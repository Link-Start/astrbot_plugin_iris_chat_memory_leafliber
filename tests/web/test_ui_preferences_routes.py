"""ui_preferences 原子写测试

历史问题：_save_prefs 是全仓库唯一一处非原子写（直接 open("w")），
写入中途崩溃会留下截断文件，且 open("w") 会跟随目标路径上的符号链接。
修复后改用 atomic_write_json（mkstemp + fsync + os.replace）。
"""

import json
from unittest.mock import Mock

from iris_memory.web.routes.ui_preferences_routes import _save_prefs


class TestUiPreferencesAtomicWrite:
    def test_save_prefs_writes_complete_json(self, tmp_path, monkeypatch):
        config = Mock()
        config.data_dir = tmp_path / "data"
        monkeypatch.setattr(
            "iris_memory.web.routes.ui_preferences_routes.get_config",
            lambda: config,
        )

        _save_prefs({"dark_mode": False})

        target = tmp_path / "data" / "ui_preferences.json"
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == {"dark_mode": False}
        # 原子写不应在同目录留下残留临时文件
        leftovers = [p for p in target.parent.iterdir() if p.name != target.name]
        assert leftovers == []
