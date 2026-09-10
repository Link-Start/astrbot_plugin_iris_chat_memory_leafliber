"""hidden_config 日志掩码测试

历史问题：set()/delete() 把配置值与旧值明文打进日志；隐藏配置允许
外部槽位写入任意内容，未来若出现密钥类字段会直接泄露。修复后数值/布尔
保留可读性（调优排查需要），字符串只留前缀与长度提示。
"""

from iris_memory.config.hidden_config import _mask_value


class TestMaskValue:
    def test_numbers_and_bools_readable(self):
        assert _mask_value(42) == "42"
        assert _mask_value(3.5) == "3.5"
        assert _mask_value(True) == "True"
        assert _mask_value(None) == "None"

    def test_short_strings_fully_masked(self):
        assert _mask_value("abc") == "***"
        assert _mask_value("abcd") == "***"

    def test_long_strings_keep_prefix_only(self):
        masked = _mask_value("sk-secret-token-value")
        assert masked.startswith("sk")
        assert "secret-token" not in masked
        assert "len=21" in masked
