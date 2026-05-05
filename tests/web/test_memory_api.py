"""记忆 API 测试"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from iris_memory.web.routes.memory import memory_bp


@pytest.fixture
def mock_component_manager():
    manager = Mock()
    manager.status = Mock()
    return manager


class TestMemoryAPI:
    @pytest.mark.asyncio
    async def test_search_l2_memory_success(self, mock_component_manager):
        mock_result = Mock()
        mock_result.entry = Mock()
        mock_result.entry.id = "mem_1"
        mock_result.entry.content = "测试记忆内容"
        mock_result.entry.metadata = {
            "group_id": "group_1",
            "timestamp": "2026-03-29T21:00:00Z",
        }
        mock_result.score = 0.95

        mock_l2 = Mock()
        mock_l2.is_available = True
        mock_l2.retrieve = AsyncMock(return_value=[mock_result])
        mock_component_manager.get_component = Mock(return_value=mock_l2)

        with (
            patch(
                "iris_memory.web.routes.memory.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(memory_bp, url_prefix="/api/iris/memory")

            async with app.test_client() as client:
                response = await client.post(
                    "/api/iris/memory/l2/search",
                    json={"query": "测试查询", "group_id": "group_1", "top_k": 10},
                )

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True
                assert len(data["results"]) == 1

    @pytest.mark.asyncio
    async def test_search_l2_memory_component_unavailable(self, mock_component_manager):
        mock_l2 = Mock()
        mock_l2.is_available = False
        mock_component_manager.get_component = Mock(return_value=mock_l2)

        with (
            patch(
                "iris_memory.web.routes.memory.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(memory_bp, url_prefix="/api/iris/memory")

            async with app.test_client() as client:
                response = await client.post(
                    "/api/iris/memory/l2/search", json={"query": "测试查询"}
                )

                assert response.status_code == 503
                data = await response.get_json()
                assert data["success"] is False
                assert "不可用" in data["error"]

    @pytest.mark.asyncio
    async def test_get_l1_buffer_success(self, mock_component_manager):
        mock_msg = Mock()
        mock_msg.role = "user"
        mock_msg.content = "测试消息"
        mock_msg.timestamp = None
        mock_msg.source = "user_1"
        mock_msg.metadata = None

        mock_l1 = Mock()
        mock_l1.is_available = True
        mock_l1.get_context = Mock(return_value=[mock_msg])
        mock_component_manager.get_component = Mock(return_value=mock_l1)

        with (
            patch(
                "iris_memory.web.routes.memory.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(memory_bp, url_prefix="/api/iris/memory")

            async with app.test_client() as client:
                response = await client.get("/api/iris/memory/l1/list?group_id=group_1")

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_l3_knowledge_graph(self, mock_component_manager):
        mock_kg = Mock()
        mock_kg.is_available = True
        mock_kg.get_random_person_node = AsyncMock(
            return_value={"id": "node_1", "name": "Test", "label": "Person"}
        )
        mock_kg.expand_from_node = AsyncMock(
            return_value=(
                [
                    {
                        "id": "node_1",
                        "name": "Test",
                        "label": "Person",
                        "type": "concept",
                    }
                ],
                [{"source": "node_1", "target": "node_2", "relation": "related_to"}],
            )
        )
        mock_component_manager.get_component = Mock(return_value=mock_kg)

        with (
            patch(
                "iris_memory.web.routes.memory.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(memory_bp, url_prefix="/api/iris/memory")

            async with app.test_client() as client:
                response = await client.get("/api/iris/memory/l3/graph")

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_search_validation_missing_query(self):
        with patch("iris_memory.web.auth.get_access_key", return_value=None):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(memory_bp, url_prefix="/api/iris/memory")

            async with app.test_client() as client:
                response = await client.post(
                    "/api/iris/memory/l2/search", json={"group_id": "group_1"}
                )

                assert response.status_code == 400
                data = await response.get_json()
                assert data["success"] is False
