"""L1 缓冲组件测试"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime

from iris_memory.l1_buffer import L1Buffer, ContextMessage
from iris_memory.l1_buffer.models import SegmentedMessageQueue
from iris_memory.config import init_config


@pytest.fixture
def mock_config(tmp_path: Path):
    """模拟配置"""
    astrbot_config = Mock()
    astrbot_config.__getitem__ = Mock(
        return_value={
            "enable": True,
            "summary_provider": "",
            "inject_queue_length": 20,
            "max_queue_tokens": 4000,
            "max_single_message_tokens": 500,
        }
    )
    astrbot_config.__contains__ = Mock(return_value=True)

    return init_config(astrbot_config, tmp_path)


class TestL1Buffer:
    """L1 缓冲组件测试"""

    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_config):
        """测试初始化成功"""
        buffer = L1Buffer()

        await buffer.initialize()

        assert buffer.is_available
        assert buffer.name == "l1_buffer"

    @pytest.mark.asyncio
    async def test_initialize_disabled(self, mock_config):
        """测试禁用状态初始化"""
        with patch("iris_memory.l1_buffer.buffer.get_config") as mock_get_config:
            mock_get_config.return_value.get = Mock(
                side_effect=lambda key, default=None: {"l1_buffer.enable": False}.get(
                    key, default
                )
            )

            buffer = L1Buffer()
            await buffer.initialize()

            assert not buffer.is_available

    @pytest.mark.asyncio
    async def test_shutdown(self, mock_config):
        """测试关闭"""
        buffer = L1Buffer()
        await buffer.initialize()

        # 添加一些消息
        await buffer.add_message("group_123", "user", "测试", "user_456")

        await buffer.shutdown()

        assert not buffer.is_available
        assert len(buffer._queues) == 0

    @pytest.mark.asyncio
    async def test_add_message_success(self, mock_config):
        """测试添加消息成功"""
        buffer = L1Buffer()
        await buffer.initialize()

        success = await buffer.add_message(
            group_id="group_123", role="user", content="你好", source="user_456"
        )

        assert success

        context = buffer.get_context("group_123")
        assert len(context) == 1
        assert context[0].content == "你好"

    @pytest.mark.asyncio
    async def test_add_message_too_large(self, mock_config):
        """测试添加超大消息"""
        with patch("iris_memory.l1_buffer.buffer.get_config") as mock_get_config:
            mock_get_config.return_value.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.enable": True,
                    "l1_max_single_message_tokens": 10,
                }.get(key, default)
            )

            buffer = L1Buffer()
            await buffer.initialize()

            # 创建一个超过限制的消息
            large_content = "这是一条很长的消息" * 100

            success = await buffer.add_message(
                group_id="group_123",
                role="user",
                content=large_content,
                source="user_456",
            )

            assert not success

            context = buffer.get_context("group_123")
            assert len(context) == 0

    @pytest.mark.asyncio
    async def test_add_message_disabled(self, mock_config):
        """测试禁用时添加消息"""
        with patch("iris_memory.l1_buffer.buffer.get_config") as mock_get_config:
            mock_get_config.return_value.get = Mock(
                side_effect=lambda key, default=None: {"l1_buffer.enable": False}.get(
                    key, default
                )
            )

            buffer = L1Buffer()
            await buffer.initialize()

            success = await buffer.add_message(
                group_id="group_123", role="user", content="测试", source="user_456"
            )

            assert not success

    @pytest.mark.asyncio
    async def test_get_context_with_limit(self, mock_config):
        """测试获取有限制的上下文"""
        buffer = L1Buffer()
        await buffer.initialize()

        # 添加 10 条消息
        for i in range(10):
            await buffer.add_message(
                group_id="group_123", role="user", content=f"消息{i}", source="user_456"
            )

        # 获取最近 5 条
        context = buffer.get_context("group_123", max_length=5)

        assert len(context) == 5
        assert context[0].content == "消息5"
        assert context[4].content == "消息9"

    @pytest.mark.asyncio
    async def test_clear_context(self, mock_config):
        """测试清空指定队列"""
        buffer = L1Buffer()
        await buffer.initialize()

        # 添加消息
        await buffer.add_message("group_123", "user", "测试", "user_456")

        buffer.clear_context("group_123")

        context = buffer.get_context("group_123")
        assert len(context) == 0

    @pytest.mark.asyncio
    async def test_clear_all(self, mock_config):
        """测试清空所有队列"""
        buffer = L1Buffer()
        await buffer.initialize()

        # 添加消息到多个队列
        await buffer.add_message("group_123", "user", "测试1", "user_456")
        await buffer.add_message("group_456", "user", "测试2", "user_789")

        buffer.clear_all()

        assert len(buffer._queues) == 0

    @pytest.mark.asyncio
    async def test_group_isolation_always_enabled(self, mock_config):
        """测试 L1 缓冲始终按群隔离

        L1 不受 enable_group_memory_isolation 配置影响，始终分群存储。
        该配置仅控制 L2/L3 的查询是否带群 ID 条件。
        """
        with patch("iris_memory.l1_buffer.buffer.get_config") as mock_get_config:
            mock_get_config.return_value.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.enable": True,
                }.get(key, default)
            )

            buffer = L1Buffer()
            await buffer.initialize()

            await buffer.add_message("group_123", "user", "测试1", "user_456")
            await buffer.add_message("group_456", "user", "测试2", "user_789")

            assert len(buffer._queues) == 2

            context1 = buffer.get_context("group_123")
            context2 = buffer.get_context("group_456")

            assert len(context1) == 1
            assert len(context2) == 1

    @pytest.mark.asyncio
    async def test_get_queue_stats(self, mock_config):
        """测试获取队列统计"""
        buffer = L1Buffer()
        await buffer.initialize()

        # 添加消息
        await buffer.add_message("group_123", "user", "测试", "user_456")

        stats = buffer.get_queue_stats("group_123")

        assert stats is not None
        assert stats["message_count"] == 1
        assert stats["total_tokens"] > 0

    @pytest.mark.asyncio
    async def test_get_queue_stats_nonexistent(self, mock_config):
        """测试获取不存在的队列统计"""
        buffer = L1Buffer()
        await buffer.initialize()

        stats = buffer.get_queue_stats("nonexistent_group")

        assert stats is None


def _make_msg(content: str = "测试消息", token_count: int = 10) -> ContextMessage:
    return ContextMessage(
        role="user",
        content=content,
        timestamp=datetime.now(),
        token_count=token_count,
        source="group_test",
    )


class TestEmptySummarySegmentPreservation:
    """回归：空总结首次失败不得 rotate，segment_2 必须保留以供重试。

    历史 bug：else 分支仅 fail_count>=2 时 return，fail_count==1 时
    落到 rotate_after_summary() 清空 segment_2，重试阈值 2 形同虚设。
    """

    def _build_buffer_with_queue(self, mock_config, seg2_count: int = 3):
        """构造一个 segment_2 有内容的 buffer，summarizer 返回空。"""
        buffer = L1Buffer()
        buffer._is_available = True
        buffer._component_manager = None  # 避免 _get_or_create_summarizer 触达

        queue = SegmentedMessageQueue(group_id="group_test")
        for _ in range(seg2_count):
            queue.segment_2.append(_make_msg(token_count=10))
        queue.total_tokens = seg2_count * 10
        buffer._queues["group_test"] = queue

        # summarizer.should_summarize -> True；summarize -> ""（空总结）
        fake_summarizer = Mock()
        fake_summarizer.should_summarize = Mock(return_value=True)
        fake_summarizer.summarize = AsyncMock(return_value="")
        buffer._summarizer = fake_summarizer

        # 副作用桩，避免触碰 L2/profile
        buffer._write_summary_to_l2 = AsyncMock(return_value=None)
        buffer._update_profile_after_summary = AsyncMock(return_value=None)
        buffer._clear_images_for_summarized_messages = Mock()

        return buffer, queue

    @pytest.mark.asyncio
    async def test_empty_summary_first_failure_preserves_segment_2(self, mock_config):
        """首次空总结失败：segment_2 保留，不 rotate"""
        with patch("iris_memory.l1_buffer.buffer.get_config") as mock_get_config:
            mock_get_config.return_value.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.enable": True,
                }.get(key, default)
            )
            buffer, queue = self._build_buffer_with_queue(mock_config, seg2_count=3)

            await buffer._check_and_summarize("group_test")

            # 关键断言：segment_2 内容未被 rotate 清空
            assert len(queue.segment_2) == 3, (
                "空总结首次失败不应 rotate，segment_2 必须保留"
            )
            assert len(queue.segment_3) == 0
            # 失败计数递增到 1
            assert buffer._summary_fail_counts["group_test"] == 1
            # 未写入 L2
            buffer._write_summary_to_l2.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_summary_second_failure_clears_segment_2(self, mock_config):
        """第二次空总结失败（达阈值）：清除 segment_2 并重置计数"""
        with patch("iris_memory.l1_buffer.buffer.get_config") as mock_get_config:
            mock_get_config.return_value.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.enable": True,
                }.get(key, default)
            )
            buffer, queue = self._build_buffer_with_queue(mock_config, seg2_count=3)
            # 预置已失败一次，本次为第二次
            buffer._summary_fail_counts["group_test"] = 1

            await buffer._check_and_summarize("group_test")

            assert len(queue.segment_2) == 0, "达阈值时应 clear_segment_2"
            assert buffer._summary_fail_counts["group_test"] == 0  # 重置

    @pytest.mark.asyncio
    async def test_successful_summary_rotates(self, mock_config):
        """对照：成功总结后正常 rotate，segment_2 清空"""
        with patch("iris_memory.l1_buffer.buffer.get_config") as mock_get_config:
            mock_get_config.return_value.get = Mock(
                side_effect=lambda key, default=None: {
                    "l1_buffer.enable": True,
                }.get(key, default)
            )
            buffer, queue = self._build_buffer_with_queue(mock_config, seg2_count=3)
            buffer._summarizer.summarize = AsyncMock(return_value="有内容的总结")

            await buffer._check_and_summarize("group_test")

            assert len(queue.segment_2) == 0, "成功总结应 rotate 清空 segment_2"
            assert buffer._summary_fail_counts["group_test"] == 0
            buffer._write_summary_to_l2.assert_awaited_once()


class TestUserIdentification:
    """测试用户识别逻辑"""

    def test_build_name_to_id_map(self):
        """测试构建用户名到用户ID的映射"""
        buffer = L1Buffer()

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
            ContextMessage(
                role="user",
                content="我还喜欢吃香蕉",
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

        name_to_id = buffer._build_name_to_id_map(messages)

        assert len(name_to_id) == 2
        assert name_to_id["张三"] == "user_001"
        assert name_to_id["李四"] == "user_002"

    def test_build_name_to_id_map_empty(self):
        """测试空消息列表"""
        buffer = L1Buffer()

        name_to_id = buffer._build_name_to_id_map([])

        assert len(name_to_id) == 0

    def test_build_name_to_id_map_no_metadata(self):
        """测试没有 metadata 的消息"""
        buffer = L1Buffer()

        messages = [
            ContextMessage(
                role="user",
                content="我喜欢吃苹果",
                timestamp=datetime.now(),
                token_count=5,
                source="user_001",
            ),
        ]

        name_to_id = buffer._build_name_to_id_map(messages)

        assert len(name_to_id) == 0

    def test_extract_user_from_item(self):
        """测试从总结条目提取用户ID"""
        buffer = L1Buffer()

        name_to_id = {"张三": "user_001", "李四": "user_002"}

        user_id = buffer._extract_user_from_item("张三提到喜欢吃苹果", name_to_id)

        assert user_id == "user_001"

        user_id = buffer._extract_user_from_item("李四表示喜欢编程", name_to_id)

        assert user_id == "user_002"

    def test_extract_user_no_match(self):
        """测试无法匹配时返回 None"""
        buffer = L1Buffer()

        name_to_id = {"张三": "user_001", "李四": "user_002"}

        user_id = buffer._extract_user_from_item("王五提到今天天气很好", name_to_id)

        assert user_id is None

    def test_extract_user_empty_map(self):
        """测试空用户映射"""
        buffer = L1Buffer()

        user_id = buffer._extract_user_from_item("任何内容", {})

        assert user_id is None


class TestParseSummaryItems:
    """测试分条总结解析"""

    def test_parse_with_dash_prefix(self):
        """测试解析带 "- " 前缀的条目"""
        buffer = L1Buffer()

        summary = """- 用户提到喜欢吃苹果
