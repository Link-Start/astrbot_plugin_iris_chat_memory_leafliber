"""persona_id 目录名清洗测试

历史问题：persona_id 未经清洗直接拼入持久化目录名
（data/faiss/memory_<persona_id>），含 ``/``、``..`` 等字符时存在
路径穿越风险。修复后良性值原样保留（不破坏既有部署），危险值替换为
白名单形式并附加原值哈希，保证不同 persona_id 不会碰撞。
"""

import re

from iris_memory.l2_memory.adapter import sanitize_persona_dirname


class TestSanitizePersonaDirname:
    def test_benign_ids_unchanged(self):
        """常见良性值原样保留，既有部署的数据目录不受影响"""
        for pid in ("default", "persona-1", "catgirl_maid", "猫娘", "UUIDv2x9"):
            assert sanitize_persona_dirname(pid) == pid

    def test_empty_falls_back_to_default(self):
        assert sanitize_persona_dirname("") == "default"
        assert sanitize_persona_dirname("   ") == "default"

    def test_path_traversal_rewritten(self):
        for pid in ("../evil", "a/b", "a\\b", "..", "a..b", ".hidden", "x."):
            sanitized = sanitize_persona_dirname(pid)
            assert sanitized != pid
            assert "/" not in sanitized
            assert "\\" not in sanitized
            assert ".." not in sanitized
            assert not sanitized.startswith(".")

    def test_dangerous_ids_do_not_collide(self):
        """不同危险值清洗后互不相同，人格隔离不被破坏"""
        a = sanitize_persona_dirname("../evil")
        b = sanitize_persona_dirname("a/b")
        assert a != b

    def test_result_is_deterministic(self):
        assert sanitize_persona_dirname("../evil") == sanitize_persona_dirname(
            "../evil"
        )

    def test_oversize_id_rewritten_with_hash(self):
        pid = "x" * 200
        sanitized = sanitize_persona_dirname(pid)
        assert sanitized != pid
        # 白名单前缀 + 12 位哈希，总长度受限
        assert re.fullmatch(r"[0-9A-Za-z_\-]{1,32}_[0-9a-f]{12}", sanitized)

    def test_control_chars_rewritten(self):
        sanitized = sanitize_persona_dirname("bad\x00name\n")
        assert sanitized != "bad\x00name\n"
        assert "\x00" not in sanitized
        assert "\n" not in sanitized
