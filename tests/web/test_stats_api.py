"""统计 API 测试"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from iris_memory.web.routes.stats import stats_bp


@pytest.fixture
def mock_component_manager():
    manager = Mock()
    manager.status = Mock()
    manager.status.is_module_available = Mock(return_value=True)
    manager.status.global_status = Mock(value="available")
    manager.get_all_states = Mock(return_value={})
    return manager


@pytest.fixture
def mock_llm_manager():
    llm = Mock()
    llm.is_available = True
    usage = Mock()
    usage.total_input_tokens = 1000
    usage.total_output_tokens = 500
    usage.total_calls = 25
    llm.get_all_token_stats = AsyncMock(
        return_value={
            "global": usage,
            "l1_summarizer": usage,
        }
    )
    return llm


@pytest.fixture
def mock_l2_memory():
    memory = Mock()
    memory.is_available = True
    memory.get_stats = AsyncMock(
        return_value={
            "total_memories": 150,
            "groups_count": 5,
        }
    )
    return memory


@pytest.fixture
def mock_l3_kg():
    kg = Mock()
    kg.is_available = True
    kg.get_stats = AsyncMock(
        return_value={
            "total_nodes": 50,
            "total_edges": 120,
            "node_types": {"concept": 20},
            "edge_types": {"related_to": 80},
        }
    )
    return kg


@pytest.fixture
def mock_l1_buffer():
    buffer = Mock()
    buffer.is_available = True
    buffer.get_stats = Mock(
        return_value={
            "queue_length": 10,
            "max_capacity": 100,
        }
    )
    return buffer


class TestStatsAPI:
    @pytest.mark.asyncio
    async def test_get_token_stats_success(
        self, mock_component_manager, mock_llm_manager
    ):
        mock_component_manager.get_component = Mock(return_value=mock_llm_manager)

        with (
            patch(
                "iris_memory.web.routes.stats.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(stats_bp, url_prefix="/api/iris/stats")

            async with app.test_client() as client:
                response = await client.get("/api/iris/stats/token")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_get_memory_stats_success(
        self, mock_component_manager, mock_l1_buffer, mock_l2_memory, mock_l3_kg
    ):
        def get_component(name):
            if name == "l1_buffer":
                return mock_l1_buffer
            elif name == "l2_memory":
                return mock_l2_memory
            elif name == "l3_kg":
                return mock_l3_kg
            return None

        mock_component_manager.get_component = Mock(side_effect=get_component)

        with (
            patch(
                "iris_memory.web.routes.stats.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(stats_bp, url_prefix="/api/iris/stats")

            async with app.test_client() as client:
                response = await client.get("/api/iris/stats/memory")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_get_knowledge_graph_stats_success(
        self, mock_component_manager, mock_l3_kg
    ):
        mock_component_manager.get_component = Mock(return_value=mock_l3_kg)

        with (
            patch(
                "iris_memory.web.routes.stats.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(stats_bp, url_prefix="/api/iris/stats")

            async with app.test_client() as client:
                response = await client.get("/api/iris/stats/kg")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_get_system_overview_success(
        self,
        mock_component_manager,
        mock_l1_buffer,
        mock_l2_memory,
        mock_l3_kg,
        mock_llm_manager,
    ):
        def get_component(name):
            if name == "l1_buffer":
                return mock_l1_buffer
            elif name == "l2_memory":
                return mock_l2_memory
            elif name == "l3_kg":
                return mock_l3_kg
            elif name == "llm_manager":
                return mock_llm_manager
            return None

        mock_component_manager.get_component = Mock(side_effect=get_component)

        with (
            patch(
                "iris_memory.web.routes.stats.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(stats_bp, url_prefix="/api/iris/stats")

            async with app.test_client() as client:
                response = await client.get("/api/iris/stats/system")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_component_unavailable(self, mock_component_manager):
        mock_llm = Mock()
        mock_llm.is_available = False
        mock_component_manager.get_component = Mock(return_value=mock_llm)

        with (
            patch(
                "iris_memory.web.routes.stats.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(stats_bp, url_prefix="/api/iris/stats")

            async with app.test_client() as client:
                response = await client.get("/api/iris/stats/token")

                assert response.status_code == 503
                data = await response.get_json()
                assert data["success"] is False

    @pytest.mark.asyncio
    async def test_partial_availability(
        self,
        mock_component_manager,
        mock_l1_buffer,
        mock_l2_memory,
        mock_l3_kg,
        mock_llm_manager,
    ):
        def get_component(name):
            if name == "l1_buffer":
                return mock_l1_buffer
            elif name == "l2_memory":
                return mock_l2_memory
            elif name == "l3_kg":
                return mock_l3_kg
            elif name == "llm_manager":
                return mock_llm_manager
            return None

        mock_component_manager.get_component = Mock(side_effect=get_component)

        with (
            patch(
                "iris_memory.web.routes.stats.get_component_manager",
                return_value=mock_component_manager,
            ),
            patch("iris_memory.web.auth.get_access_key", return_value=None),
        ):
            from quart import Quart

            app = Quart(__name__)
            app.register_blueprint(stats_bp, url_prefix="/api/iris/stats")

            async with app.test_client() as client:
                response = await client.get("/api/iris/stats/all")

                assert response.status_code == 200
                data = await response.get_json()
                assert data["success"] is True