- 用户询问了项目的配置方法
- 用户表示今天工作压力很大"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 3
        assert items[0] == "用户提到喜欢吃苹果"
        assert items[1] == "用户询问了项目的配置方法"
        assert items[2] == "用户表示今天工作压力很大"

    def test_parse_with_bullet_prefix(self):
        """测试解析带 "• " 前缀的条目"""
        buffer = L1Buffer()

        summary = """• 用户提到喜欢吃苹果
• 用户询问了项目的配置方法"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 2
        assert items[0] == "用户提到喜欢吃苹果"
        assert items[1] == "用户询问了项目的配置方法"

    def test_parse_mixed_format(self):
        """测试解析混合格式的条目"""
        buffer = L1Buffer()

        summary = """- 用户提到喜欢吃苹果
1. 用户询问了项目的配置方法
• 用户表示今天工作压力很大"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 3

    def test_parse_empty_lines_ignored(self):
        """测试空行被忽略"""
        buffer = L1Buffer()

        summary = """- 用户提到喜欢吃苹果

- 用户询问了项目的配置方法

"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 2

    def test_parse_short_items_filtered(self):
        """测试短条目被过滤"""
        buffer = L1Buffer()

        summary = """- 用户提到喜欢吃苹果
- 短
- 用户询问了项目的配置方法
- abc
- 用户表示今天工作压力很大"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 3
        assert "短" not in items
        assert "abc" not in items

    def test_parse_min_length_parameter(self):
        """测试最小长度参数"""
        buffer = L1Buffer()

        summary = """- 用户提到喜欢吃苹果和橙子
- 短条目
- 用户询问了项目的配置方法"""

        items = buffer._parse_summary_items(summary, min_length=10)

        assert len(items) == 2
        assert "短条目" not in items

    def test_parse_plain_lines(self):
        """测试解析无前缀的普通行"""
        buffer = L1Buffer()

        summary = """用户提到喜欢吃苹果
用户询问了项目的配置方法
用户表示今天工作压力很大"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 3

    def test_parse_empty_summary(self):
        """测试空总结"""
        buffer = L1Buffer()

        items = buffer._parse_summary_items("")

        assert len(items) == 0

    def test_parse_whitespace_only(self):
        """测试仅包含空白字符的总结"""
        buffer = L1Buffer()

        summary = """   
   
