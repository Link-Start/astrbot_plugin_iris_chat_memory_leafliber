"""
Iris Chat Memory - L1 数据模型

定义 L1 消息上下文缓冲的数据结构。
三段式 FIFO 队列：L1-1（最新）、L1-2（主体）、L1-3（缓冲）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Dict, Any
from collections import deque


@dataclass
class ContextMessage:
    """消息数据类

    存储单条消息的完整信息，包括角色、内容、时间戳、Token 数等。

    Attributes:
        role: 消息角色（user/assistant/system）
        content: 消息内容
        timestamp: 消息时间戳
        token_count: Token 数量
        source: 消息来源（群聊ID或用户ID）
        metadata: 额外元数据（如用户昵称、消息ID等）
    """

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime
    token_count: int
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        Returns:
            包含所有字段的字典
        """
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "token_count": self.token_count,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextMessage":
        """从字典创建实例

        Args:
            data: 包含消息数据的字典

        Returns:
            ContextMessage 实例

        Raises:
            ValueError: 缺少必要字段时
        """
        required_fields = ("role", "content", "timestamp", "token_count", "source")
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(f"ContextMessage.from_dict 缺少必要字段：{missing}")

        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=timestamp,
            token_count=data["token_count"],
            source=data["source"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class SegmentedMessageQueue:
    """三段式 FIFO 消息队列

    队列分为三段：
    - L1-1（segment_1）：最新段，接收新消息，注入上下文，总结时辅助理解
    - L1-2（segment_2）：主体段，注入上下文，总结时的目标段
    - L1-3（segment_3）：缓冲段，不注入上下文，总结时辅助理解

    数据流：新消息 → L1-1 → 溢出到 L1-2 → 溢出到 L1-3 → 触发总结

    总结后段位转移：
    - 旧 L1-3 → 删除
    - 旧 L1-2 → 内容删除（已总结到L2），槽位成为新 L1-3
    - 旧 L1-1 → 成为新 L1-2
    - 新 L1-1 → 空，接收新消息

    Note:
        本类非线程安全。在 asyncio 单线程事件循环中，同步方法在同一个
        await 点之间不会被中断，因此是安全的。但如果跨 await 点操作同一
        队列（如总结过程中），需由调用方加锁保护。

    Attributes:
        group_id: 群聊ID
        segment_1: L1-1 最新段
        segment_2: L1-2 主体段
        segment_3: L1-3 缓冲段
        total_tokens: 队列总 Token 数
        segment_1_length: L1-1 段最大长度
        segment_3_length: L1-3 段最大长度
        total_length: 队列总长度
    """

    group_id: str
    segment_1: deque[ContextMessage] = field(default_factory=deque)
    segment_2: deque[ContextMessage] = field(default_factory=deque)
    segment_3: deque[ContextMessage] = field(default_factory=deque)
    total_tokens: int = 0
    segment_1_length: int = 10
    segment_3_length: int = 5
    total_length: int = 30

    @property
    def segment_2_length(self) -> int:
        """L1-2 段最大长度（由总长减去 L1-1 和 L1-3 计算得出）"""
        return max(1, self.total_length - self.segment_1_length - self.segment_3_length)

    @property
    def all_messages(self) -> list[ContextMessage]:
        """按时间顺序返回全量消息（L1-3 + L1-2 + L1-1，旧→新）"""
        return list(self.segment_3) + list(self.segment_2) + list(self.segment_1)

    @property
    def inject_messages(self) -> list[ContextMessage]:
        """返回注入上下文的消息（L1-2 + L1-1，不含 L1-3）"""
        return list(self.segment_2) + list(self.segment_1)

    def add_message(self, message: ContextMessage) -> None:
        """添加消息到队列

        消息先入 L1-1，溢出时依次推入 L1-2 → L1-3。

        Args:
            message: 要添加的消息
        """
        self.segment_1.append(message)
        self.total_tokens += message.token_count
        self._overflow()

    def _overflow(self) -> None:
        """段间溢出处理：L1-1 → L1-2 → L1-3"""
        while len(self.segment_1) > self.segment_1_length:
            msg = self.segment_1.popleft()
            self.segment_2.append(msg)

        while len(self.segment_2) > self.segment_2_length:
            msg = self.segment_2.popleft()
            self.segment_3.append(msg)

    def is_full(self) -> bool:
        """检查队列是否已满（L1-3 段达到上限）"""
        return len(self.segment_3) >= self.segment_3_length

    def rotate_after_summary(self) -> None:
        """总结后段位转移

        旧 L1-3 → 删除
        旧 L1-2 → 内容删除（已总结到L2），槽位成为新 L1-3
        旧 L1-1 → 成为新 L1-2
        新 L1-1 → 空
        """
        seg3_removed_tokens = sum(m.token_count for m in self.segment_3)
        seg2_removed_tokens = sum(m.token_count for m in self.segment_2)
        self.total_tokens -= seg3_removed_tokens + seg2_removed_tokens

        self.segment_3 = self.segment_2
        self.segment_2 = self.segment_1
        self.segment_1 = deque()

    def clear(self) -> None:
        """清空所有段的消息并重置 Token 计数"""
        self.segment_1.clear()
        self.segment_2.clear()
        self.segment_3.clear()
        self.total_tokens = 0

    def __len__(self) -> int:
        """获取队列总长度"""
        return len(self.segment_1) + len(self.segment_2) + len(self.segment_3)

    def is_empty(self) -> bool:
        """检查队列是否为空"""
        return len(self) == 0

    def to_message_list(self) -> list[Dict[str, str]]:
        """转换为 OpenAI Chat API 格式的消息列表

        Returns:
            消息列表，每条消息包含 role 和 content
        """
        return [
            {"role": msg.role, "content": msg.content} for msg in self.all_messages
        ]

    def remove_messages(self, messages: list[ContextMessage]) -> None:
        """从队列中移除指定消息

        遍历三段移除匹配的消息并更新 Token 计数。

        Args:
            messages: 要移除的消息列表
        """
        message_set = set(id(m) for m in messages)
        removed_tokens = 0

        new_seg1 = deque()
        for msg in self.segment_1:
            if id(msg) in message_set:
                removed_tokens += msg.token_count
            else:
                new_seg1.append(msg)

        new_seg2 = deque()
        for msg in self.segment_2:
            if id(msg) in message_set:
                removed_tokens += msg.token_count
            else:
                new_seg2.append(msg)

        new_seg3 = deque()
        for msg in self.segment_3:
            if id(msg) in message_set:
                removed_tokens += msg.token_count
            else:
                new_seg3.append(msg)

        self.segment_1 = new_seg1
        self.segment_2 = new_seg2
        self.segment_3 = new_seg3
        self.total_tokens = max(0, self.total_tokens - removed_tokens)

    def remove_user_messages(self, user_id: str) -> int:
        """从队列中删除指定用户的消息

        Args:
            user_id: 用户ID

        Returns:
            删除的消息数量
        """
        removed_count = 0
        removed_tokens = 0

        new_seg1 = deque()
        for msg in self.segment_1:
            if msg.source == user_id:
                removed_count += 1
                removed_tokens += msg.token_count
            else:
                new_seg1.append(msg)

        new_seg2 = deque()
        for msg in self.segment_2:
            if msg.source == user_id:
                removed_count += 1
                removed_tokens += msg.token_count
            else:
                new_seg2.append(msg)

        new_seg3 = deque()
        for msg in self.segment_3:
            if msg.source == user_id:
                removed_count += 1
                removed_tokens += msg.token_count
            else:
                new_seg3.append(msg)

        self.segment_1 = new_seg1
        self.segment_2 = new_seg2
        self.segment_3 = new_seg3
        self.total_tokens -= removed_tokens

        return removed_count


MessageQueue = SegmentedMessageQueue
