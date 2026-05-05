"""Pytest 配置文件"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class _ToolExecResult:
    def __init__(self, result="", **kwargs):
        self.result = result
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"ToolExecResult(result={self.result!r})"


_TOOL_MODULES = [
    "iris_memory.tools.save_memory",
    "iris_memory.tools.search_memory",
    "iris_memory.tools.save_knowledge",
    "iris_memory.tools.correct_memory",
    "iris_memory.tools.get_profile",
    "iris_memory.tools.search_knowledge_graph",
]


@pytest.fixture(autouse=True)
def _patch_tool_exec_result():
    import astrbot.core.agent.tool as tool_mod

    original = tool_mod.ToolExecResult
    tool_mod.ToolExecResult = _ToolExecResult

    patched = {}
    for mod_name in _TOOL_MODULES:
        import importlib

        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "ToolExecResult"):
                patched[mod_name] = mod.ToolExecResult
                mod.ToolExecResult = _ToolExecResult
        except ImportError:
            pass

    yield

    tool_mod.ToolExecResult = original
    for mod_name, orig in patched.items():
        try:
            mod = importlib.import_module(mod_name)
            mod.ToolExecResult = orig
        except ImportError:
            pass


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"