"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 0

    def test_parse_chinese_numbered_prefix(self):
        """测试中文数字前缀"""
        buffer = L1Buffer()

        summary = """1、用户提到喜欢吃苹果
2、用户询问了项目的配置方法"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 2
        assert items[0] == "用户提到喜欢吃苹果"
        assert items[1] == "用户询问了项目的配置方法"

    def test_parse_parenthesis_prefix(self):
        """测试括号前缀"""
        buffer = L1Buffer()

        summary = """1) 用户提到喜欢吃苹果
2) 用户询问了项目的配置方法"""

        items = buffer._parse_summary_items(summary)

        assert len(items) == 2
        assert items[0] == "用户提到喜欢吃苹果"
        assert items[1] == "用户询问了项目的配置方法"

    def test_parse_skips_markdown_fences(self):
        """回归测试：行式回退不应把 Markdown 代码块标记当作记忆。"""
        buffer = L1Buffer()

        summary = """```json
{
  "memories": []
}
```"""

        items = buffer._parse_summary_items(summary)

        assert items == []
        assert not any("```" in i for i in items)

    def test_parse_skips_json_structural_lines(self):
        """回归测试：行式回退不应把 JSON 骨架行（括号、键名行）当作记忆。"""
        buffer = L1Buffer()

        summary = """{
  "memories": [
    {"content": "有效记忆条目内容", "confidence": "high"}
  ]
}"""

        items = buffer._parse_summary_items(summary)

        # 只应保留真正的记忆文本，不含 JSON 结构行
        assert all(not i.startswith("{") for i in items)
        assert all(not i.startswith("}") for i in items)
        assert all('"memories"' not in i for i in items)
        assert all('"content"' not in i for i in items)

    def test_parse_fenced_empty_json_no_garbage(self):
        """回归测试：用户报告的 bug——```json + "memories": [] 被误导入。"""
        buffer = L1Buffer()

        summary = '```json\n{\n  "memories": []\n}\n```'

        items = buffer._parse_summary_items(summary)

        assert items == []
        assert "```json" not in items
        assert '"memories": []' not in items
