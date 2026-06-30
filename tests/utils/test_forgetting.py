"""遗忘权重算法测试"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from iris_memory.utils.forgetting import (
    calculate_recency,
    calculate_frequency,
    calculate_confidence,
    calculate_isolation_degree,
    calculate_forgetting_score,
    should_evict,
)
from iris_memory.l2_memory.models import MemoryEntry


class TestCalculateRecency:
    """calculate_recency 测试"""

    def test_recent_access(self):
        """测试最近访问"""
        now = datetime.now().isoformat()
        score = calculate_recency(now, lambda_decay=0.1)

        assert score > 0.9
        assert score <= 1.0

    def test_old_access(self):
        """测试很久之前访问"""
        old_time = (datetime.now() - timedelta(days=30)).isoformat()
        score = calculate_recency(old_time, lambda_decay=0.1)

        assert score < 0.1

    def test_no_access_time(self):
        """测试无访问记录"""
        score = calculate_recency(None, lambda_decay=0.1)

        assert score == 0.5

    def test_invalid_time(self):
        """测试无效时间格式"""
        score = calculate_recency("invalid_time", lambda_decay=0.1)

        assert score == 0.5


class TestCalculateFrequency:
    """calculate_frequency 测试"""

    def test_zero_count(self):
        """测试零访问"""
        score = calculate_frequency(0)

        assert score == 0.0

    def test_low_count(self):
        """测试低访问次数"""
        score = calculate_frequency(10, max_count=100)

        assert 0 < score < 0.7

    def test_high_count(self):
        """测试高访问次数"""
        score = calculate_frequency(100, max_count=100)

        assert score == 1.0

    def test_very_high_count(self):
        """测试超高访问次数"""
        score = calculate_frequency(1000, max_count=100)

        assert score == 1.0  # 被限制在 [0, 1]


class TestCalculateConfidence:
    """calculate_confidence 测试"""

    def test_high_confidence(self):
        """测试高置信度"""
        score = calculate_confidence(0.9)

        assert score == 0.9

    def test_low_confidence(self):
        """测试低置信度"""
        score = calculate_confidence(0.1)

        assert score == 0.1

    def test_out_of_range_high(self):
        """测试超出范围的高置信度"""
        score = calculate_confidence(1.5)

        assert score == 1.0

    def test_out_of_range_low(self):
        """测试超出范围的低置信度"""
        score = calculate_confidence(-0.5)

        assert score == 0.0


class TestCalculateIsolationDegree:
    """calculate_isolation_degree 测试"""

    def test_default_isolation(self):
        score = calculate_isolation_degree({})

        assert score == 0.0

    def test_with_metadata(self):
        score = calculate_isolation_degree({"connected_count": 5})

        assert score == pytest.approx(1.0 / 6.0, abs=0.01)

    def test_zero_connections(self):
        score = calculate_isolation_degree({"connected_count": 0})

        assert score == 1.0


class TestCalculateForgettingScore:
    """calculate_forgetting_score 测试"""

    @pytest.fixture
    def mock_config(self):
        config = Mock()
        config.get = Mock(
            side_effect=lambda key, default=None: {
                "forgetting_lambda": 0.1,
                "forgetting_threshold": 0.3,
                "forgetting_immediate_eviction_threshold": 0.1,
            }.get(key, default)
        )
        return config

    def test_high_importance(self, mock_config):
        """测试高重要性记忆"""
        entry = MemoryEntry(
            id="mem_001",
            content="重要记忆",
            metadata={
                "last_access_time": datetime.now().isoformat(),
                "access_count": 50,
                "confidence": 0.9,
            },
        )

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            score = calculate_forgetting_score(entry)

            assert score > 0.7

    def test_low_importance(self, mock_config):
        """测试低重要性记忆"""
        entry = MemoryEntry(
            id="mem_002",
            content="不重要记忆",
            metadata={
                "last_access_time": (datetime.now() - timedelta(days=60)).isoformat(),
                "access_count": 0,
                "confidence": 0.1,
            },
        )

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            score = calculate_forgetting_score(entry)

            assert score < 0.5

    def test_custom_weights(self, mock_config):
        """测试自定义权重"""
        entry = MemoryEntry(
            id="mem_003",
            content="测试记忆",
            metadata={
                "last_access_time": datetime.now().isoformat(),
                "access_count": 10,
                "confidence": 0.8,
            },
        )

        weights = {
            "w1": 0.5,  # 近因性权重提高
            "w2": 0.2,
            "w3": 0.2,
            "w4": 0.1,
        }

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            score = calculate_forgetting_score(entry, weights=weights)

            assert 0 < score <= 1.0


class TestShouldEvict:
    """should_evict 测试"""

    @pytest.fixture
    def mock_config(self):
        config = Mock()
        config.get = Mock(
            side_effect=lambda key, default=None: {
                "forgetting_lambda": 0.1,
                "forgetting_threshold": 0.3,
                "forgetting_immediate_eviction_threshold": 0.1,
            }.get(key, default)
        )
        return config

    def test_should_evict_old_low_score(self, mock_config):
        """测试应该淘汰的旧记忆"""
        entry = MemoryEntry(
            id="mem_001",
            content="旧记忆",
            metadata={
                "last_access_time": (datetime.now() - timedelta(days=60)).isoformat(),
                "access_count": 0,
                "confidence": 0.1,
            },
        )

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            result = should_evict(entry, threshold=0.3, retention_days=30)

            assert result

    def test_should_not_evict_recent(self, mock_config):
        """测试不应淘汰的近期记忆"""
        entry = MemoryEntry(
            id="mem_002",
            content="近期记忆",
            metadata={
                "last_access_time": datetime.now().isoformat(),
                "access_count": 10,
                "confidence": 0.8,
            },
        )

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            result = should_evict(entry, threshold=0.3, retention_days=30)

            assert not result

    def test_should_not_evict_within_retention(self, mock_config):
        """测试在保留期内不应淘汰"""
        entry = MemoryEntry(
            id="mem_003",
            content="低分但在保留期内",
            metadata={
                "last_access_time": (datetime.now() - timedelta(days=10)).isoformat(),
                "access_count": 0,
                "confidence": 0.1,
            },
        )

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            result = should_evict(entry, threshold=0.3, retention_days=30)

            # 虽然分数低，但在保留期内，不应淘汰
            assert not result

    def test_should_evict_no_access_time(self, mock_config):
        """测试无访问记录应该淘汰"""
        entry = MemoryEntry(
            id="mem_004",
            content="无访问记录",
            metadata={"access_count": 0, "confidence": 0.1},
        )

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            result = should_evict(entry, threshold=0.3, retention_days=30)

            # 无访问记录且分数低，应该淘汰
            assert result

    def test_should_evict_uses_explicit_threshold_not_config_default(self, mock_config):
        """回归：should_evict 应使用显式传入的 threshold，而非配置默认值 0.3

        历史 bug：形参 threshold 被静默忽略，调用方传入 threshold=0.5 时
        仍回退到配置默认 0.3。修复后 evict_threshold = threshold if threshold
        != 0.3 else config_threshold。以 forgetting_score=0.4 为例：
        threshold=0.5 → 0.4 < 0.5 且无访问记录 → 淘汰；
        threshold=0.3 → 0.4 >= 0.3 → 不淘汰。
        """
        entry = MemoryEntry(
            id="mem_threshold",
            content="阈值测试记忆",
            metadata={"access_count": 0, "confidence": 0.4},
        )

        with patch("iris_memory.utils.forgetting.get_config", return_value=mock_config):
            with patch(
                "iris_memory.utils.forgetting.calculate_forgetting_score",
                return_value=0.4,
            ):
                # 0.4 >= immediate_threshold(0.1)，不触发立即淘汰
                # threshold=0.5：evict_threshold=0.5，0.4 < 0.5 且无访问记录 → 淘汰
                assert should_evict(entry, threshold=0.5, retention_days=30)

                # threshold=0.3：evict_threshold=配置值 0.3，0.4 >= 0.3 → 不淘汰
                assert not should_evict(entry, threshold=0.3, retention_days=30)
