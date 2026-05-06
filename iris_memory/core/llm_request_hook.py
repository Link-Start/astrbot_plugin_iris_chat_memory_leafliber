"""
LLM 请求钩子处理模块

负责处理 LLM 请求前的钩子逻辑，包括：
- L1 上下文注入
- 用户画像注入
- 图片解析（related 模式）
- 知识图谱检索结果注入

注入策略（参考 astrbot_plugin_iris_memory）：
所有内容统一注入到 req.system_prompt，使用标记包裹各 section，
支持重复调用时替换而非追加。不修改 req.contexts 和 req.prompt。
"""

import re
from typing import TYPE_CHECKING, List, Optional, cast

from iris_memory.core import get_logger

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest
    from iris_memory.core.components import ComponentManager
    from iris_memory.l1_buffer import L1Buffer
    from iris_memory.l1_buffer.models import ContextMessage
    from iris_memory.l2_memory.models import MemorySearchResult
    from iris_memory.profile.models import GroupProfile, UserProfile

logger = get_logger("llm_request_hook")

_PROMPT_SECTION_START = "<!-- iris:start:{section} -->"
_PROMPT_SECTION_END = "<!-- iris:end:{section} -->"
_PROMPT_SECTION_PATTERN = re.compile(
    r"\n*<!-- iris:start:\w+ -->.*?<!-- iris:end:\w+ -->\n*",
    re.DOTALL,
)


def _extract_original_prompt(prompt: str) -> str:
    if not prompt:
        return ""
    cleaned = _PROMPT_SECTION_PATTERN.sub("", prompt)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _wrap_prompt_section(section: str, content: str) -> str:
    start = _PROMPT_SECTION_START.format(section=section)
    end = _PROMPT_SECTION_END.format(section=section)
    return f"{start}\n{content}\n{end}"


async def preprocess_llm_request(
    event: "AstrMessageEvent",
    req: "ProviderRequest",
    component_manager: "ComponentManager",
) -> None:
    """LLM 请求钩子处理

    执行所有 LLM 对话前的预处理逻辑。

    注入策略（参考 astrbot_plugin_iris_memory，统一注入 system_prompt）：
    - req.system_prompt: 人格/L1（含内联图片）/画像/L2/L3（全部带标记替换）
    - req.contexts: 当 takeover_context 启用时清空，由插件接管上下文管理
    - req.prompt: 不修改

    Args:
        event: AstrBot 消息事件对象
        req: LLM 提供者请求对象
        component_manager: 组件管理器实例
    """
    await _parse_images_if_related_mode(event, req, component_manager)

    l1_text = await _collect_l1_context(event, req, component_manager)
    profile_text = await _collect_user_profile(event, component_manager)
    l2_text, l2_results = await _collect_l2_memory(event, component_manager)

    user_message = ""
    if hasattr(event, "message_str") and event.message_str:
        user_message = event.message_str
    elif hasattr(event, "get_message_str"):
        user_message = event.get_message_str()

    l3_text = await _collect_l3_knowledge_graph(
        event, component_manager, l2_results, user_message
    )

    _inject_all_to_system_prompt(req, l1_text, profile_text, l2_text, l3_text)

    _takeover_context_if_enabled(req)

    _log_final_context(req)


