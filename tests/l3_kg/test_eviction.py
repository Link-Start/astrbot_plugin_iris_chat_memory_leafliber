"""L3 知识图谱淘汰策略测试"""

import pytest
import pytest_asyncio
from pathlib import Path
import tempfile
import shutil
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from iris_memory.l3_kg import (
    GraphNode,
    GraphEdge,
    L3KGAdapter,
)
from iris_memory.config import init_config
from iris_memory.tasks.forgetting_task import ForgettingTask


class TestAdapterEviction:
    """L3KGAdapter 淘汰功能测试"""

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest_asyncio.fixture
    async def adapter(self, temp_dir):
        from unittest.mock import Mock

        astrbot_config = Mock()
        astrbot_config.__getitem__ = Mock(return_value={"enable": True})
        astrbot_config.__contains__ = Mock(return_value=True)
        init_config(astrbot_config, temp_dir)

        adapter = L3KGAdapter()
        await adapter.initialize()

        yield adapter

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_evict_nodes(self, adapter):
        node1 = GraphNode(id="", label="Person", name="Alice", content="测试用户")
        node1.id = node1.generate_id()

        node2 = GraphNode(id="", label="Person", name="Bob", content="测试用户")
        node2.id = node2.generate_id()

        await adapter.add_node(node1)
        await adapter.add_node(node2)

        deleted = await adapter.evict_nodes([node1.id])

        assert deleted == 1

        stats = await adapter.get_stats()
        assert stats["node_count"] == 1

    @pytest.mark.asyncio
    async def test_evict_nodes_empty_list(self, adapter):
        deleted = await adapter.evict_nodes([])
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_evict_nodes_unavailable_adapter(self, adapter):
        adapter._is_available = False

        deleted = await adapter.evict_nodes(["test_id"])
        assert deleted == 0

        adapter._is_available = True

    @pytest.mark.asyncio
    async def test_get_all_nodes(self, adapter):
        node = GraphNode(id="", label="Person", name="TestUser", content="测试用户")
        node.id = node.generate_id()

        await adapter.add_node(node)

        nodes = await adapter.get_all_nodes()

        assert len(nodes) >= 1
        assert any(n["id"] == node.id for n in nodes)

    @pytest.mark.asyncio
    async def test_get_all_nodes_empty(self, adapter):
        nodes = await adapter.get_all_nodes()
        assert nodes == []

    @pytest.mark.asyncio
    async def test_evict_nodes_with_nonexistent_id(self, adapter):
        deleted = await adapter.evict_nodes(["nonexistent_id"])
        assert deleted == len(["nonexistent_id"])

    @pytest.mark.asyncio
    async def test_evict_nodes_with_edges(self, adapter):
        node1 = GraphNode(id="", label="Person", name="Alice", content="用户1")
        node1.id = node1.generate_id()

        node2 = GraphNode(id="", label="Event", name="Conference", content="会议")
        node2.id = node2.generate_id()

        await adapter.add_node(node1)
        await adapter.add_node(node2)

        edge = GraphEdge(
            source_id=node1.id, target_id=node2.id, relation_type="ATTENDED"
        )
        await adapter.add_edge(edge)

        deleted = await adapter.evict_nodes([node1.id])
        assert deleted == 1

        stats = await adapter.get_stats()
        assert stats["node_count"] == 1


class TestForgettingTaskL3:
    """ForgettingTask L3 淘汰逻辑测试"""

    @pytest.fixture
    def mock_component_manager(self):
        manager = MagicMock()
        return manager

    @pytest.fixture
    def forgetting_task(self, mock_component_manager):
        return ForgettingTask(mock_component_manager)

    @pytest.mark.asyncio
    async def test_evict_l3_nodes_adapter_unavailable(
        self, forgetting_task, mock_component_manager
    ):
        mock_adapter = MagicMock()
        mock_adapter.is_available = False
        mock_component_manager.get_component = MagicMock(return_value=mock_adapter)

        await forgetting_task._evict_l3_nodes()

    @pytest.mark.asyncio
    async def test_evict_l3_nodes_empty_graph(
        self, forgetting_task, mock_component_manager
    ):
        mock_adapter = MagicMock()
        mock_adapter.is_available = True
        mock_adapter.get_all_nodes = AsyncMock(return_value=[])
        mock_component_manager.get_component = MagicMock(return_value=mock_adapter)

        await forgetting_task._evict_l3_nodes()

    @pytest.mark.asyncio
    async def test_should_evict_node_low_score(self, forgetting_task):
        node = MagicMock()
        node.content = "低质量内容"
        node.confidence = 0.1
        node.access_count = 0
        node.last_access_time = datetime.now() - timedelta(days=60)
        node.properties = {}

        result = forgetting_task._should_evict_node(
            node, threshold=0.3, retention_days=30, connected_count=0
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_should_evict_node_high_score(self, forgetting_task):
        node = MagicMock()
        node.content = "重要内容"
        node.confidence = 0.95
        node.access_count = 50
        node.last_access_time = datetime.now()
        node.properties = {}

        result = forgetting_task._should_evict_node(
            node, threshold=0.3, retention_days=30, connected_count=5
        )
        assert result is False
