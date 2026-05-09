"""总结器测试"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from iris_memory.l1_buffer import Summarizer, SegmentedMessageQueue, ContextMessage


@pytest.fixture
def mock_llm_manager():
    manager = AsyncMock()
    manager.generate = AsyncMock(return_value="这是一个总结")
    return manager


@pytest.fixture
def mock_messages():
    messages = []
    for i in range(5):
        msg = ContextMessage(
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息{i}",
            timestamp=datetime.now(),
            token_count=10,
            source="user_456",
        )
        messages.append(msg)
    return messages


@pytest.fixture
def mock_queue():
    queue = SegmentedMessageQueue(
        group_id="group_123",
        segment_1_length=2,
        segment_3_length=2,
        total_length=8,
    )
    for i in range(8):
        queue.add_message(
            ContextMessage(
                role="user" if i % 2 == 0 else "assistant",
                content=f"消息{i}",
                timestamp=datetime.now(),
                token_count=10,
                source="user_456",
            )
        )
    return queue


class TestSummarizer:
    def test_create_summarizer(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        assert summarizer.llm_manager == mock_llm_manager
        assert summarizer.provider == ""

    def test_create_summarizer_with_provider(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager, provider="gpt-4o-mini")

        assert summarizer.provider == "gpt-4o-mini"

    def test_should_summarize_when_full(self, mock_queue):
        with patch("iris_memory.l1_buffer.summarizer.get_config") as mock_get_config:
            mock_config = Mock()
            mock_config.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.max_queue_tokens": 10000,
                }.get(key)
            )
            mock_get_config.return_value = mock_config

            summarizer = Summarizer(llm_manager=Mock())

            assert summarizer.should_summarize(mock_queue)

    def test_should_summarize_by_tokens(self, mock_queue):
        with patch("iris_memory.l1_buffer.summarizer.get_config") as mock_get_config:
            mock_config = Mock()
            mock_config.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.max_queue_tokens": 40,
                }.get(key)
            )
            mock_get_config.return_value = mock_config

            summarizer = Summarizer(llm_manager=Mock())

            assert summarizer.should_summarize(mock_queue)

    def test_should_not_summarize(self):
        queue = SegmentedMessageQueue(
            group_id="g1",
            segment_1_length=5,
            segment_3_length=3,
            total_length=20,
        )
        for i in range(3):
            queue.add_message(
                ContextMessage(
                    role="user",
                    content=f"消息{i}",
                    timestamp=datetime.now(),
                    token_count=10,
                    source="user",
                )
            )

        with patch("iris_memory.l1_buffer.summarizer.get_config") as mock_get_config:
            mock_config = Mock()
            mock_config.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.max_queue_tokens": 10000,
                }.get(key)
            )
            mock_get_config.return_value = mock_config

            summarizer = Summarizer(llm_manager=Mock())

            assert not summarizer.should_summarize(queue)

    @pytest.mark.asyncio
    async def test_summarize_messages(self, mock_llm_manager, mock_messages):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        summary = await summarizer.summarize(
            context_messages=mock_messages, target_messages=mock_messages
        )

        assert summary == "这是一个总结"
        assert mock_llm_manager.generate.called

    @pytest.mark.asyncio
    async def test_summarize_empty_target(self, mock_llm_manager, mock_messages):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        summary = await summarizer.summarize(
            context_messages=mock_messages, target_messages=[]
        )

        assert summary is None

    def test_build_summary_prompt(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        context_messages = [
            ContextMessage(
                role="user",
                content="你好",
                timestamp=datetime.now(),
                token_count=2,
                source="user_001",
                metadata={"user_name": "张三"},
            ),
            ContextMessage(
                role="assistant",
                content="你好！",
                timestamp=datetime.now(),
                token_count=3,
                source="bot",
            ),
        ]

        target_messages = context_messages

        prompt = summarizer._build_summary_prompt(context_messages, target_messages)

        assert "[张三]: 你好" in prompt
        assert "[助手]: 你好！" in prompt
        assert "提取记忆信息" in prompt
        assert "memories" in prompt
        assert "完整对话上下文" in prompt
        assert "需要总结的对话片段" in prompt

    def test_build_summary_prompt_format(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        messages = [
            ContextMessage(
                role="user",
                content="我喜欢吃苹果",
                timestamp=datetime.now(),
                token_count=5,
                source="user_001",
                metadata={"user_name": "张三"},
            ),
            ContextMessage(
                role="assistant",
                content="好的，我记住了",
                timestamp=datetime.now(),
                token_count=5,
                source="bot",
            ),
        ]

        prompt = summarizer._build_summary_prompt(messages, messages)

        assert "信息价值" in prompt
        assert "独立完整" in prompt
        assert "非即时性" in prompt
        assert "JSON" in prompt

    def test_build_summary_prompt_with_user_names(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        messages = [
            ContextMessage(
                role="user",
                content="我喜欢吃苹果",
                timestamp=datetime.now(),
                token_count=5,
                source="user_001",
                metadata={"user_name": "张三"},
            ),
            ContextMessage(
                role="user",
                content="我喜欢编程",
                timestamp=datetime.now(),
                token_count=5,
                source="user_002",
                metadata={"user_name": "李四"},
            ),
        ]

        prompt = summarizer._build_summary_prompt(messages, messages)

        assert "[张三]: 我喜欢吃苹果" in prompt
        assert "[李四]: 我喜欢编程" in prompt

    def test_build_summary_prompt_without_user_name(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        messages = [
            ContextMessage(
                role="user",
                content="你好",
                timestamp=datetime.now(),
                token_count=2,
                source="user_001",
            )
        ]

        prompt = summarizer._build_summary_prompt(messages, messages)

        assert "[用户]: 你好" in prompt

    def test_build_summary_prompt_different_context_and_target(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        context_messages = [
            ContextMessage(
                role="user",
                content="旧消息",
                timestamp=datetime.now(),
                token_count=2,
                source="user_001",
            ),
            ContextMessage(
                role="user",
                content="目标消息",
                timestamp=datetime.now(),
                token_count=2,
                source="user_001",
            ),
            ContextMessage(
                role="user",
                content="新消息",
                timestamp=datetime.now(),
                token_count=2,
                source="user_001",
            ),
        ]

        target_messages = [context_messages[1]]

        prompt = summarizer._build_summary_prompt(context_messages, target_messages)

        assert "旧消息" in prompt
        assert "目标消息" in prompt
        assert "新消息" in prompt

    def test_format_messages(self, mock_llm_manager):
        summarizer = Summarizer(llm_manager=mock_llm_manager)

        messages = [
            ContextMessage(
                role="user",
                content="你好",
                timestamp=datetime.now(),
                token_count=2,
                source="user_001",
                metadata={"user_name": "张三"},
            ),
            ContextMessage(
                role="assistant",
                content="你好！",
                timestamp=datetime.now(),
                token_count=3,
                source="bot",
            ),
        ]

        result = Summarizer._format_messages(messages)

        assert "[张三]: 你好" in result
        assert "[助手]: 你好！" in result


class TestSegmentedQueueSummarization:
    def test_queue_full_triggers_summarize(self):
        queue = SegmentedMessageQueue(
            group_id="g1",
            segment_1_length=2,
            segment_3_length=2,
            total_length=8,
        )

        for i in range(8):
            queue.add_message(
                ContextMessage(
                    role="user",
                    content=f"消息{i}",
                    timestamp=datetime.now(),
                    token_count=10,
                    source="user",
                )
            )

        assert queue.is_full()

    def test_target_messages_are_segment_2(self):
        queue = SegmentedMessageQueue(
            group_id="g1",
            segment_1_length=2,
            segment_3_length=2,
            total_length=8,
        )

        for i in range(8):
            queue.add_message(
                ContextMessage(
                    role="user",
                    content=f"消息{i}",
                    timestamp=datetime.now(),
                    token_count=10,
                    source="user",
                )
            )

        target = list(queue.segment_2)
        context = queue.all_messages

        assert len(target) == 4
        assert len(context) == 8

    def test_after_rotate_segments_shift(self):
        queue = SegmentedMessageQueue(
            group_id="g1",
            segment_1_length=2,
            segment_3_length=2,
            total_length=8,
        )

        for i in range(8):
            queue.add_message(
                ContextMessage(
                    role="user",
                    content=f"消息{i}",
                    timestamp=datetime.now(),
                    token_count=10,
                    source="user",
                )
            )

        old_seg1 = list(queue.segment_1)
        old_seg2 = list(queue.segment_2)

        queue.rotate_after_summary()

        assert list(queue.segment_2) == old_seg1
        assert list(queue.segment_3) == old_seg2
        assert len(queue.segment_1) == 0