def _takeover_context_if_enabled(req: "ProviderRequest") -> None:
    """接管 AstrBot 的上下文管理

    当 takeover_context 启用时，从 req.contexts 中移除 AstrBot 自动注入的
    对话历史（user/assistant 角色），避免与插件自身的 L1/L2/L3 上下文管理
    产生冗余。

    保留策略（兼容其他插件）：
    - 保留 system 角色条目（如文件提取结果、其他插件注入的系统消息）
    - 保留带 _no_save 标记的条目（人格预设对话 begin_dialogs）
    - 保留非标准角色的条目
    - 仅移除 user/assistant 角色且无 _no_save 标记的真实对话历史条目

    参考 AstrBot 源码 astr_main_agent.py / persona_mgr.py：
    - req.contexts = json.loads(conversation.history)  # 对话历史（无 _no_save）
    - req.contexts[:0] = begin_dialogs                  # 人格开场对话（带 _no_save）
    - req.contexts.append({"role": "system", ...})      # 文件提取结果

    Args:
        req: LLM 提供者请求对象
    """
    from iris_memory.config import get_config

    config = get_config()
    if not config.get("enhancement.takeover_context"):
        return

    if not req.contexts:
        return

    original_count = len(req.contexts)
    filtered = [
        ctx
        for ctx in req.contexts
        if ctx.get("role") not in ("user", "assistant") or ctx.get("_no_save")
    ]
    removed_count = original_count - len(filtered)

    if removed_count > 0:
        req.contexts = filtered
        logger.debug(
            f"接管上下文管理：移除 {removed_count} 条对话历史，"
            f"保留 {len(filtered)} 条非对话上下文"
        )

    if req.system_prompt:
        cleaned = re.sub(
            r"\n*-{3,}\n*\[Contexts\].*",
            "",
            req.system_prompt,
            flags=re.DOTALL,
        )
        cleaned = re.sub(r"\n-{3,}\s*$", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if cleaned != req.system_prompt:
            logger.debug("接管上下文管理：清理 system_prompt 中的 [Contexts] 段")
            req.system_prompt = cleaned


def _inject_all_to_system_prompt(
    req: "ProviderRequest",
    l1_text: str,
    profile_text: str,
    l2_text: str,
    l3_text: str,
) -> None:
    """将所有内容注入到 req.system_prompt 中

    使用标记包裹各 section，支持重复调用时替换而非追加。

    注入顺序：人格 → L1 上下文 → 画像 → L2 记忆 → L3 知识图谱

    Args:
        req: LLM 提供者请求对象
        l1_text: L1 对话历史文本
        profile_text: 用户画像文本
        l2_text: 相关记忆文本
        l3_text: 知识图谱文本
    """
    original = _extract_original_prompt(req.system_prompt or "")

    sections = [
        ("l1_context", l1_text),
        ("profile", profile_text),
        ("l2_memory", l2_text),
        ("l3_kg", l3_text),
    ]

    prompt_parts = []
    if original:
        prompt_parts.append(original)

    for section_name, content in sections:
        if content:
            prompt_parts.append(_wrap_prompt_section(section_name, content))

    if prompt_parts:
        req.system_prompt = "\n\n".join(prompt_parts)
    else:
        req.system_prompt = original


async def _build_image_map(
    l1_buffer: "L1Buffer",
    group_id: str,
    component_manager: "ComponentManager",
) -> dict:
    """构建图片解析结果映射表

    从 L1 Buffer 图片队列和缓存中获取已解析的图片内容，
    按 message_id 和时间窗口关联到对应的消息。

    Args:
        l1_buffer: L1 Buffer 实例
        group_id: 群聊 ID
        component_manager: 组件管理器实例

    Returns:
        映射表，key 为 message_id 或 (user_id, timestamp_window)，value为图片描述列表
    """
    from iris_memory.image import ImageParseStatus

    cache_manager = component_manager.get_component("image_cache")

    all_images = l1_buffer.get_images(group_id, only_pending=False)
    if not all_images:
        return {}

    image_map: dict[str, list[str]] = {}

    for img_item in all_images:
        if img_item.status != ImageParseStatus.SUCCESS:
            continue

        desc: Optional[str] = None

        if cache_manager and cache_manager.is_available:
            cached = await cache_manager.get_cache(img_item.image_hash)
            if cached and cached.content:
                desc = cached.content

        if not desc:
            continue

        if img_item.message_id:
            key = img_item.message_id
        else:
            ts = img_item.timestamp
            key = f"{img_item.user_id}:{ts.hour}:{ts.minute}"

        if key not in image_map:
            image_map[key] = []
        image_map[key].append(desc)

    return image_map


def _get_inline_image_desc(
    msg: "ContextMessage",
    msg_id: Optional[str],
    image_map: dict,
) -> str:
    """获取消息的行内图片描述

    根据消息 ID 或时间窗口匹配图片解析结果，
    返回行内格式的图片描述文本。

    Args:
        msg: 上下文消息
        msg_id: 消息 ID
        image_map: 图片映射表

    Returns:
        行内图片描述，如 " [图片：一只猫的照片]"，无匹配时返回空字符串
    """
    if not image_map:
        return ""

    descs: Optional[list[str]] = None

    if msg_id and msg_id in image_map:
        descs = image_map[msg_id]
    else:
        ts = msg.timestamp
        source = msg.source
        key = f"{source}:{ts.hour}:{ts.minute}"
        descs = image_map.get(key)

    if not descs:
        return ""

    if len(descs) == 1:
        return f" [图片：{descs[0]}]"

    parts = "；".join(descs)
    return f" [图片：{parts}]"


async def _collect_l1_context(
    event: "AstrMessageEvent",
    req: "ProviderRequest",
    component_manager: "ComponentManager",
) -> str:
    """收集 L1 上下文文本（不直接修改 req）

    将 L1 上下文格式化为纯文本返回，用于注入到 system_prompt。
    格式参考 astrbot_plugin_iris_memory 的 ChatHistoryBuffer.format_for_llm。

    Args:
        event: AstrBot 消息事件对象
        req: LLM 提供者请求对象
        component_manager: 组件管理器实例

    Returns:
        格式化的 L1 上下文文本，不可用时返回空字符串
    """
    from iris_memory.platform import get_adapter

    buffer = component_manager.get_available_component("l1_buffer")
    if not buffer:
        logger.debug("L1 Buffer 组件不可用，跳过上下文注入")
        return ""

    from iris_memory.config import get_config

    config = get_config()

    l1_buffer = cast("L1Buffer", buffer)

    adapter = get_adapter(event)
    group_id = adapter.get_group_id(event)

    max_length = cast(int, config.get("l1_buffer.inject_queue_length", 30))

    messages = l1_buffer.get_context(group_id, max_length)
    if not messages:
        logger.debug(f"群聊 {group_id} 的 L1 上下文为空，跳过注入")
        return ""

    current_user_id = adapter.get_user_id(event)
    if (
        current_user_id
        and messages
        and messages[-1].role == "user"
        and messages[-1].source == current_user_id
    ):
        messages = messages[:-1]

    if not messages:
        logger.debug(f"群聊 {group_id} 排除当前消息后 L1 上下文为空，跳过注入")
        return ""

    image_map = await _build_image_map(l1_buffer, group_id, component_manager)

    max_content_chars = cast(int, config.get("l1_buffer.inject_max_content_chars", 200))

    lines = []
    if group_id:
        lines.append("【近期群聊记录】")
        lines.append(
            "以下是群里最近的对话，帮助你了解当前话题。"
            "其中 [图片] 标记为对话中发送的图片的辅助描述，"
            "仅用于辅助理解对话内容："
        )
    else:
        lines.append("【近期对话记录】")
        lines.append(
            "以下是你们最近的对话。"
            "其中 [图片] 标记为对话中发送的图片的辅助描述，"
            "仅用于辅助理解对话内容："
        )

    msg_id_map: dict[str, tuple[str, str]] = {}
    for msg in messages:
        if msg.metadata:
            mid = msg.metadata.get("message_id")
            if mid:
                uname = (
                    msg.metadata.get("user_name", "") if msg.role == "user" else "Bot"
                )
                msg_id_map[str(mid)] = (msg.content, uname)

    for msg in messages:
        content = msg.content
        role = msg.role

        if max_content_chars > 0 and len(content) > max_content_chars:
            content = content[:max_content_chars] + "..."

        if role == "user":
            user_name = msg.metadata.get("user_name") if msg.metadata else None
            reply_content = msg.metadata.get("reply_content") if msg.metadata else None
            reply_user_name = (
                msg.metadata.get("reply_user_name") if msg.metadata else None
            )

            if not reply_content and msg.metadata:
                reply_mid = msg.metadata.get("reply_message_id")
                if reply_mid and str(reply_mid) in msg_id_map:
                    ref_content, ref_name = msg_id_map[str(reply_mid)]
                    reply_content = ref_content
                    if not reply_user_name and ref_name:
                        reply_user_name = ref_name

            reply_tag = ""
            if reply_content:
                ref_sender = reply_user_name or "某人"
                if len(reply_content) > 80:
                    reply_content = reply_content[:80] + "..."
                reply_tag = f" ↩️回复{ref_sender}「{reply_content}」"
            elif msg.metadata and msg.metadata.get("reply_message_id"):
                reply_tag = " ↩️回复了某条消息"

            sender = user_name or "对方"

            msg_id = msg.metadata.get("message_id") if msg.metadata else None
            image_desc = _get_inline_image_desc(msg, msg_id, image_map)

            lines.append(f"{sender}:{reply_tag} {content}{image_desc}")
        elif role == "assistant":
            lines.append(f"Bot: {content}")

    try:
        req._l1_context_count = len(messages)
    except AttributeError:
        pass

    logger.debug(f"已收集 {len(messages)} 条 L1 上下文消息到群聊 {group_id}")

    return "\n".join(lines)


async def _collect_user_profile(
    event: "AstrMessageEvent",
    component_manager: "ComponentManager",
) -> str:
    """收集用户画像文本（不直接修改 req）

    Args:
        event: AstrBot 消息事件对象
        component_manager: 组件管理器实例

    Returns:
        格式化的画像文本，不可用时返回空字符串
    """
    from iris_memory.config import get_config
    from iris_memory.platform import get_adapter

    config = get_config()
    if not config.get("profile.enable"):
        return ""

    enable_auto_injection = config.get("profile.enable_auto_injection")
    if enable_auto_injection is not None and not enable_auto_injection:
        return ""

    profile_storage = component_manager.get_available_component("profile")
    if not profile_storage:
        logger.debug("画像系统组件不可用，跳过画像注入")
        return ""

    adapter = get_adapter(event)
    group_id = adapter.get_group_id(event)
    user_id = adapter.get_user_id(event)

    if not user_id:
        logger.debug("无法获取用户ID，跳过画像注入")
        return ""

    effective_group_id = (
        group_id if config.get("isolation_config.enable_group_isolation") else "default"
    )

    from iris_memory.profile import GroupProfileManager, UserProfileManager

    group_manager = GroupProfileManager(profile_storage)
    user_manager = UserProfileManager(profile_storage)

    group_profile = await group_manager.get_or_create(group_id)
    user_profile = await user_manager.get_or_create(user_id, effective_group_id)

    profile_text = _format_profiles_for_injection(group_profile, user_profile)

    if profile_text:
        logger.debug(f"已收集画像信息：群聊 {group_id} 用户 {user_id}")

    return profile_text


async def _rewrite_query_for_retrieval(
    user_message: str, component_manager: "ComponentManager"
) -> Optional[str]:
    """查询改写：从用户消息中提取检索意图

    使用 LLM 将用户原始消息改写为更适合向量检索的查询文本。
    例如："你还记得我喜欢什么吗？" → "用户偏好 喜好"

    Args:
        user_message: 用户原始消息
        component_manager: 组件管理器实例

    Returns:
        改写后的查询文本，失败时返回 None（使用原始消息）
    """
    from iris_memory.config import get_config
    import asyncio

    config = get_config()

    if not config.get("l2_query_rewrite_enable", True):
        return None

    llm_manager = component_manager.get_component("llm_manager")
    if not llm_manager or not llm_manager.is_available:
        return None

    prompt = (
        "从以下用户消息中提取用于记忆检索的关键信息，输出简洁的搜索关键词。\n"
        "规则：\n"
        "1. 只输出搜索关键词，不要解释\n"
        "2. 去除无意义的口语和语气词\n"
        "3. 提取核心实体、事件和偏好\n"
        "4. 如果消息是询问记忆相关的内容，提取被询问的主题\n"
        "5. 多个关键词用空格分隔\n"
        "6. 如果消息不包含可检索的信息（如纯闲聊），输出：无\n\n"
        f"用户消息：{user_message}\n\n搜索关键词："
    )

    timeout_ms = config.get("l2_query_rewrite_timeout_ms", 3000)

    try:
        rewritten = await asyncio.wait_for(
            llm_manager.generate(prompt=prompt, module="l2_query_rewrite"),
            timeout=timeout_ms / 1000.0,
        )

        rewritten = rewritten.strip()

        if not rewritten or rewritten == "无":
            logger.debug("查询改写结果为空，使用原始消息")
            return None

        logger.debug(f"查询改写：'{user_message[:30]}...' -> '{rewritten}'")
        return rewritten

    except asyncio.TimeoutError:
        logger.debug(f"查询改写超时（{timeout_ms}ms），使用原始消息")
        return None
    except Exception as e:
        logger.debug(f"查询改写失败：{e}，使用原始消息")
        return None


async def _collect_l2_memory(
    event: "AstrMessageEvent",
    component_manager: "ComponentManager",
) -> tuple[str, List["MemorySearchResult"]]:
    """收集 L2 记忆文本（不直接修改 req）

    执行 L2 向量检索并返回格式化文本和检索结果。

    Args:
        event: AstrBot 消息事件对象
        component_manager: 组件管理器实例

    Returns:
        (格式化的记忆文本, L2 检索结果列表)
    """
    from iris_memory.config import get_config
    from iris_memory.platform import get_adapter

    config = get_config()

    if not config.get("l2_memory.enable"):
        logger.debug("L2 记忆库未启用，跳过记忆注入")
        return "", []

    l2_status = component_manager.check_component("l2_memory")
    if l2_status == "disabled":
        logger.debug("L2 记忆库未启用，跳过记忆注入")
        return "", []
    if l2_status == "initializing":
        logger.debug("L2 记忆库正在初始化中，跳过记忆注入")
        return "", []
    if l2_status != "available":
        logger.debug("L2 记忆库组件不可用，跳过记忆注入")
        return "", []

    adapter = get_adapter(event)
    group_id = adapter.get_group_id(event)

    query_text = ""
    if hasattr(event, "message_str") and event.message_str:
        query_text = event.message_str
    elif hasattr(event, "get_message_str"):
        query_text = event.get_message_str()

    if not query_text:
        logger.debug("无法获取用户消息，跳过记忆检索")
        return "", []

    try:
        rewritten_query = await _rewrite_query_for_retrieval(
            query_text, component_manager
        )
        search_query = rewritten_query if rewritten_query else query_text

        from iris_memory.l2_memory import MemoryRetriever

        llm_manager = component_manager.get_component("llm_manager")
        retriever = MemoryRetriever(component_manager, llm_manager)

        enable_graph = config.get("l2_memory.enable_graph_enhancement", False)
        enable_rerank = config.get("enhancement.enable_rerank", False)

        if enable_graph or enable_rerank:
            context_text = await retriever.retrieve_for_context(
                query=search_query,
                group_id=group_id,
                max_tokens=config.get("token_budget_max_tokens", 2000),
            )

            results = await retriever.retrieve(search_query, group_id)

            if context_text:
                logger.debug(f"已收集增强检索记忆到群聊 {group_id}")

            return context_text, results
        else:
            results = await retriever.retrieve(search_query, group_id)

            if not results:
                logger.debug("L2 检索未找到相关记忆")
                return "", []

            from iris_memory.enhancement import TokenBudgetController

            budget_controller = TokenBudgetController()
            max_tokens = config.get("token_budget_max_tokens", 2000)

            trimmed_results, actual_tokens = budget_controller.trim_memories(
                memories=results, max_tokens=max_tokens
            )

            logger.debug(
                f"L2 检索到 {len(results)} 条记忆，裁剪后 {len(trimmed_results)} 条"
            )

            memory_text = _format_l2_memories_for_injection(trimmed_results)

            if memory_text:
                logger.debug(f"已收集 L2 记忆到群聊 {group_id}")

            return memory_text, trimmed_results

    except Exception as e:
        logger.error(f"L2 记忆注入失败: {e}", exc_info=True)
        return "", []


async def _collect_l3_knowledge_graph(
    event: "AstrMessageEvent",
    component_manager: "ComponentManager",
    l2_results: List["MemorySearchResult"],
    user_message: str = "",
) -> str:
    """收集 L3 知识图谱文本（不直接修改 req）

    检索策略：
    1. 当 enable_graph_enhancement=True 时跳过（L2 阶段已处理）
    2. 优先基于 L2 记忆关联的节点 ID 进行路径扩展
    3. 若 L2 结果无节点 ID，则基于用户消息关键词搜索图谱
    4. 两种策略的结果合并去重

    Args:
        event: AstrBot 消息事件对象
        component_manager: 组件管理器实例
        l2_results: L2 检索结果
        user_message: 用户当前消息文本

    Returns:
        格式化的图谱文本，不可用时返回空字符串
    """
    from iris_memory.config import get_config
    from iris_memory.platform import get_adapter

    config = get_config()

    if not config.get("l3_kg.enable"):
        logger.debug("L3 知识图谱未启用，跳过图谱注入")
        return ""

    l3_status = component_manager.check_component("l3_kg")
    if l3_status == "disabled":
        logger.debug("L3 知识图谱未启用，跳过图谱注入")
        return ""
    if l3_status == "initializing":
        logger.debug("L3 知识图谱正在初始化中，跳过图谱注入")
        return ""
    if l3_status != "available":
        logger.debug("L3 知识图谱组件不可用，跳过图谱注入")
        return ""

    kg_adapter = component_manager.get_available_component("l3_kg")

    adapter = get_adapter(event)
    group_id = adapter.get_group_id(event)

    try:
        enable_graph_enhancement = config.get(
            "l2_memory.enable_graph_enhancement", False
        )

        if enable_graph_enhancement:
            logger.debug("图增强已在 L2 阶段执行，跳过 L3 独立图谱注入以避免重复")
            return ""

        from iris_memory.l3_kg import GraphRetriever

        retriever = GraphRetriever(kg_adapter)

        all_nodes: dict[str, dict] = {}
        all_edges: dict[str, dict] = {}

        memory_node_ids: List[str] = []
        if l2_results:
            for result in l2_results:
                metadata = result.entry.metadata
                node_id = (
                    metadata.get("memory_node_id")
                    or metadata.get("kg_node_id")
                    or metadata.get("node_id")
                    or metadata.get("entity_id")
                )
                if node_id:
                    memory_node_ids.append(node_id)

        if memory_node_ids:
            nodes, edges = await retriever.retrieve_with_expansion(
                memory_node_ids=memory_node_ids, group_id=group_id
            )
            for n in nodes:
                nid = n.get("id")
                if nid:
                    all_nodes[nid] = n
            for e in edges:
                eid = f"{e.get('source', '')}-{e.get('relation_type', '')}-{e.get('target', '')}"
                all_edges[eid] = e
            logger.debug(f"基于 L2 节点扩展：{len(nodes)} 节点，{len(edges)} 边")

        if not memory_node_ids and user_message:
            keywords = _extract_kg_keywords(user_message)
            if keywords:
                nodes, edges = await retriever.retrieve_by_keywords(
                    keywords=keywords, group_id=group_id
                )
                for n in nodes:
                    nid = n.get("id")
                    if nid:
                        all_nodes[nid] = n
                for e in edges:
                    eid = f"{e.get('source', '')}-{e.get('relation_type', '')}-{e.get('target', '')}"
                    all_edges[eid] = e
                logger.debug(f"基于关键词检索：{len(nodes)} 节点，{len(edges)} 边")

        if not all_nodes:
            return ""

        l3_max_tokens = cast(int, config.get("l3_kg.max_inject_tokens", 400))

        graph_text = retriever.format_for_context(
            list(all_nodes.values()),
            list(all_edges.values()),
            max_tokens=l3_max_tokens,
        )

        if graph_text:
            node_ids = [nid for nid in all_nodes.keys()]
            await retriever.update_access_count(node_ids)

            logger.debug(f"图谱检索完成（{len(all_nodes)} 节点，{len(all_edges)} 边）")

        return graph_text

    except Exception as e:
        logger.error(f"L3 知识图谱注入失败: {e}", exc_info=True)
        return ""


def _extract_kg_keywords(text: str) -> List[str]:
    """从用户消息中提取知识图谱检索关键词

    Args:
        text: 用户消息文本

    Returns:
        关键词列表
    """
    import re

    if not text:
        return []

    keywords: List[str] = []

    quoted = re.findall(r'[""「」『』]([^""「」『』]+)[""「」『』]', text)
    keywords.extend(quoted)

    chinese_words = re.findall(r"[\u4e00-\u9fa5]{2,6}", text)
    stopwords = {
        "什么",
        "怎么",
        "如何",
        "为什么",
        "这个",
        "那个",
        "今天",
        "昨天",
        "明天",
        "喜欢",
        "觉得",
        "想要",
        "可以",
        "知道",
        "一下",
        "一些",
        "告诉",
        "请问",
        "还是",
        "的话",
        "不是",
        "没有",
        "什么",
        "现在",
        "已经",
        "应该",
        "可能",
        "因为",
        "所以",
        "但是",
    }
    filtered = [w for w in chinese_words if w not in stopwords and len(w) >= 2]
    keywords.extend(filtered)

    seen = set()
    unique: List[str] = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)

    return unique[:8]


