"""Web 导入端点大小限制测试（资源耗尽防护）"""

import io
import json
from unittest.mock import Mock

import pytest
from quart import Quart, request as quart_request

import iris_memory.web.routes.data_routes as data_routes
from iris_memory.web.routes.data_routes import _read_upload_capped, import_l2_memory


class _FakeUpload:
    """模拟 Werkzeug FileStorage：仅提供分块 read()"""

    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


@pytest.fixture
def available_manager(monkeypatch):
    """组件全部可用的 component manager"""
    manager = Mock()
    manager.get_component.return_value = Mock(is_available=True)
    monkeypatch.setattr(data_routes, "get_component_manager", lambda: manager)
    return manager


class TestReadUploadCapped:
    def test_under_limit_returns_content(self, monkeypatch):
        monkeypatch.setattr(data_routes, "_MAX_IMPORT_BYTES", 10)
        result = _read_upload_capped(_FakeUpload(b"12345"))
        assert result == "12345"

    def test_over_limit_returns_none(self, monkeypatch):
        monkeypatch.setattr(data_routes, "_MAX_IMPORT_BYTES", 10)
        # 分块读取：累计超限即中止，不返回部分内容
        result = _read_upload_capped(_FakeUpload(b"x" * 11))
        assert result is None

    def test_exact_limit_passes(self, monkeypatch):
        monkeypatch.setattr(data_routes, "_MAX_IMPORT_BYTES", 10)
        result = _read_upload_capped(_FakeUpload(b"abcdefghij"))
        assert result == "abcdefghij"


class TestImportSizeLimits:
    @pytest.mark.asyncio
    async def test_json_body_over_limit_returns_413(
        self, available_manager, monkeypatch
    ):
        monkeypatch.setattr(data_routes, "_MAX_IMPORT_BYTES", 8)
        app = Quart(__name__)
        body = json.dumps({"data": {"entries": []}})
        async with app.test_request_context(
            "/",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        ):
            # Quart 测试上下文不自动设置 CONTENT_LENGTH，显式模拟带长度头的请求
            real_request = quart_request._get_current_object()
            monkeypatch.setattr(
                type(real_request), "content_length", property(lambda self: 9_999_999)
            )
            response, status = await import_l2_memory()
            assert status == 413
            assert "大小上限" in (await response.get_json())["error"]

    @pytest.mark.asyncio
    async def test_entry_count_over_limit_returns_413(
        self, available_manager, monkeypatch
    ):
        monkeypatch.setattr(data_routes, "_MAX_IMPORT_ENTRIES", 2)
        app = Quart(__name__)
        body = json.dumps({"data": {"entries": [{"id": str(i)} for i in range(3)]}})
        async with app.test_request_context(
            "/",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        ):
            response, status = await import_l2_memory()
            assert status == 413
            assert "数量上限" in (await response.get_json())["error"]

    @pytest.mark.asyncio
    async def test_non_list_entries_rejected(self, available_manager):
        app = Quart(__name__)
        body = json.dumps({"data": {"entries": "not-a-list"}})
        async with app.test_request_context(
            "/",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        ):
            response, status = await import_l2_memory()
            assert status == 413
