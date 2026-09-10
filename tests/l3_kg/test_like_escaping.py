"""L3 搜索路径 LIKE 通配符转义回归测试

历史问题：search_nodes / search_edges / properties 反查直接把关键词拼进
``%{keyword}%`` 模式，用户关键词中的 % / _ 会作为通配符扩大匹配面
（如 "%%%" 全表命中）。修复后统一 escape_like + ESCAPE 子句按字面匹配。
"""

import pytest
import pytest_asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

from iris_memory.config import init_config
from iris_memory.l3_kg import GraphEdge, GraphNode, L3KGAdapter


class TestSearchLikeEscaping:
    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest_asyncio.fixture
    async def adapter(self, temp_dir):
        astrbot_config = Mock()
        astrbot_config.__getitem__ = Mock(return_value={"enable": True})
        astrbot_config.__contains__ = Mock(return_value=True)

        init_config(astrbot_config, temp_dir)

        adapter = L3KGAdapter()
        await adapter.initialize()
        yield adapter
        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_percent_literal_only(self, adapter):
        """含 % 的关键词只匹配字面含 % 的节点，不再当作通配符"""
        node_plain = GraphNode(
            id="", label="Event", name="100 dollars off", content="打折活动"
        )
        node_plain.id = node_plain.generate_id()
        node_literal = GraphNode(
            id="", label="Event", name="100%_off", content="折扣信息"
        )
        node_literal.id = node_literal.generate_id()
        await adapter.add_node(node_plain)
        await adapter.add_node(node_literal)

        results = await adapter.search_nodes("100%")
        names = [r["name"] for r in results]
        assert names == ["100%_off"]

    @pytest.mark.asyncio
    async def test_wildcard_only_keyword_matches_nothing(self, adapter):
        """纯通配符关键词不再全表命中"""
        node = GraphNode(id="", label="Event", name="anything", content="内容")
        node.id = node.generate_id()
        await adapter.add_node(node)

        assert await adapter.search_nodes("%%") == []
        assert await adapter.search_nodes("__") == []

    @pytest.mark.asyncio
    async def test_underscore_literal_only(self, adapter):
        node_plain = GraphNode(id="", label="Event", name="aXb", content="c")
        node_plain.id = node_plain.generate_id()
        node_literal = GraphNode(id="", label="Event", name="a_b", content="c")
        node_literal.id = node_literal.generate_id()
        await adapter.add_node(node_plain)
        await adapter.add_node(node_literal)

        results = await adapter.search_nodes("a_b")
        names = [r["name"] for r in results]
        assert names == ["a_b"]

    @pytest.mark.asyncio
    async def test_normal_keyword_unaffected(self, adapter):
        """不含通配符的普通关键词行为不变"""
        node = GraphNode(id="", label="Person", name="Alice", content="engineer")
        node.id = node.generate_id()
        await adapter.add_node(node)

        results = await adapter.search_nodes("lice")
        assert [r["name"] for r in results] == ["Alice"]

    @pytest.mark.asyncio
    async def test_search_edges_escapes_keyword(self, adapter):
        """边搜索同样按字面匹配 relation_type"""
        src = GraphNode(id="", label="Person", name="A", content="a")
        src.id = src.generate_id()
        tgt = GraphNode(id="", label="Person", name="B", content="b")
        tgt.id = tgt.generate_id()
        await adapter.add_node(src)
        await adapter.add_node(tgt)
        edge = GraphEdge(source_id=src.id, target_id=tgt.id, relation_type="WORKS_WITH")
        await adapter.add_edge(edge)

        assert await adapter.search_edges("%") == []
        results = await adapter.search_edges("WORKS")
        assert len(results) == 1
        assert results[0]["relation"] == "WORKS_WITH"