def _format_l2_memories_for_injection(memories: List["MemorySearchResult"]) -> str:
    """格式化 L2 记忆为注入文本

    格式参考 astrbot_plugin_iris_memory 的 MemoryFormatter._format_natural_style。

    Args:
        memories: L2 记忆检索结果列表

    Returns:
        格式化的记忆文本
    """
    if not memories:
        return ""

    lines = [
        "【你记得的事情】",
        "以下是你和群友之间的往事，请用自己的话自然提及，不要暴露「记录」「数据」等概念：",
    ]

    for memory in memories:
        lines.append(f"- {memory.entry.content}")

    return "\n".join(lines)


def _format_profiles_for_injection(
    group_profile: "GroupProfile", user_profile: "UserProfile"
) -> str:
    """格式化画像为注入文本

    格式参考 astrbot_plugin_iris_memory 的 PersonaCoordinator._build_persona_summary。

    Args:
        group_profile: 群聊画像对象
        user_profile: 用户画像对象

    Returns:
        格式化的画像文本
    """
    parts = ["【用户画像】"]

    if user_profile.user_name:
        parts.append(f"昵称: {user_profile.user_name}")
    if user_profile.personality_tags:
        parts.append(f"性格: {', '.join(user_profile.personality_tags[:3])}")
    if user_profile.interests:
        parts.append(f"兴趣: {', '.join(user_profile.interests[:3])}")
    if user_profile.communication_style:
        parts.append(f"沟通偏好: {user_profile.communication_style}")
    if user_profile.emotional_baseline:
        parts.append(f"情感: {user_profile.emotional_baseline}")
    if user_profile.bot_relationship:
        parts.append(f"称呼: {user_profile.bot_relationship}")
    if user_profile.taboo_topics:
        parts.append(f"禁忌: {', '.join(user_profile.taboo_topics)}")

    group_parts = []
    if group_profile.interests:
        group_parts.append(f"兴趣: {', '.join(group_profile.interests[:3])}")
    if group_profile.atmosphere_tags:
        group_parts.append(f"氛围: {', '.join(group_profile.atmosphere_tags[:3])}")
    if group_profile.blacklist_topics:
        group_parts.append(f"禁忌: {', '.join(group_profile.blacklist_topics)}")

    if group_parts:
        parts.append("群聊: " + ", ".join(group_parts))

    return "\n".join(parts) if len(parts) > 1 else ""


