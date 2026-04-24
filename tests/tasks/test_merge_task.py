"""
MergeTask 记忆合并任务测试

测试记忆合并任务的核心功能：
- Union-Find 连通分量
- 批量检索去重
- LLM 合并
- 采样扫描
- 群聊隔离
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from iris_memory.tasks.merge_task import MergeTask, UnionFind
from iris_memory.l2_memory.models import MemoryEntry, MemorySearchResult


class TestUnionFind:
    """UnionFind 并查集测试"""

    def test_single_element(self):
        uf = UnionFind()
        uf.find("a")
        assert uf.groups() == {}

    def test_pair_union(self):
        uf = UnionFind()
        uf.union("a", "b")
        groups = uf.groups()
        assert len(groups) == 1
        group = list(groups.values())[0]
        assert set(group) == {"a", "b"}

    def test_transitive_union(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("b", "c")
        groups = uf.groups()
        assert len(groups) == 1
        group = list(groups.values())[0]
        assert set(group) == {"a", "b", "c"}

    def test_disjoint_groups(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("c", "d")
        groups = uf.groups()
        assert len(groups) == 2
        all_members = set()
        for g in groups.values():
            all_members.update(g)
        assert all_members == {"a", "b", "c", "d"}

    def test_idempotent_union(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("a", "b")
        groups = uf.groups()
        assert len(groups) == 1
        assert set(list(groups.values())[0]) == {"a", "b"}

    def test_self_union(self):
        uf = UnionFind()
        uf.find("a")
        uf.union("a", "a")
        assert uf.groups() == {}

    def test_large_chain(self):
        uf = UnionFind()
        for i in range(100):
            uf.union(f"m_{i}", f"m_{i + 1}")
        groups = uf.groups()
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 101


class TestMergeTask:
    """MergeTask 测试类"""

    @pytest.fixture
    def mock_component_manager(self):
        manager = Mock()

        l2_adapter = Mock()
        l2_adapter.is_available = True
        l2_adapter.get_all_entries = AsyncMock(return_value=[])
        l2_adapter.retrieve = AsyncMock(return_value=[])
        l2_adapter.batch_retrieve = AsyncMock(return_value=[])
        l2_adapter.add_memory = AsyncMock(return_value="merged_mem_id")
        l2_adapter.delete_entries = AsyncMock(return_value=True)

        llm_manager = Mock()
        llm_manager.is_available = True
        llm_manager.generate = AsyncMock(return_value="合并后的记忆内容")

        def get_component(name):
            if name == "l2_memory":
                return l2_adapter
            elif name == "llm_manager":
                return llm_manager
            return None

        manager.get_component = get_component

        return manager

    @pytest.fixture
    def merge_task(self, mock_component_manager):
        return MergeTask(mock_component_manager)

    @pytest.mark.asyncio
    async def test_execute_disabled(self, merge_task):
        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": False,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
            }.get(key, None)

            await merge_task.execute()

            merge_task._component_manager.get_component(
                "l2_memory"
            ).get_all_entries.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_empty_memories(self, merge_task):
        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
            }.get(key, None)

            await merge_task.execute()

            merge_task._component_manager.get_component(
                "l2_memory"
            ).get_all_entries.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_insufficient_memories(self, merge_task):
        entries = [
            MemoryEntry(
                id="mem_1", content="单条记忆", metadata={"group_id": "group_1"}
            )
        ]

        merge_task._component_manager.get_component(
            "l2_memory"
        ).get_all_entries = AsyncMock(return_value=entries)

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
            }.get(key, None)

            await merge_task.execute()

            merge_task._component_manager.get_component(
                "llm_manager"
            ).generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_l2_unavailable(self, merge_task):
        merge_task._component_manager.get_component("l2_memory").is_available = False

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
            }.get(key, None)

            await merge_task.execute()

            merge_task._component_manager.get_component(
                "l2_memory"
            ).get_all_entries.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_unavailable(self, merge_task):
        entries = [
            MemoryEntry(id="mem_1", content="记忆1", metadata={"group_id": "group_1"}),
            MemoryEntry(id="mem_2", content="记忆2", metadata={"group_id": "group_1"}),
        ]

        merge_task._component_manager.get_component(
            "l2_memory"
        ).get_all_entries = AsyncMock(return_value=entries)
        merge_task._component_manager.get_component("llm_manager").is_available = False

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
            }.get(key, None)

            await merge_task.execute()

            merge_task._component_manager.get_component(
                "llm_manager"
            ).generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_merge_groups_basic(self, merge_task):
        entries = [
            MemoryEntry(
                id="mem_1", content="用户喜欢吃苹果", metadata={"group_id": "group_1"}
            ),
            MemoryEntry(
                id="mem_2",
                content="用户喜欢吃苹果和香蕉",
                metadata={"group_id": "group_1"},
            ),
        ]

        entry_index = {e.id: e for e in entries}

        batch_results = [
            [
                MemorySearchResult(entry=entries[0], score=1.0, distance=0.0),
                MemorySearchResult(entry=entries[1], score=0.9, distance=0.1),
            ],
            [
                MemorySearchResult(entry=entries[1], score=1.0, distance=0.0),
                MemorySearchResult(entry=entries[0], score=0.9, distance=0.1),
            ],
        ]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")
        l2_adapter.batch_retrieve = AsyncMock(return_value=batch_results)

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
                "isolation_config.enable_group_memory_isolation": False,
            }.get(key, None)

            merge_groups = await merge_task._find_merge_groups(
                entries, entry_index, l2_adapter
            )

            assert isinstance(merge_groups, list)
            assert len(merge_groups) >= 1
            all_ids = set()
            for group in merge_groups:
                all_ids.update(group)
            assert "mem_1" in all_ids or "mem_2" in all_ids

    @pytest.mark.asyncio
    async def test_find_merge_groups_transitive(self, merge_task):
        entries = [
            MemoryEntry(
                id="mem_1", content="用户喜欢苹果", metadata={"group_id": "group_1"}
            ),
            MemoryEntry(
                id="mem_2",
                content="用户喜欢苹果和橙子",
                metadata={"group_id": "group_1"},
            ),
            MemoryEntry(
                id="mem_3",
                content="用户喜欢苹果橙子和香蕉",
                metadata={"group_id": "group_1"},
            ),
        ]

        entry_index = {e.id: e for e in entries}

        batch_results = [
            [
                MemorySearchResult(entry=entries[0], score=1.0, distance=0.0),
                MemorySearchResult(entry=entries[1], score=0.9, distance=0.1),
            ],
            [
                MemorySearchResult(entry=entries[1], score=1.0, distance=0.0),
                MemorySearchResult(entry=entries[2], score=0.88, distance=0.12),
            ],
            [
                MemorySearchResult(entry=entries[2], score=1.0, distance=0.0),
            ],
        ]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")
        l2_adapter.batch_retrieve = AsyncMock(return_value=batch_results)

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
                "isolation_config.enable_group_memory_isolation": False,
            }.get(key, None)

            merge_groups = await merge_task._find_merge_groups(
                entries, entry_index, l2_adapter
            )

            assert len(merge_groups) >= 1
            all_ids_in_groups = set()
            for group in merge_groups:
                all_ids_in_groups.update(group)
            assert "mem_1" in all_ids_in_groups
            assert "mem_2" in all_ids_in_groups
            assert "mem_3" in all_ids_in_groups

    @pytest.mark.asyncio
    async def test_merge_memories(self, merge_task):
        llm_manager = merge_task._component_manager.get_component("llm_manager")

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
            }.get(key, None)

            merged = await merge_task._merge_memories(
                "用户喜欢吃苹果", "用户喜欢吃苹果和香蕉", llm_manager
            )

            llm_manager.generate.assert_called_once()
            assert merged is not None

    @pytest.mark.asyncio
    async def test_batch_processing(self, merge_task):
        entries = [
            MemoryEntry(
                id=f"mem_{i}", content=f"记忆{i}", metadata={"group_id": "group_1"}
            )
            for i in range(20)
        ]

        batch_results = [
            [
                MemorySearchResult(entry=entries[0], score=1.0, distance=0.0),
                MemorySearchResult(entry=entries[1], score=0.9, distance=0.1),
            ]
            for _ in range(20)
        ]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")
        l2_adapter.get_all_entries = AsyncMock(return_value=entries)
        l2_adapter.batch_retrieve = AsyncMock(return_value=batch_results)

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 5,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
                "isolation_config.enable_group_memory_isolation": False,
            }.get(key, None)

            await merge_task.execute()

            llm_manager = merge_task._component_manager.get_component("llm_manager")
            assert llm_manager.generate.call_count <= 5

    @pytest.mark.asyncio
    async def test_group_isolation(self, merge_task):
        entries = [
            MemoryEntry(id="mem_1", content="记忆1", metadata={"group_id": "group_1"}),
            MemoryEntry(id="mem_2", content="记忆2", metadata={"group_id": "group_2"}),
        ]

        entry_index = {e.id: e for e in entries}

        batch_results_g1 = [
            [
                MemorySearchResult(entry=entries[0], score=1.0, distance=0.0),
            ]
        ]
        batch_results_g2 = [
            [
                MemorySearchResult(entry=entries[1], score=1.0, distance=0.0),
            ]
        ]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")

        call_count = [0]

        async def mock_batch_retrieve(queries, group_id=None, top_k=10):
            call_count[0] += 1
            if group_id == "group_1":
                return batch_results_g1
            elif group_id == "group_2":
                return batch_results_g2
            return [[] for _ in queries]

        l2_adapter.batch_retrieve = mock_batch_retrieve

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
                "isolation_config.enable_group_memory_isolation": True,
            }.get(key, None)

            merge_groups = await merge_task._find_merge_groups(
                entries, entry_index, l2_adapter
            )

            for group in merge_groups:
                group_entries = [
                    entry_index[eid] for eid in group if eid in entry_index
                ]
                gids = set(e.metadata.get("group_id") for e in group_entries)
                assert len(gids) <= 1

    @pytest.mark.asyncio
    async def test_sampling_with_large_dataset(self, merge_task):
        entries = [
            MemoryEntry(
                id=f"mem_{i}", content=f"记忆{i}", metadata={"group_id": "group_1"}
            )
            for i in range(2000)
        ]

        entry_index = {e.id: e for e in entries}

        batch_results = [[] for _ in range(50)]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")
        l2_adapter.batch_retrieve = AsyncMock(return_value=batch_results)

        merge_task._scan_budget = 100

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 100,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 5,
                "isolation_config.enable_group_memory_isolation": False,
            }.get(key, None)

            await merge_task._find_merge_groups(entries, entry_index, l2_adapter)

            assert l2_adapter.batch_retrieve.call_count <= 4

    @pytest.mark.asyncio
    async def test_merge_group_pair(self, merge_task):
        entries = [
            MemoryEntry(
                id="mem_1",
                content="用户喜欢吃苹果",
                metadata={"group_id": "group_1", "confidence": 0.7},
            ),
            MemoryEntry(
                id="mem_2",
                content="用户喜欢吃苹果和香蕉",
                metadata={"group_id": "group_1", "confidence": 0.8},
            ),
        ]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")
        llm_manager = merge_task._component_manager.get_component("llm_manager")

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
            }.get(key, None)

            merged_count, deleted_count = await merge_task._merge_group(
                entries, l2_adapter, llm_manager
            )

            assert merged_count == 1
            assert deleted_count == 2
            l2_adapter.delete_entries.assert_called_once_with(["mem_1", "mem_2"])
            l2_adapter.add_memory.assert_called_once()
            call_args = l2_adapter.add_memory.call_args
            assert call_args[1]["skip_dedup"] is True
            assert call_args[1]["metadata"]["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_merge_group_triple(self, merge_task):
        entries = [
            MemoryEntry(
                id="mem_1",
                content="用户喜欢苹果",
                metadata={"group_id": "group_1", "confidence": 0.7},
            ),
            MemoryEntry(
                id="mem_2",
                content="用户喜欢苹果和橙子",
                metadata={"group_id": "group_1", "confidence": 0.8},
            ),
            MemoryEntry(
                id="mem_3",
                content="用户喜欢苹果橙子和香蕉",
                metadata={"group_id": "group_1", "confidence": 0.6},
            ),
        ]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")
        llm_manager = merge_task._component_manager.get_component("llm_manager")

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
            }.get(key, None)

            merged_count, deleted_count = await merge_task._merge_group(
                entries, l2_adapter, llm_manager
            )

            assert merged_count == 1
            assert deleted_count == 3
            assert llm_manager.generate.call_count == 2

    @pytest.mark.asyncio
    async def test_max_group_size_limit(self, merge_task):
        entries = [
            MemoryEntry(
                id=f"mem_{i}", content=f"记忆{i}", metadata={"group_id": "group_1"}
            )
            for i in range(10)
        ]

        entry_index = {e.id: e for e in entries}

        batch_results = [
            [
                MemorySearchResult(entry=entries[j], score=0.95, distance=0.05)
                for j in range(10)
            ]
            for _ in range(10)
        ]

        l2_adapter = merge_task._component_manager.get_component("l2_memory")
        l2_adapter.batch_retrieve = AsyncMock(return_value=batch_results)

        merge_task._max_group_size = 3

        with patch("iris_memory.tasks.merge_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key: {
                "scheduled_tasks.enable_merging": True,
                "merge_similarity_threshold": 0.85,
                "merge_batch_size": 10,
                "merge_scan_budget": 500,
                "merge_query_batch_size": 50,
                "merge_max_group_size": 3,
                "isolation_config.enable_group_memory_isolation": False,
            }.get(key, None)

            merge_groups = await merge_task._find_merge_groups(
                entries, entry_index, l2_adapter
            )

            for group in merge_groups:
                assert len(group) <= 3
