"""
Iris Chat Memory - L1 消息缓冲组件

提供消息队列管理、自动总结触发等功能。
支持群聊隔离和人格切换时清空所有队列。
"""

from __future__ import annotations

from typing import Optional, Dict, Any, List, TYPE_CHECKING
from datetime import datetime
from collections import deque
import asyncio
import itertools
from typing import cast

from iris_memory.core import Component, get_logger
from iris_memory.config import get_config
from iris_memory.utils import count_tokens
from .models import ContextMessage, MessageQueue
from .summarizer import Summarizer

if TYPE_CHECKING:
    from iris_memory.core.components import ComponentManager
    from iris_memory.profile import GroupProfileManager, UserProfileManager
    from iris_memory.profile.storage import ProfileStorage
    from iris_memory.profile.models import UserProfile

logger = get_logger("buffer")


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _as_str_list(value: object) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


def _as_str_dict(value: object) -> dict[str, str] | None:
    if isinstance(value, dict):
        return value  # type: ignore[return-value]
    return None


# ============================================================================
# L1 缓冲组件
# ============================================================================


class L1Buffer(Component):
    """L1 消息缓冲组件

    管理消息队列，支持：
    - 按群聊隔离存储消息
    - 自动总结触发（阶段 5 后可用）
    - 清空单个队列或所有队列

    Attributes:
        _queues: 消息队列字典 {group_id: MessageQueue}
        _summarizer: 总结器实例（延迟初始化）
        _component_manager: 组件管理器引用（用于获取 LLMManager）
        _provider: 总结使用的 Provider ID

    Examples:
        >>> buffer = L1Buffer()
        >>> await buffer.initialize()
        >>> msg = ContextMessage(
        ...     role="user",
        ...     content="你好",
        ...     timestamp=datetime.now(),
        ...     token_count=2,
        ...     source="group_123"
        ... )
        >>> await buffer.add_message("group_123", msg)
        >>> context = buffer.get_context("group_123", 10)
        >>> len(context)
        1
    """

    def __init__(self):
        """初始化 L1 缓冲组件"""
        super().__init__()
        self._queues: Dict[str, MessageQueue] = {}
        self._image_queues: Dict[str, List[Any]] = {}
        self._summarizer: Optional[Summarizer] = None
        self._component_manager: Optional["ComponentManager"] = None
        self._provider: str = ""
        self._summarizing_locks: Dict[str, asyncio.Lock] = {}
        logger.debug("L1Buffer 实例已创建")

    @property
    def name(self) -> str:
        """组件名称

        Returns:
            组件名称 "l1_buffer"
        """
        return "l1_buffer"

    async def initialize(self) -> None:
        """初始化组件

        加载配置，总结器延迟创建（需要 LLMManager）。

        Raises:
            Exception: 初始化失败时抛出
        """
        try:
            config = get_config()

            # 检查是否启用
            if not config.get("l1_buffer.enable"):
                logger.info("L1 缓冲已禁用")
                self._is_available = False
                self._init_error = "L1 缓冲已禁用"
                return

            # 保存 Provider 配置，稍后创建总结器
            self._provider = str(config.get("l1_buffer.summary_provider", ""))

            self._is_available = True
            logger.info("L1 缓冲组件初始化成功")

        except Exception as e:
            self._is_available = False
            self._init_error = str(e)
            logger.error(f"L1 缓冲组件初始化失败：{e}", exc_info=True)
            raise

    def set_component_manager(self, manager: "ComponentManager") -> None:
        """设置组件管理器引用

        用于延迟获取 LLMManager。

        Args:
            manager: 组件管理器实例
        """
        self._component_manager = manager
        logger.debug("L1Buffer 已获取 ComponentManager 引用")

    async def shutdown(self) -> None:
        """关闭组件

        清空所有队列，释放资源。
        """
        self.clear_all()
        self._summarizing_locks.clear()
        self._reset_state()
        logger.info("L1 缓冲组件已关闭")

    def _get_or_create_summarizer(self) -> Optional[Summarizer]:
        """获取或创建 Summarizer（延迟初始化）

        Returns:
            Summarizer 实例，无法获取 LLMManager 时返回 None
        """
        # 如果已创建，直接返回
        if self._summarizer is not None:
            return self._summarizer

        # 检查 ComponentManager 是否可用
        if not self._component_manager:
            logger.warning("ComponentManager 未设置，无法创建 Summarizer")
            return None

        # 获取 LLMManager
        from iris_memory.llm import LLMManager

        llm_manager = self._component_manager.get_component("llm_manager")

        if not llm_manager or not llm_manager.is_available:
            logger.warning("LLMManager 不可用，无法创建 Summarizer")
            return None

        assert isinstance(llm_manager, LLMManager)

        # 创建 Summarizer
        self._summarizer = Summarizer(llm_manager=llm_manager, provider=self._provider)
        logger.info("Summarizer 已延迟创建")

        return self._summarizer

    def _get_queue_key(self, group_id: str) -> str:
        """获取队列键

        L1 缓冲始终按群隔离存储，不受 enable_group_memory_isolation 配置影响。
        该配置仅控制 L2/L3 的查询是否带群 ID 条件。

        Args:
            group_id: 群聊ID

        Returns:
            队列键（始终为 group_id）
        """
        return group_id

    def _get_or_create_queue(self, group_id: str) -> MessageQueue:
        """获取或创建队列

        如果队列不存在则创建。

        Args:
            group_id: 群聊ID

        Returns:
            消息队列实例
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._queues:
            self._queues[queue_key] = MessageQueue(group_id=queue_key)
            logger.debug(f"创建新队列：{queue_key}")

        return self._queues[queue_key]

    async def add_message(
        self,
        group_id: str,
        role: str,
        content: str,
        source: str,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """添加消息到队列

        计算消息 Token 数，检查是否超限，添加到队列。
        触发自动总结检查。

        Args:
            group_id: 群聊ID
            role: 消息角色（user/assistant/system）
            content: 消息内容
            source: 消息来源（用户ID等）
            metadata: 额外元数据

        Returns:
            是否成功添加（超限消息返回 False）

        Raises:
            ValueError: role 不是合法值时
        """
        if not self._is_available:
            logger.warning("L1 缓冲不可用，跳过消息添加")
            return False

        valid_roles = ("user", "assistant", "system")
        if role not in valid_roles:
            raise ValueError(f"无效的消息角色：{role!r}，合法值为 {valid_roles}")

        config = get_config()

        # 计算消息 Token 数
        token_count = count_tokens(content)

        # 检查单条消息 Token 数限制
        max_single_tokens = cast(
            int, config.get("l1_buffer.max_single_message_tokens", 2000)
        )
        if token_count > max_single_tokens:
            logger.warning(
                f"消息 Token 数 {token_count} 超过限制 {max_single_tokens}，已丢弃"
            )
            return False

        # 创建消息实例
        message = ContextMessage(
            role=role,
            content=content,
            timestamp=datetime.now(),
            token_count=token_count,
            source=source,
            metadata=metadata or {},
        )

        # 获取或创建队列
        queue = self._get_or_create_queue(group_id)
        queue.add_message(message)

        logger.debug(
            "消息已入队：%r, role=%r, tokens=%d, queue_size=%d",
            group_id,
            role,
            token_count,
            len(queue),
        )

        # 检查是否触发总结
        await self._check_and_summarize(group_id)

        return True

    def get_context(
        self, group_id: str, max_length: Optional[int] = None
    ) -> list[ContextMessage]:
        """获取队列上下文

        返回指定群聊的消息列表，用于注入 LLM 请求。

        Args:
            group_id: 群聊ID
            max_length: 最大消息数（可选，默认使用配置）

        Returns:
            消息列表
        """
        if not self._is_available:
            logger.warning("L1 缓冲不可用，返回空上下文")
            return []

        config = get_config()
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._queues:
            return []

        queue = self._queues[queue_key]

        # 使用配置的最大长度
        if max_length is None:
            max_length = cast(int, config.get("l1_buffer.inject_queue_length", 30))

        # 返回最近的消息
        q_len = len(queue.messages)
        if q_len > max_length:
            start = q_len - max_length
            messages = list(itertools.islice(queue.messages, start, q_len))
        else:
            messages = list(queue.messages)

        logger.debug(
            f"获取上下文：{group_id}, 返回 {len(messages)}/{len(queue)} 条消息"
        )

        return messages

    def clear_context(self, group_id: str) -> None:
        """清空指定群聊的队列

        Args:
            group_id: 群聊ID
        """
        self.clear_by_group(group_id)

    def clear_all(self) -> int:
        """清空所有队列

        用于人格切换时清空所有记忆。

        Returns:
            删除的消息总数
        """
        total_messages = sum(len(q) for q in self._queues.values())
        self._queues.clear()
        self._image_queues.clear()
        self._summarizing_locks.clear()
        logger.info(f"已清空所有队列，共 {total_messages} 条消息")
        return total_messages

    def clear_by_user(self, user_id: str, group_id: Optional[str] = None) -> int:
        """清空指定用户的消息

        从队列中删除指定用户发送的消息。

        Args:
            user_id: 用户ID
            group_id: 群聊ID（可选，不指定则删除所有群聊中该用户的消息）

        Returns:
            删除的消息数量
        """
        total_removed = 0

        if group_id:
            queue_key = self._get_queue_key(group_id)
            if queue_key in self._queues:
                queue = self._queues[queue_key]
                removed = self._remove_user_messages(queue, user_id)
                total_removed += removed
                logger.info(
                    f"已从队列 {queue_key} 删除用户 {user_id} 的 {removed} 条消息"
                )
        else:
            for queue_key, queue in self._queues.items():
                removed = self._remove_user_messages(queue, user_id)
                total_removed += removed
                if removed > 0:
                    logger.info(
                        f"已从队列 {queue_key} 删除用户 {user_id} 的 {removed} 条消息"
                    )

        return total_removed

    def clear_by_group(self, group_id: str) -> int:
        """清空指定群聊的队列

        Args:
            group_id: 群聊ID

        Returns:
            删除的消息数量
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key in self._queues:
            queue = self._queues[queue_key]
            old_size = len(queue)
            queue.clear()
            logger.info(f"已清空队列：{queue_key}，原 {old_size} 条消息")
            self.clear_images_for_queue(group_id)
            self._summarizing_locks.pop(queue_key, None)
            return old_size

        return 0

    def _remove_user_messages(self, queue: MessageQueue, user_id: str) -> int:
        """从队列中删除指定用户的消息

        Args:
            queue: 消息队列
            user_id: 用户ID

        Returns:
            删除的消息数量
        """
        new_messages = deque()
        removed_count = 0
        removed_tokens = 0

        for msg in queue.messages:
            if msg.source == user_id:
                removed_count += 1
                removed_tokens += msg.token_count
            else:
                new_messages.append(msg)

        queue.messages = new_messages
        queue.total_tokens -= removed_tokens

        return removed_count

    async def _check_and_summarize(self, group_id: str) -> None:
        """检查并触发总结

        检查队列是否超过限制，触发自动总结。
        使用锁防止并发触发重复总结。

        阶段 2-4：总结功能不可用，仅清空队列
        阶段 5：调用 LLM 生成总结并写入 L2

        Args:
            group_id: 群聊ID
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._summarizing_locks:
            self._summarizing_locks[queue_key] = asyncio.Lock()

        if self._summarizing_locks[queue_key].locked():
            logger.debug(f"群聊 {queue_key} 正在总结中，跳过重复触发")
            return

        async with self._summarizing_locks[queue_key]:
            summarizer = self._get_or_create_summarizer()

            if not summarizer:
                logger.debug("Summarizer 不可用，跳过总结检查")
                return

            if queue_key not in self._queues:
                return

            queue = self._queues[queue_key]

            if not summarizer.should_summarize(queue):
                return

            try:
                config = get_config()
                retain_count = cast(
                    int, config.get("l1_buffer.retain_message_count", 10)
                )
                max_queue_tokens = cast(
                    int, config.get("l1_buffer.max_queue_tokens", 4000)
                )

                to_summarize, to_retain = queue.split_for_summary(
                    retain_count=retain_count, max_retain_tokens=max_queue_tokens
                )

                if not to_summarize:
                    logger.debug(f"队列 {queue_key} 无需总结的消息")
                    return

                logger.info(
                    f"开始总结队列：{queue_key}，"
                    f"待总结 {len(to_summarize)} 条，保留 {len(to_retain)} 条"
                )

                summary = await summarizer.summarize(to_summarize)

                if summary:
                    logger.info(f"总结完成：{queue_key}, 长度：{len(summary)}")

                    await self._write_summary_to_l2(group_id, to_summarize, summary)

                    await self._update_profile_after_summary(
                        group_id, to_summarize, summary
                    )
                else:
                    logger.warning(f"总结返回空，队列 {queue_key}")

                queue.remove_messages(to_summarize)

                self._clear_images_for_summarized_messages(queue_key, to_summarize)

                logger.info(
                    f"队列已更新：{queue_key}，剩余 {len(queue)} 条消息，"
                    f"{queue.total_tokens} tokens"
                )

            except Exception as e:
                logger.error(f"总结队列 {queue_key} 失败：{e}", exc_info=True)

    async def _update_profile_after_summary(
        self, group_id: str, messages: list[ContextMessage], summary: str
    ) -> None:
        """总结后更新画像（三层更新策略）

        短期字段：每次总结后规则更新（无LLM）
        中期字段：按频率触发LLM分析
        长期字段：按时间间隔触发LLM深度分析

        Args:
            group_id: 群聊ID
            messages: 被总结的消息列表
            summary: 总结文本
        """
        config = get_config()
        if not config.get("profile.enable"):
            return

        if not self._component_manager:
            return

        profile_storage = self._component_manager.get_component("profile")
        if not profile_storage or not profile_storage.is_available:
            return

        try:
            from iris_memory.profile import GroupProfileManager, UserProfileManager
            from iris_memory.profile.storage import ProfileStorage

            assert isinstance(profile_storage, ProfileStorage)

            group_manager = GroupProfileManager(profile_storage)
            user_manager = UserProfileManager(profile_storage)

            user_messages_by_id: dict[str, list[str]] = {}
            for msg in messages:
                if msg.role == "user" and msg.source:
                    user_messages_by_id.setdefault(msg.source, []).append(msg.content)

            effective_group_id = (
                group_id
                if config.get("isolation_config.enable_group_isolation")
                else "default"
            )

            group_profile_obj = await group_manager.get_or_create(group_id)
            if group_manager.should_update_mid(group_profile_obj):
                await self._update_group_mid_term(
                    group_id, messages, group_manager, profile_storage
                )

            if group_manager.should_update_long(group_profile_obj):
                await self._update_group_long_term(
                    group_id, messages, group_manager, profile_storage
                )

            for user_id, user_msgs in user_messages_by_id.items():
                user_profile_obj = await user_manager.get_or_create(
                    user_id, effective_group_id
                )

                if user_manager.should_update_mid(user_profile_obj):
                    await self._update_user_mid_term(
                        user_id,
                        effective_group_id,
                        user_msgs,
                        user_manager,
                        user_profile_obj,
                        profile_storage,
                    )

                if user_manager.should_update_long(user_profile_obj):
                    await self._update_user_long_term(
                        user_id,
                        effective_group_id,
                        user_msgs,
                        user_manager,
                        user_profile_obj,
                        profile_storage,
                    )

            logger.debug(f"总结后更新画像完成: {group_id}")

        except Exception as e:
            logger.error(f"更新画像失败: {e}", exc_info=True)

    async def _update_group_mid_term(
        self,
        group_id: str,
        messages: list[ContextMessage],
        group_manager: GroupProfileManager,
        profile_storage: ProfileStorage,
    ) -> None:
        """群聊画像中期更新（LLM分析）

        Args:
            group_id: 群聊ID
            messages: 消息列表
            group_manager: 群聊画像管理器
            profile_storage: 画像存储
        """
        assert self._component_manager is not None
        llm_manager = self._component_manager.get_component("llm_manager")
        if not llm_manager or not llm_manager.is_available:
            return

        try:
            from iris_memory.llm import LLMManager
            from iris_memory.profile import ProfileAnalyzer
            from iris_memory.profile.models import UpdateTier

            assert isinstance(llm_manager, LLMManager)
            analyzer = ProfileAnalyzer(llm_manager)
            group_profile_obj = await group_manager.get_or_create(group_id)
            from iris_memory.profile.models import profile_to_dict

            current_profile_dict = profile_to_dict(group_profile_obj)

            msg_texts = [msg.content for msg in messages if msg.content]
            result = await analyzer.analyze_group_profile(
                msg_texts, current_profile_dict, tier=UpdateTier.MID
            )

            if result:
                await group_manager.update_from_analysis(
                    group_id=group_id,
                    interests=_as_str_list(result.get("interests")),
                    atmosphere_tags=_as_str_list(result.get("atmosphere_tags")),
                    custom_fields=_as_str_dict(result.get("custom_fields")),
                    tier=UpdateTier.MID,
                    confidence=0.7,
                )
                logger.info(f"群聊画像中期更新完成: {group_id}")

        except Exception as e:
            logger.error(f"群聊画像中期更新失败: {e}", exc_info=True)

    async def _update_group_long_term(
        self,
        group_id: str,
        messages: list[ContextMessage],
        group_manager: GroupProfileManager,
        profile_storage: ProfileStorage,
    ) -> None:
        """群聊画像长期更新（LLM深度分析）

        Args:
            group_id: 群聊ID
            messages: 消息列表
            group_manager: 群聊画像管理器
            profile_storage: 画像存储
        """
        assert self._component_manager is not None
        llm_manager = self._component_manager.get_component("llm_manager")
        if not llm_manager or not llm_manager.is_available:
            return

        try:
            from iris_memory.llm import LLMManager
            from iris_memory.profile import ProfileAnalyzer
            from iris_memory.profile.models import UpdateTier

            assert isinstance(llm_manager, LLMManager)
            analyzer = ProfileAnalyzer(llm_manager)
            group_profile_obj = await group_manager.get_or_create(group_id)
            from iris_memory.profile.models import profile_to_dict

            current_profile_dict = profile_to_dict(group_profile_obj)

            msg_texts = [msg.content for msg in messages if msg.content]
            result = await analyzer.analyze_group_profile(
                msg_texts, current_profile_dict, tier=UpdateTier.LONG
            )

            if result:
                await group_manager.update_long_term_from_analysis(
                    group_id=group_id,
                    long_term_tags=_as_str_list(result.get("long_term_tags")),
                    blacklist_topics=_as_str_list(result.get("blacklist_topics")),
                    interests=_as_str_list(result.get("interests")),
                    atmosphere_tags=_as_str_list(result.get("atmosphere_tags")),
                    custom_fields=_as_str_dict(result.get("custom_fields")),
                    confidence=0.8,
                )
                logger.info(f"群聊画像长期更新完成: {group_id}")

        except Exception as e:
            logger.error(f"群聊画像长期更新失败: {e}", exc_info=True)

    async def _update_user_mid_term(
        self,
        user_id: str,
        group_id: str,
        user_messages: list[str],
        user_manager: UserProfileManager,
        user_profile_obj: UserProfile,
        profile_storage: ProfileStorage,
    ) -> None:
        """用户画像中期更新（LLM分析）

        Args:
            user_id: 用户ID
            group_id: 群聊ID
            user_messages: 用户消息列表
            user_manager: 用户画像管理器
            user_profile_obj: 用户画像对象
            profile_storage: 画像存储
        """
        assert self._component_manager is not None
        llm_manager = self._component_manager.get_component("llm_manager")
        if not llm_manager or not llm_manager.is_available:
            return

        try:
            from iris_memory.llm import LLMManager
            from iris_memory.profile import ProfileAnalyzer
            from iris_memory.profile.models import UpdateTier, profile_to_dict

            assert isinstance(llm_manager, LLMManager)
            analyzer = ProfileAnalyzer(llm_manager)
            current_profile_dict = profile_to_dict(user_profile_obj)

            result = await analyzer.analyze_user_profile(
                user_messages, current_profile_dict, tier=UpdateTier.MID
            )

            if result:
                await user_manager.update_from_analysis(
                    user_id=user_id,
                    group_id=group_id,
                    personality_tags=_as_str_list(result.get("personality_tags")),
                    interests=_as_str_list(result.get("interests")),
                    occupation=_as_str(result.get("occupation")),
                    language_style=_as_str(result.get("language_style")),
                    custom_fields=_as_str_dict(result.get("custom_fields")),
                    tier=UpdateTier.MID,
                    confidence=0.7,
                )
                logger.info(f"用户画像中期更新完成: {user_id}")

        except Exception as e:
            logger.error(f"用户画像中期更新失败: {e}", exc_info=True)

    async def _update_user_long_term(
        self,
        user_id: str,
        group_id: str,
        user_messages: list[str],
        user_manager: UserProfileManager,
        user_profile_obj: UserProfile,
        profile_storage: ProfileStorage,
    ) -> None:
        """用户画像长期更新（LLM深度分析）

        Args:
            user_id: 用户ID
            group_id: 群聊ID
            user_messages: 用户消息列表
            user_manager: 用户画像管理器
            user_profile_obj: 用户画像对象
            profile_storage: 画像存储
        """
        assert self._component_manager is not None
        llm_manager = self._component_manager.get_component("llm_manager")
        if not llm_manager or not llm_manager.is_available:
            return

        try:
            from iris_memory.llm import LLMManager
            from iris_memory.profile import ProfileAnalyzer
            from iris_memory.profile.models import UpdateTier, profile_to_dict

            assert isinstance(llm_manager, LLMManager)
            analyzer = ProfileAnalyzer(llm_manager)
            current_profile_dict = profile_to_dict(user_profile_obj)

            result = await analyzer.analyze_user_profile(
                user_messages, current_profile_dict, tier=UpdateTier.LONG
            )

            if result:
                await user_manager.update_long_term_from_analysis(
                    user_id=user_id,
                    group_id=group_id,
                    occupation=_as_str(result.get("occupation")),
                    bot_relationship=_as_str(result.get("bot_relationship")),
                    important_events=_as_str_list(result.get("important_events")),
                    taboo_topics=_as_str_list(result.get("taboo_topics")),
                    important_dates=result.get("important_dates"),  # type: ignore[arg-type]
                    personality_tags=_as_str_list(result.get("personality_tags")),
                    interests=_as_str_list(result.get("interests")),
                    custom_fields=_as_str_dict(result.get("custom_fields")),
                    confidence=0.8,
                )
                logger.info(f"用户画像长期更新完成: {user_id}")

        except Exception as e:
            logger.error(f"用户画像长期更新失败: {e}", exc_info=True)

    async def _write_summary_to_l2(
        self, group_id: str, messages: list[ContextMessage], summary: str
    ) -> Optional[str]:
        """将总结写入 L2 记忆库

        解析分条总结，每条独立存储到 L2 记忆库。
        从总结内容中提取用户名，绑定到具体的发送用户。

        Args:
            group_id: 群聊ID
            messages: 被总结的消息列表
            summary: 总结文本（JSON 格式或分条格式）

        Returns:
            第一条记忆 ID，失败时返回 None
        """
        config = get_config()
        if not config.get("l2_memory.enable"):
            logger.debug("L2 记忆库未启用，跳过写入")
            return None

        if not self._component_manager:
            return None

        l2_adapter = self._component_manager.get_component("l2_memory")
        if not l2_adapter or not l2_adapter.is_available:
            logger.debug("L2 记忆库组件不可用，跳过写入")
            return None

        try:
            from iris_memory.l2_memory import MemoryRetriever
            from .summarizer import parse_summary_response

            retriever = MemoryRetriever(self._component_manager)

            name_to_id = self._build_name_to_id_map(messages)
            active_users = list(
                set(msg.source for msg in messages if msg.role == "user" and msg.source)
            )

            parsed = parse_summary_response(summary)
            summary_items = parsed.get("memories", [])

            if not summary_items:
                summary_items = self._parse_summary_items(summary)

            if not summary_items:
                logger.warning(f"总结解析后无有效条目，原内容：{summary[:100]}...")
                return None

            memory_ids = []
            for item in summary_items:
                if item.startswith("- "):
                    item = item[2:]

                user_id = self._extract_user_from_item(item, name_to_id)

                metadata = {
                    "group_id": group_id,
                    "source": "l1_summary",
                    "timestamp": datetime.now().isoformat(),
                    "confidence": 0.8,
                    "kg_processed": False,
                }

                if user_id:
                    metadata["user_id"] = user_id

                if active_users:
                    metadata["active_users"] = ",".join(active_users)

                memory_id = await retriever.add_from_summary(item, metadata)
                if memory_id:
                    memory_ids.append(memory_id)

            if memory_ids:
                logger.info(f"已将 {len(memory_ids)} 条记忆写入 L2 记忆库")
                return memory_ids[0]
            else:
                logger.warning("写入 L2 记忆库失败")
                return None

        except Exception as e:
            logger.error(f"写入 L2 记忆库失败: {e}", exc_info=True)
            return None

    def _build_name_to_id_map(self, messages: list[ContextMessage]) -> dict[str, str]:
        """构建用户名到用户ID的映射

        Args:
            messages: 消息列表

        Returns:
            {user_name: user_id}
        """
        name_to_id: dict[str, str] = {}
        for msg in messages:
            if msg.role == "user" and msg.source and msg.metadata:
                user_name = msg.metadata.get("user_name")
                if user_name and user_name not in name_to_id:
                    name_to_id[user_name] = msg.source
        return name_to_id

    def _extract_user_from_item(
        self, item: str, name_to_id: dict[str, str]
    ) -> Optional[str]:
        """从总结条目中提取用户ID

        总结格式如："张三提到喜欢吃苹果"
        通过匹配用户名来识别用户。按名字长度降序匹配，避免短名误匹配。

        Args:
            item: 记忆条目内容
            name_to_id: 用户名到用户ID的映射

        Returns:
            用户ID，无法识别时返回 None
        """
        if not name_to_id:
            return None

        for user_name, user_id in sorted(
            name_to_id.items(), key=lambda x: len(x[0]), reverse=True
        ):
            if user_name in item:
                return user_id

        return None

    def _parse_summary_items(self, summary: str, min_length: int = 5) -> list[str]:
        """解析分条总结

        支持多种格式：
        - "- 条目内容"
        - "1. 条目内容"
        - "• 条目内容"
        - 换行分隔

        Args:
            summary: 总结文本
            min_length: 最小条目长度，低于此长度则忽略

        Returns:
            解析后的条目列表
        """
        items = []
        lines = summary.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line in ("无", "无有效信息", "无有效记忆", "无有价值的信息"):
                continue

            if line.startswith("- "):
                line = line[2:]
            elif line.startswith("• "):
                line = line[2:]
            elif len(line) > 2 and line[0].isdigit() and line[1] in ".、)":
                line = line[2:].strip()

            line = line.strip()
            if len(line) >= min_length:
                items.append(line)

        return items

    def get_queue_stats(self, group_id: str) -> Optional[Dict]:
        """获取队列统计信息

        Args:
            group_id: 群聊ID

        Returns:
            统计信息字典，队列不存在时返回 None
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._queues:
            return None

        queue = self._queues[queue_key]

        return {
            "group_id": queue_key,
            "message_count": len(queue),
            "total_tokens": queue.total_tokens,
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取 L1 缓冲的全局统计信息

        Returns:
            统计信息字典
        """
        config = get_config()

        # 计算总消息数和总 Token 数
        total_messages = 0
        total_tokens = 0
        queue_count = len(self._queues)

        max_queue_length = 0
        for queue in self._queues.values():
            total_messages += len(queue)
            total_tokens += queue.total_tokens
            if len(queue) > max_queue_length:
                max_queue_length = len(queue)

        return {
            "queue_count": queue_count,
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "max_capacity": config.get("l1_buffer.max_capacity", 100),
            "max_queue_length": max_queue_length,
        }

    def get_all_queues_stats(self) -> List[Dict[str, Any]]:
        """获取所有群聊队列的统计信息

        Returns:
            队列统计列表 [{"group_id": str, "message_count": int, "total_tokens": int}]
        """
        queues_stats = []
        for group_id, queue in self._queues.items():
            queues_stats.append(
                {
                    "group_id": group_id,
                    "message_count": len(queue),
                    "total_tokens": queue.total_tokens,
                }
            )
        return queues_stats

    # ========================================================================
    # 图片队列管理
    # ========================================================================

    def append_to_last_message(self, group_id: str, suffix: str) -> bool:
        """追加文本到队列中最后一条消息

        用于在消息入队后追加图片占位符或描述。

        Args:
            group_id: 群聊ID
            suffix: 要追加的文本

        Returns:
            是否成功追加
        """
        if not self._is_available:
            return False

        queue_key = self._get_queue_key(group_id)
        if queue_key not in self._queues:
            return False

        queue = self._queues[queue_key]
        if not queue.messages:
            return False

        last_msg = queue.messages[-1]
        old_tokens = last_msg.token_count
        last_msg.content += suffix
        last_msg.token_count = count_tokens(last_msg.content)

        token_diff = last_msg.token_count - old_tokens
        queue.total_tokens += token_diff

        logger.debug(
            f"已追加文本到最后消息：{queue_key}, 追加长度={len(suffix)}, "
            f"token差={token_diff}"
        )
        return True

    def prepend_to_last_message(
        self, group_id: str, prefix: str, same_source: str = ""
    ) -> bool:
        """前置文本到队列中最后一条消息

        用于将图片描述放在消息内容最前面，保持发送者意图。

        Args:
            group_id: 群聊ID
            prefix: 要前置的文本
            same_source: 若非空，仅当最后一条消息的 source 匹配时才前置

        Returns:
            是否成功前置
        """
        if not self._is_available:
            return False

        queue_key = self._get_queue_key(group_id)
        if queue_key not in self._queues:
            return False

        queue = self._queues[queue_key]
        if not queue.messages:
            return False

        last_msg = queue.messages[-1]

        if same_source and last_msg.source != same_source:
            return False

        old_tokens = last_msg.token_count
        last_msg.content = prefix + last_msg.content
        last_msg.token_count = count_tokens(last_msg.content)

        token_diff = last_msg.token_count - old_tokens
        queue.total_tokens += token_diff

        logger.debug(
            f"已前置文本到最后消息：{queue_key}, 前置长度={len(prefix)}, "
            f"token差={token_diff}"
        )
        return True

    def replace_image_placeholder(
        self, group_id: str, placeholder: str, description: str
    ) -> bool:
        """替换消息中的图片占位符

        在队列中查找包含占位符的消息，将占位符替换为图片描述，
        并更新 token 计数。

        Args:
            group_id: 群聊ID
            placeholder: 占位符文本（如 [IMG:abc12345]）
            description: 替换文本（如 [图:一只猫的照片]）

        Returns:
            是否成功替换
        """
        if not self._is_available:
            return False

        queue_key = self._get_queue_key(group_id)
        if queue_key not in self._queues:
            return False

        queue = self._queues[queue_key]
        replaced = False

        for msg in queue.messages:
            if placeholder in msg.content:
                old_tokens = msg.token_count
                msg.content = msg.content.replace(placeholder, description)
                msg.token_count = count_tokens(msg.content)

                token_diff = msg.token_count - old_tokens
                queue.total_tokens += token_diff

                replaced = True
                logger.debug(
                    f"已替换图片占位符：{queue_key}, "
                    f"{placeholder} -> {description[:30]}..."
                )

        return replaced

    def add_image(self, group_id: str, image_item: Any) -> None:
        """添加图片到图片队列

        Args:
            group_id: 群聊ID
            image_item: 图片队列项（ImageQueueItem）
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._image_queues:
            self._image_queues[queue_key] = []

        self._image_queues[queue_key].append(image_item)
        logger.debug(
            f"图片已入队：{queue_key}, hash={image_item.image_hash[:8]}..., "
            f"队列大小={len(self._image_queues[queue_key])}"
        )

    def get_images(
        self, group_id: str, limit: Optional[int] = None, only_pending: bool = True
    ) -> List[Any]:
        """获取图片队列中的图片

        Args:
            group_id: 群聊ID
            limit: 最大返回数量（None 表示不限制）
            only_pending: 是否只返回待解析的图片

        Returns:
            图片队列项列表
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._image_queues:
            return []

        images = self._image_queues[queue_key]

        if only_pending:
            from iris_memory.image import ImageParseStatus

            images = [img for img in images if img.status == ImageParseStatus.PENDING]

        if limit is not None:
            images = images[:limit]

        return images

    def mark_image_parsed(self, group_id: str, image_hash: str, status: Any) -> bool:
        """标记图片解析状态

        Args:
            group_id: 群聊ID
            image_hash: 图片 hash
            status: 解析状态（ImageParseStatus）

        Returns:
            是否成功标记
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._image_queues:
            return False

        for img in self._image_queues[queue_key]:
            if img.image_hash == image_hash:
                img.status = status
                logger.debug(
                    f"图片状态已更新：{queue_key}, hash={image_hash[:8]}..., "
                    f"status={status.value}"
                )
                return True

        return False

    def clear_images_for_message(self, group_id: str, message_id: str) -> int:
        """清理指定消息的图片

        Args:
            group_id: 群聊ID
            message_id: 消息ID

        Returns:
            清理的图片数量
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._image_queues:
            return 0

        original_count = len(self._image_queues[queue_key])
        self._image_queues[queue_key] = [
            img for img in self._image_queues[queue_key] if img.message_id != message_id
        ]

        removed_count = original_count - len(self._image_queues[queue_key])
        if removed_count > 0:
            logger.debug(f"已清理消息 {message_id} 的 {removed_count} 张图片")

        return removed_count

    def clear_images_for_queue(self, group_id: str) -> int:
        """清理指定群聊的所有图片

        Args:
            group_id: 群聊ID

        Returns:
            清理的图片数量
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._image_queues:
            return 0

        removed_count = len(self._image_queues[queue_key])
        del self._image_queues[queue_key]

        if removed_count > 0:
            logger.debug(f"已清理队列 {queue_key} 的 {removed_count} 张图片")

        return removed_count

    def get_image_stats(self, group_id: str) -> Optional[Dict[str, Any]]:
        """获取图片队列统计信息

        Args:
            group_id: 群聊ID

        Returns:
            统计信息字典
        """
        queue_key = self._get_queue_key(group_id)

        if queue_key not in self._image_queues:
            return None

        from iris_memory.image import ImageParseStatus

        images = self._image_queues[queue_key]
        pending_count = sum(
            1 for img in images if img.status == ImageParseStatus.PENDING
        )
        success_count = sum(
            1 for img in images if img.status == ImageParseStatus.SUCCESS
        )
        failed_count = sum(1 for img in images if img.status == ImageParseStatus.FAILED)

        return {
            "group_id": queue_key,
            "total_count": len(images),
            "pending_count": pending_count,
            "success_count": success_count,
            "failed_count": failed_count,
        }

    def _clear_images_for_summarized_messages(
        self, queue_key: str, messages: list[ContextMessage]
    ) -> int:
        """清理被总结消息对应的图片

        Args:
            queue_key: 队列键
            messages: 被总结的消息列表

        Returns:
            清理的图片数量
        """
        if queue_key not in self._image_queues:
            return 0

        message_ids = set()
        for msg in messages:
            msg_id = msg.metadata.get("message_id")
            if msg_id:
                message_ids.add(msg_id)

        if not message_ids:
            return 0

        original_count = len(self._image_queues[queue_key])
        self._image_queues[queue_key] = [
            img
            for img in self._image_queues[queue_key]
            if img.message_id not in message_ids
        ]

        removed_count = original_count - len(self._image_queues[queue_key])
        if removed_count > 0:
            logger.debug(f"已清理被总结消息的 {removed_count} 张图片")

        return removed_count
