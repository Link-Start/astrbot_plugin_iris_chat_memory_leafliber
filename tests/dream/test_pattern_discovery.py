"""
PatternDiscoveryPhase 模式挖掘测试

测试核心功能：
- 记忆分组采样
- LLM 模式提取
- 模式解析
- 去重写入
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from iris_memory.dream.pattern_discovery import PatternDiscoveryPhase


def _mock_config():
    mock = Mock()
    mock.get = Mock(side_effect=lambda key, default=None: {
        "dream_pattern_sample_size": 30,
        "dream_pattern_min_confidence": "medium",
        "isolation_config.enable_group_memory_isolation": False,
    }.get(key, default))
    return mock


class TestPatternDiscoveryPhase:

    @pytest.fixture
    def phase(self):
        return PatternDiscoveryPhase()

    @pytest.mark.asyncio
    async def test_execute_no_llm(self, phase):
        l2 = Mock()
        l2.is_available = True
        l3 = None
        llm = None

        with patch("iris_memory.dream.pattern_discovery.get_config", return_value=_mock_config()):
            result = await phase.execute(l2, l3, llm)

        assert result["patterns_found"] == 0
        assert result["patterns_written"] == 0

    @pytest.mark.asyncio
    async def test_execute_no_entries(self, phase):
        l2 = Mock()
        l2.is_available = True
        l2.get_all_entries = AsyncMock(return_value=[])
        l3 = None
        llm = Mock()

        with patch("iris_memory.dream.pattern_discovery.get_config", return_value=_mock_config()):
            result = await phase.execute(l2, l3, llm)

        assert result["patterns_found"] == 0
        assert result["patterns_written"] == 0

    def test_parse_patterns_valid(self, phase):
        response = """PATTERN: 用户偏好使用Python进行开发
EVIDENCE: 1,3,5
CONFIDENCE: high

PATTERN: 用户习惯在晚上讨论技术问题
EVIDENCE: 2,4
CONFIDENCE: medium"""

        patterns = phase._parse_patterns(response)

        assert len(patterns) == 2
        assert patterns[0]["description"] == "用户偏好使用Python进行开发"
        assert patterns[0]["confidence"] == "high"
        assert patterns[1]["confidence"] == "medium"

    def test_parse_patterns_empty(self, phase):
        patterns = phase._parse_patterns("")
        assert len(patterns) == 0

    def test_parse_patterns_no_confidence(self, phase):
        response = "PATTERN: 测试模式\nEVIDENCE: 1"
        patterns = phase._parse_patterns(response)
        assert len(patterns) == 1
        assert patterns[0]["description"] == "测试模式"
        assert "confidence" not in patterns[0]
