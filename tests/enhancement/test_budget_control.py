"""
测试 Token 预算控制器
"""

from unittest.mock import MagicMock, patch
from iris_memory.l2_memory.models import MemoryEntry, MemorySearchResult
from iris_memory.enhancement.budget_control import TokenBudgetController


def create_memory_result(content: str, memory_id: str = None) -> MemorySearchResult:
    entry = MemoryEntry(
        id=memory_id or f"mem_{hash(content)}", content=content, metadata={}
    )
    return MemorySearchResult(entry=entry, score=0.9, distance=0.1)


class TestTokenBudgetController:
    def test_estimate_tokens_with_character_estimation(self):
        with patch(
            "iris_memory.enhancement.budget_control.get_config"
        ) as mock_get_config:
            mock_config = MagicMock()
            mock_config.get = MagicMock(return_value=2000)
            mock_get_config.return_value = mock_config

            controller = TokenBudgetController()

            text_zh = "你好世界"
            tokens_zh = controller.estimate_tokens(text_zh)
            assert tokens_zh > 0

            text_en = "Hello World"
            tokens_en = controller.estimate_tokens(text_en)
            assert tokens_en > 0

            tokens_empty = controller.estimate_tokens("")
            assert tokens_empty == 0

    def test_trim_memories_basic(self):
        controller = TokenBudgetController(max_tokens=100)

        memories = [
            create_memory_result("这是一条测试记忆，长度适中"),
            create_memory_result("这是另一条测试记忆，也比较适中"),
            create_memory_result("这是第三条测试记忆，同样适中"),
        ]

        trimmed, total_tokens = controller.trim_memories(memories)

        assert len(trimmed) > 0
        assert len(trimmed) <= len(memories)
        assert total_tokens <= 100

    def test_trim_memories_with_budget_exceeded(self):
        controller = TokenBudgetController(max_tokens=50)

        memories = [
            create_memory_result(
                "这是一条比较长的测试记忆，用于测试Token预算控制功能是否正常工作"
            ),
            create_memory_result(
                "这是另一条比较长的测试记忆，同样用于测试Token预算控制功能"
            ),
            create_memory_result(
                "这是第三条比较长的测试记忆，继续测试Token预算控制功能"
            ),
        ]

        trimmed, total_tokens = controller.trim_memories(memories)

        assert len(trimmed) < len(memories)
        assert total_tokens <= 50

    def test_trim_memories_single_memory_exceeds_budget(self):
        controller = TokenBudgetController(max_tokens=10)

        long_content = "这是一条非常非常非常非常非常长的测试记忆，远远超出Token预算"
        memories = [create_memory_result(long_content)]

        trimmed, total_tokens = controller.trim_memories(memories)

        assert len(trimmed) == 1
        assert trimmed[0].entry.content == long_content

    def test_trim_memories_empty_list(self):
        with patch(
            "iris_memory.enhancement.budget_control.get_config"
        ) as mock_get_config:
            mock_config = MagicMock()
            mock_config.get = MagicMock(return_value=2000)
            mock_get_config.return_value = mock_config

            controller = TokenBudgetController()

            trimmed, total_tokens = controller.trim_memories([])

            assert len(trimmed) == 0
            assert total_tokens == 0

    def test_estimate_total_tokens(self):
        with patch(
            "iris_memory.enhancement.budget_control.get_config"
        ) as mock_get_config:
            mock_config = MagicMock()
            mock_config.get = MagicMock(return_value=2000)
            mock_get_config.return_value = mock_config

            controller = TokenBudgetController()

            memories = [
                create_memory_result("测试记忆一"),
                create_memory_result("测试记忆二"),
                create_memory_result("测试记忆三"),
            ]

            total = controller.estimate_total_tokens(memories)

            expected = sum(
                controller.estimate_tokens(m.entry.content) for m in memories
            )
            assert total == expected

    def test_can_fit(self):
        controller = TokenBudgetController(max_tokens=100)

        memories = [
            create_memory_result("短记忆一"),
            create_memory_result("短记忆二"),
        ]

        assert controller.can_fit(memories)
        assert controller.can_fit(memories, additional_tokens=50)
        assert not controller.can_fit(memories, additional_tokens=200)

    def test_trim_memories_preserve_order(self):
        controller = TokenBudgetController(max_tokens=200)

        memories = [
            create_memory_result("记忆A", "mem_a"),
            create_memory_result("记忆B", "mem_b"),
            create_memory_result("记忆C", "mem_c"),
        ]

        trimmed, _ = controller.trim_memories(memories, preserve_order=True)

        assert [m.entry.id for m in trimmed] == ["mem_a", "mem_b", "mem_c"]
