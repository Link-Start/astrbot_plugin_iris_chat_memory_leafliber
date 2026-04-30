"""
LLM 请求钩子处理模块

负责处理 LLM 请求前的钩子逻辑，包括：
- L1 上下文注入
- 用户画像注入
- 图片解析（related 模式）
- 知识图谱检索结果注入（未来扩展）
"""

import re
from typing import TYPE_CHECKING, List, Optional, cast

from iris_memory.core import get_logger

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest
    from iris_memory.core.components import ComponentManager
    from iris_memory.l1_buffer import L1Buffer
    from iris_memory.l2_memory.models import MemorySearchResult
    from iris_memory.profile.models import GroupProfile, UserProfile

logger = get_logger("llm_request_hook")

_PROMPT_SECTION_START = "<!-- iris:start:{section} -->"
_PROMPT_SECTION_END = "<!-- iris:end:{section} -->"
_PROMPT_SECTION_PATTERN = re.compile(
    r"\n*<!-- iris:start:\w+ -->.*?<!-- iris:end:\w+ -->\n*",
    re.DOTALL,
)

_L1_CONTEXT_START_MARKER = "<!-- iris:l1_context:start -->"
_L1_CONTEXT_END_MARKER = "<!-- iris:l1_context:end -->"
_L1_CONTEXT_PATTERN = re.compile(
    r"\n*<!-- iris:l1_context:start -->.*?<!-- iris:l1_context:end -->\n*",
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


def _find_l1_context_system_message(contexts: list) -> int | None:
    for i, ctx in enumerate(contexts):
        if ctx.get("role") == "system" and _L1_CONTEXT_START_MARKER in ctx.get(
            "content", ""
        ):
            return i
    return None


def _extract_l1_content_from_system_message(content: str) -> str:
    match = _L1_CONTEXT_PATTERN.search(content)
    if not match:
        return ""
    inner = match.group()
    inner = inner.replace(_L1_CONTEXT_START_MARKER, "").replace(
        _L1_CONTEXT_END_MARKER, ""
    )
    return inner.strip()


def _replace_l1_in_system_message(content: str, new_l1_text: str) -> str:
    if not new_l1_text:
        cleaned = _L1_CONTEXT_PATTERN.sub("", content)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned
    replacement = f"\n{_L1_CONTEXT_START_MARKER}\n{new_l1_text}\n{_L1_CONTEXT_END_MARKER}\n"
    result = _L1_CONTEXT_PATTERN.sub(replacement, content)
    return result.strip()


def _remove_l1_context_block(contexts: list) -> list:
    idx = _find_l1_context_system_message(contexts)
    if idx is None:
        return contexts

    old_content = contexts[idx]["content"]
    cleaned = _L1_CONTEXT_PATTERN.sub("", old_content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if cleaned:
        new_contexts = contexts[:idx] + [{"role": "system", "content": cleaned}] + contexts[idx + 1 :]
    else:
        new_contexts = contexts[:idx] + contexts[idx + 1 :]

    return new_contexts


async def preprocess_llm_request(
    event: "AstrMessageEvent",
    req: "ProviderRequest",
    component_manager: "ComponentManager",
) -> None:
    """LLM 请求钩子处理

    执行所有 LLM 对话前的预处理逻辑。

    注入顺序（最终 prompt 从上到下）：
    1. 原始系统提示词
    2. 用户画像
    3. 知识图谱
    4. 相关记忆（最接近用户查询）

    Args:
        event: AstrBot 消息事件对象
        req: LLM 提供者请求对象
        component_manager: 组件管理器实例
    """
    await _inject_l1_context(event, req, component_manager)

    profile_text = await _collect_user_profile(event, component_manager)
    l2_text, l2_results = await _collect_l2_memory(event, component_manager)
    l3_text = await _collect_l3_knowledge_graph(event, component_manager, l2_results)

    original_prompt = _extract_original_prompt(req.prompt or "")

    sections = [
        ("profile", profile_text),
        ("l3_kg", l3_text),
        ("l2_memory", l2_text),
    ]

    prompt_parts = []
    if original_prompt:
        prompt_parts.append(original_prompt)

    for section_name, content in sections:
        if content:
            prompt_parts.append(_wrap_prompt_section(section_name, content))

    if prompt_parts:
        req.prompt = "\n\n".join(prompt_parts)
    else:
        req.prompt = original_prompt

    await _parse_images_if_related_mode(event, req, component_manager)

    _log_final_context(req)


async def _inject_l1_context(
    event: "AstrMessageEvent",
    req: "ProviderRequest",
    component_manager: "ComponentManager",
) -> None:
    """注入 L1 上下文到 LLM 请求（内部函数）

    将 L1 上下文合并到单个 system 角色消息中，使用标记包裹，
    以兼容 OpenAI API（不支持多个 system 消息）。

    Args:
        event: AstrBot 消息事件对象
        req: LLM 提供者请求对象
        component_manager: 组件管理器实例
    """
    from iris_memory.platform import get_adapter

    existing_contexts = req.contexts or []

    buffer = component_manager.get_component("l1_buffer")
    if not buffer or not buffer.is_available:
        logger.debug("L1 Buffer 组件不可用，跳过上下文注入")
        l1_idx = _find_l1_context_system_message(existing_contexts)
        if l1_idx is not None:
            existing_contexts = _remove_l1_context_block(existing_contexts)
        req.contexts = existing_contexts
        return

    l1_buffer = cast("L1Buffer", buffer)

    adapter = get_adapter(event)
    group_id = adapter.get_group_id(event)

    max_length = 20

    messages = l1_buffer.get_context(group_id, max_length)
    if not messages:
        logger.debug(f"群聊 {group_id} 的 L1 上下文为空，跳过注入")
        l1_idx = _find_l1_context_system_message(existing_contexts)
        if l1_idx is not None:
            existing_contexts = _remove_l1_context_block(existing_contexts)
        req.contexts = existing_contexts
        return

    context_lines = []
    for msg in messages:
        content = msg.content
        if msg.role == "user":
            user_name = msg.metadata.get("user_name") if msg.metadata else None
            reply_content = msg.metadata.get("reply_content") if msg.metadata else None
            reply_user_name = (
                msg.metadata.get("reply_user_name") if msg.metadata else None
            )

            if user_name:
                content = f"[{user_name}]: {content}"

            if reply_content:
                reply_prefix = f"回复[{reply_user_name}]" if reply_user_name else "回复"
                content = f"{reply_prefix}「{reply_content}」\n{content}"

        context_lines.append(f"{msg.role}: {content}")

    l1_text = "\n".join(context_lines)

    l1_idx = _find_l1_context_system_message(existing_contexts)
    if l1_idx is not None:
        old_content = existing_contexts[l1_idx]["content"]
        new_content = _replace_l1_in_system_message(old_content, l1_text)
        existing_contexts[l1_idx] = {"role": "system", "content": new_content}
        req.contexts = existing_contexts
    else:
        l1_block_content = (
            f"{_L1_CONTEXT_START_MARKER}\n{l1_text}\n{_L1_CONTEXT_END_MARKER}"
        )
        l1_message = {"role": "system", "content": l1_block_content}
        req.contexts = [l1_message] + existing_contexts

    try:
        req._l1_context_count = len(messages)
    except AttributeError:
        pass

    logger.debug(f"已注入 {len(messages)} 条 L1 上下文消息到群聊 {group_id}")


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

    profile_storage = component_manager.get_component("profile")
    if not profile_storage or not profile_storage.is_available:
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

    l2_adapter = component_manager.get_component("l2_memory")
    if not l2_adapter or not l2_adapter.is_available:
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
) -> str:
    """收集 L3 知识图谱文本（不直接修改 req）

    当 enable_graph_enhancement=True 时跳过（L2 阶段已处理）。
    否则基于 L2 记忆关联的节点 ID 进行路径扩展。

    Args:
        event: AstrBot 消息事件对象
        component_manager: 组件管理器实例
        l2_results: L2 检索结果

    Returns:
        格式化的图谱文本，不可用时返回空字符串
    """
    from iris_memory.config import get_config
    from iris_memory.platform import get_adapter

    config = get_config()

    if not config.get("l3_kg.enable"):
        logger.debug("L3 知识图谱未启用，跳过图谱注入")
        return ""

    kg_adapter = component_manager.get_component("l3_kg")
    if not kg_adapter or not kg_adapter.is_available:
        logger.debug("L3 知识图谱组件不可用，跳过图谱注入")
        return ""

    adapter = get_adapter(event)
    group_id = adapter.get_group_id(event)

    try:
        enable_graph_enhancement = config.get(
            "l2_memory.enable_graph_enhancement", False
        )

        if enable_graph_enhancement:
            logger.debug("图增强已在 L2 阶段执行，跳过 L3 独立图谱注入以避免重复")
            return ""

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
            from iris_memory.l3_kg import GraphRetriever

            retriever = GraphRetriever(kg_adapter)

            nodes, edges = await retriever.retrieve_with_expansion(
                memory_node_ids=memory_node_ids, group_id=group_id
            )

            if nodes or edges:
                graph_text = retriever.format_for_context(nodes, edges)

                if graph_text:
                    logger.debug(
                        f"纯图谱检索完成（基于 {len(memory_node_ids)} 个记忆节点）"
                    )
                    return graph_text

        return ""

    except Exception as e:
        logger.error(f"L3 知识图谱注入失败: {e}", exc_info=True)
        return ""


def _format_l2_memories_for_injection(memories: List["MemorySearchResult"]) -> str:
    """格式化 L2 记忆为注入文本

    Args:
        memories: L2 记忆检索结果列表

    Returns:
        格式化的记忆文本
    """
    if not memories:
        return ""

    lines = ["【相关记忆】"]

    for memory in memories:
        lines.append(f"• {memory.entry.content}")

    return "\n".join(lines)


def _format_profiles_for_injection(
    group_profile: "GroupProfile", user_profile: "UserProfile"
) -> str:
    """格式化画像为注入文本

    Args:
        group_profile: 群聊画像对象
        user_profile: 用户画像对象

    Returns:
        格式化的画像文本
    """
    parts = []

    group_parts = []
    if group_profile.interests:
        group_parts.append(f"兴趣:{','.join(group_profile.interests[:3])}")
    if group_profile.atmosphere_tags:
        group_parts.append(f"氛围:{','.join(group_profile.atmosphere_tags[:3])}")
    if group_profile.blacklist_topics:
        group_parts.append(f"禁忌:{','.join(group_profile.blacklist_topics)}")

    if group_parts:
        parts.append(f"【群聊】{' | '.join(group_parts)}")

    user_parts = []
    if user_profile.user_name:
        user_parts.append(f"昵称:{user_profile.user_name}")
    if user_profile.personality_tags:
        user_parts.append(f"性格:{','.join(user_profile.personality_tags[:3])}")
    if user_profile.interests:
        user_parts.append(f"兴趣:{','.join(user_profile.interests[:3])}")
    if user_profile.bot_relationship:
        user_parts.append(f"称呼:{user_profile.bot_relationship}")
    if user_profile.taboo_topics:
        user_parts.append(f"禁忌:{','.join(user_profile.taboo_topics)}")

    if user_parts:
        parts.append(f"【用户】{' | '.join(user_parts)}")

    return "\n".join(parts) if parts else ""


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

    buffer = component_manager.get_component("l1_buffer")
    if not buffer or not buffer.is_available:
        return

    l1_buffer = cast("L1Buffer", buffer)

    cache_manager = component_manager.get_component("image_cache")
    quota_manager = component_manager.get_component("image_quota")
    llm_manager = component_manager.get_component("llm_manager")

    if not llm_manager or not llm_manager.is_available:
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
        _insert_images_by_time(req, all_image_results)
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

    _insert_images_by_time(req, all_image_results)

    total_injected = len(all_image_results)
    if total_injected > 0:
        logger.info(
            f"已注入 {total_injected} 条图片解析结果到 LLM 上下文 "
            f"（新解析 {success_count}，缓存 {len(cached_results)}）"
        )


def _insert_images_by_time(req: "ProviderRequest", image_results: list) -> None:
    """按时间顺序插入图片解析结果

    将图片解析结果按时间戳排序后，插入到 contexts 中的正确位置。
    优先通过 L1 上下文 system 消息定位，回退到 _l1_context_count。

    Args:
        req: LLM 提供者请求对象
        image_results: 图片解析结果列表，每项包含 timestamp 和 content
    """
    if not image_results:
        return

    if req.contexts is None:
        req.contexts = []

    image_results.sort(key=lambda x: x["timestamp"])

    l1_idx = _find_l1_context_system_message(req.contexts)
    if l1_idx is not None:
        insert_pos = l1_idx + 1
    else:
        insert_pos = getattr(req, "_l1_context_count", 0)

    for img in image_results:
        req.contexts.insert(
            insert_pos, {"role": "user", "content": f"[图片] {img['content']}"}
        )
        insert_pos += 1


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

    if req.prompt:
        log_parts.append(f"\n[System Prompt]\n{'-' * 40}\n{req.prompt}\n{'-' * 40}")
    else:
        log_parts.append("\n[System Prompt]\n(无)")

    if req.contexts:
        log_parts.append(
            f"\n[Contexts] (共 {len(req.contexts)} 条) - 群聊当前对话，你需要在这之后发言"
        )
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
