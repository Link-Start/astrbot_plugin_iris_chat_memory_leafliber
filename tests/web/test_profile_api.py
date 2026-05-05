"""画像 API 测试"""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch, AsyncMock
from iris_memory.web.routes.profile import profile_bp


@pytest.fixture
def mock_component_manager():
    manager = Mock()
    return manager


@pytest.fixture
def mock_profile_storage():
    storage = Mock()
    storage.is_available = True
    storage.get_group_profile = AsyncMock(return_value=None)
    storage.update_group_profile = AsyncMock(return_value=True)
    storage.get_user_profile = AsyncMock(return_value=None)
    storage.update_user_profile = AsyncMock(return_value=True)
    return storage


class TestProfileAPI:
    @pytest.mark.asyncio
    async def test_get_group_profile_success(
        self, mock_component_manager, mock_profile_storage
    ):
        mock_profile = SimpleNamespace(
            group_id="group_1",
            group_name="测试群聊",
            interests=["技术"],
            atmosphere_tags=["活跃"],
            long_term_tags=[],
            blacklist_topics=[],
            custom_fields={},
            version=1,
            FIELD_TIERS={},
        )
        mock_profile_storage.get_group_profile = AsyncMock(return_value=mock_profile)
        mock_component_manager.get_component = Mock(return_value=mock_profile_storage)

        with (
            patch(
                "iris_memory.web.routes.profile.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(profile_bp, url_prefix="/api/iris/profile")

            async with app.test_client() as client:
                response = await client.get("/api/iris/profile/group/group_1")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_update_group_profile_success(
        self, mock_component_manager, mock_profile_storage
    ):
        mock_component_manager.get_component = Mock(return_value=mock_profile_storage)

        with (
            patch(
                "iris_memory.web.routes.profile.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(profile_bp, url_prefix="/api/iris/profile")

            async with app.test_client() as client:
                response = await client.put(
                    "/api/iris/profile/group/group_1",
                    json={
                        "atmosphere_tags": ["活跃"],
                        "interests": ["技术", "游戏", "生活"],
                    },
                )

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_get_user_profile_success(
        self, mock_component_manager, mock_profile_storage
    ):
        mock_profile = SimpleNamespace(
            user_id="user_1",
            username="测试用户",
            personality="",
            interests=[],
            long_term_notes="",
            custom_fields={},
            version=1,
            FIELD_TIERS={},
        )
        mock_profile_storage.get_user_profile = AsyncMock(return_value=mock_profile)
        mock_component_manager.get_component = Mock(return_value=mock_profile_storage)

        with (
            patch(
                "iris_memory.web.routes.profile.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(profile_bp, url_prefix="/api/iris/profile")

            async with app.test_client() as client:
                response = await client.get("/api/iris/profile/user/user_1")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_update_user_profile_success(
        self, mock_component_manager, mock_profile_storage
    ):
        mock_component_manager.get_component = Mock(return_value=mock_profile_storage)

        with (
            patch(
                "iris_memory.web.routes.profile.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(profile_bp, url_prefix="/api/iris/profile")

            async with app.test_client() as client:
                response = await client.put(
                    "/api/iris/profile/user/user_1",
                    json={"personality": "内向", "interests": ["阅读", "音乐"]},
                )

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_component_unavailable(self, mock_component_manager):
        mock_storage = Mock()
        mock_storage.is_available = False
        mock_component_manager.get_component = Mock(return_value=mock_storage)

        with (
            patch(
                "iris_memory.web.routes.profile.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(profile_bp, url_prefix="/api/iris/profile")

            async with app.test_client() as client:
                response = await client.get("/api/iris/profile/group/group_1")

                assert response.status_code == 503
                data = await response.get_json()
                assert data["success"] is False

    @pytest.mark.asyncio
    async def test_profile_not_found(
        self, mock_component_manager, mock_profile_storage
    ):
        mock_profile_storage.get_group_profile = AsyncMock(return_value=None)
        mock_component_manager.get_component = Mock(return_value=mock_profile_storage)

        with (
            patch(
                "iris_memory.web.routes.profile.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(profile_bp, url_prefix="/api/iris/profile")

            async with app.test_client() as client:
                response = await client.get("/api/iris/profile/group/nonexistent")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True
                assert data["profile"] == {}