async def _parse_images_if_related_mode(
    event: "AstrMessageEvent",
    req: "ProviderRequest",
    component_manager: "ComponentManager",
) -> None:
    """解析图片并注入 LLM 上下文（related 模式）

    仅在 related 模式下解析 L1 Buffer 范围内的图片。
    all 模式已在消息钩子中处理。

    流程：
    1. 获取 L1Buffer 图片队列中的待解析图片
    2. 检查缓存，过滤已解析的图片
    3. 批量解析（并发控制、数量限制）
    4. 结果存入缓存
    5. 注入 LLM 上下文

    Args:
        event: AstrBot 消息事件对象
        req: LLM 提供者请求对象
        component_manager: 组件管理器实例
    """
    from iris_memory.config import get_config
    from iris_memory.platform import get_adapter
    from iris_memory.image import ImageParser, ImageParseStatus, ImageParseCache
    import asyncio

    config = get_config()
    if not config.get("image_parsing.enable"):
        return

    mode = config.get("image_parsing.parsing_mode", "related")

    if mode == "all":
        return

    if mode != "related":
        logger.warning(f"未知的图片解析模式：{mode}")
        return

    adapter = get_adapter(event)
    group_id = adapter.get_group_id(event)

    buffer = component_manager.get_available_component("l1_buffer")
    if not buffer:
        return

    l1_buffer = cast("L1Buffer", buffer)

    cache_manager = component_manager.get_available_component("image_cache")
    quota_manager = component_manager.get_available_component("image_quota")
    llm_manager = component_manager.get_available_component("llm_manager")

    if not llm_manager:
        logger.warning("LLM Manager 不可用，跳过图片解析")
        return

    max_parse = config.get("image_parsing.max_parse_per_request", 5)
    max_concurrent = config.get("image_parsing.max_concurrent_parse", 3)

    pending_images = l1_buffer.get_images(group_id, limit=max_parse, only_pending=True)

    if not pending_images:
        return

    images_to_parse = []
    cached_results = []

    for img_item in pending_images:
        if cache_manager and cache_manager.is_available:
            cached = await cache_manager.get_cache(img_item.image_hash)
            if cached:
                l1_buffer.mark_image_parsed(
                    group_id, img_item.image_hash, ImageParseStatus.SUCCESS
                )
                cached_results.append((img_item, cached))
                continue

        images_to_parse.append(img_item)

    if cached_results:
        logger.debug(f"从缓存读取 {len(cached_results)} 条图片解析结果")

    all_image_results = []

    for img_item, cached in cached_results:
        all_image_results.append(
            {"timestamp": img_item.timestamp, "content": cached.content}
        )

    if not images_to_parse:
        total_cached = len(all_image_results)
        if total_cached > 0:
            logger.info(
                f"已从缓存获取 {total_cached} 条图片解析结果，将内联到 L1 上下文中"
            )
        return

    if quota_manager and quota_manager.is_available:
        has_quota = await quota_manager.check_quota()
        if not has_quota:
            logger.info("图片解析配额已耗尽，跳过解析")
            return

        quota_used = await quota_manager.use_quota(len(images_to_parse))
        if not quota_used:
            logger.warning("图片解析配额使用失败")
            return

    provider = config.get("image_parsing.provider", "")
    parser = ImageParser(llm_manager, provider)

    logger.info(f"开始解析 {len(images_to_parse)} 张图片（related 模式）")

    semaphore = asyncio.Semaphore(max_concurrent)

    async def parse_with_semaphore(img_item):
        async with semaphore:
            if not img_item.image_info or not img_item.image_info.has_url:
                return (img_item, None)
            result = await parser.parse(img_item.image_info)
            return (img_item, result)

    parse_tasks = [parse_with_semaphore(img) for img in images_to_parse]
    parse_results = await asyncio.gather(*parse_tasks)

    success_count = 0
    for img_item, result in parse_results:
        if result is None:
            l1_buffer.mark_image_parsed(
                group_id, img_item.image_hash, ImageParseStatus.FAILED
            )
            continue

        if not result.success:
            logger.warning(f"图片解析失败：{result.error_message}")
            l1_buffer.mark_image_parsed(
                group_id, img_item.image_hash, ImageParseStatus.FAILED
            )
            continue

        if not result.content:
            logger.debug("图片解析结果为空")
            l1_buffer.mark_image_parsed(
                group_id, img_item.image_hash, ImageParseStatus.FAILED
            )
            continue

        if cache_manager and cache_manager.is_available:
            cache = ImageParseCache(
                image_hash=img_item.image_hash,
                content=result.content,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            await cache_manager.set_cache(cache)

        l1_buffer.mark_image_parsed(
            group_id, img_item.image_hash, ImageParseStatus.SUCCESS
        )

        all_image_results.append(
            {"timestamp": img_item.timestamp, "content": result.content}
        )

        success_count += 1

    total_injected = len(all_image_results)
    if total_injected > 0:
        logger.info(
            f"已解析 {success_count} 张新图片，缓存 {len(cached_results)} 张，"
            f"共 {total_injected} 条图片解析结果将内联到 L1 上下文中"
        )


def _log_final_context(req: "ProviderRequest") -> None:
    """输出最终上下文内容的 debug 日志

    在所有注入完成后，输出完整的上下文信息用于问题排查。

    Args:
        req: LLM 提供者请求对象
    """
    from iris_memory.config import get_config

    config = get_config()
    if not config.get("enable_context_logging", False):
        return

    log_parts = ["\n" + "=" * 60 + "\n[LLM 请求上下文详情]\n" + "=" * 60]

    if req.system_prompt:
        log_parts.append(
            f"\n[System Prompt]\n{'-' * 40}\n{req.system_prompt}\n{'-' * 40}"
        )
    else:
        log_parts.append("\n[System Prompt]\n(无)")

    if req.contexts:
        log_parts.append(f"\n[Contexts] (共 {len(req.contexts)} 条)")
        for i, ctx in enumerate(req.contexts, 1):
            role = ctx.get("role", "unknown")
            content = ctx.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            log_parts.append(f"  [{i}] {role}: {content}")
    else:
        log_parts.append("\n[Contexts]\n(无)")

    if hasattr(req, "functions") and req.functions:
        log_parts.append(f"\n[Functions] (共 {len(req.functions)} 个)")
        for i, func in enumerate(req.functions, 1):
            name = (
                func.get("name", "unknown")
                if isinstance(func, dict)
                else getattr(func, "name", "unknown")
            )
            log_parts.append(f"  [{i}] {name}")

    log_parts.append("\n" + "=" * 60)

    logger.debug("\n".join(log_parts))
