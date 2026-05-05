"""认证中间件测试"""

import pytest
from unittest.mock import Mock, patch

from iris_memory.web.auth import (
    dashboard_auth,
    get_access_key,
    verify_access_key,
    require_auth,
)


class TestGetAccessKey:
    """get_access_key 函数测试"""

    def test_returns_none_when_no_config(self):
        with patch("iris_memory.config.get_config") as mock_get_config:
            mock_get_config.side_effect = Exception("no config")
            result = get_access_key()
            assert result is None

    def test_returns_none_when_empty_key(self):
        with patch("iris_memory.config.get_config") as mock_get_config:
            mock_config = Mock()
            mock_config.get = Mock(return_value="")
            mock_get_config.return_value = mock_config
            result = get_access_key()
            assert result is None

    def test_returns_key_when_set(self):
        with patch("iris_memory.config.get_config") as mock_get_config:
            mock_config = Mock()
            mock_config.get = Mock(return_value="my_secret_key  ")
            mock_get_config.return_value = mock_config
            result = get_access_key()
            assert result == "my_secret_key"


class TestVerifyAccessKey:
    """verify_access_key 函数测试"""

    def test_no_expected_key_returns_true(self):
        with patch("iris_memory.web.auth.get_access_key", return_value=None):
            result = verify_access_key("any_key")
            assert result is True

    def test_correct_key_returns_true(self):
        with patch("iris_memory.web.auth.get_access_key", return_value="secret123"):
            result = verify_access_key("secret123")
            assert result is True

    def test_wrong_key_returns_false(self):
        with patch("iris_memory.web.auth.get_access_key", return_value="secret123"):
            result = verify_access_key("wrong_key")
            assert result is False

    def test_empty_provided_key_returns_false(self):
        with patch("iris_memory.web.auth.get_access_key", return_value="secret123"):
            result = verify_access_key("")
            assert result is False

    def test_none_provided_key_returns_false(self):
        with patch("iris_memory.web.auth.get_access_key", return_value="secret123"):
            result = verify_access_key(None)
            assert result is False


class TestDashboardAuthSingleton:
    """dashboard_auth 单例测试"""

    def test_singleton_has_require_auth(self):
        assert hasattr(dashboard_auth, "require_auth")

    def test_singleton_has_get_access_key(self):
        assert hasattr(dashboard_auth, "get_access_key")

    def test_singleton_has_verify_access_key(self):
        assert hasattr(dashboard_auth, "verify_access_key")

    def test_require_auth_is_callable(self):
        assert callable(dashboard_auth.require_auth)

    def test_get_access_key_is_callable(self):
        assert callable(dashboard_auth.get_access_key)

    def test_verify_access_key_is_callable(self):
        assert callable(dashboard_auth.verify_access_key)


class TestRequireAuthDecorator:
    """require_auth 装饰器测试"""

    @pytest.mark.asyncio
    async def test_no_key_required(self):
        with patch("iris_memory.web.auth.get_access_key", return_value=None):

            @require_auth
            async def protected_route():
                return {"success": True}

            result = await protected_route()
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_valid_cookie_auth(self):
        with patch("iris_memory.web.auth.get_access_key", return_value="secret123"):
            from unittest.mock import MagicMock

            mock_request = MagicMock()
            mock_request.cookies = {"iris_access_key": "secret123"}
            mock_request.args = {}
            mock_request.headers = {}

            with patch("iris_memory.web.auth.request", mock_request):

                @require_auth
                async def protected_route():
                    return {"success": True}

                result = await protected_route()
                assert result["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_key_returns_unauthorized(self):
        with patch("iris_memory.web.auth.get_access_key", return_value="secret123"):
            from unittest.mock import MagicMock

            mock_request = MagicMock()
            mock_request.cookies = {}
            mock_request.args = {}
            mock_request.headers = {}

            with patch("iris_memory.web.auth.request", mock_request):
                with patch("iris_memory.web.auth.jsonify") as mock_jsonify:
                    mock_jsonify.return_value = {
                        "success": False,
                        "error": "unauthorized",
                    }
                    with patch(
                        "iris_memory.web.auth.verify_access_key", return_value=False
                    ):

                        @require_auth
                        async def protected_route():
                            return {"success": True}

                        result, status_code = await protected_route()
                        assert status_code == 401
