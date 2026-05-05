"""
ForgettingTask 遗忘清洗任务测试
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from iris_memory.tasks.forgetting_task import ForgettingTask
from iris_memory.l2_memory.models import MemoryEntry


class TestForgettingTask:
    @pytest.fixture
    def mock_component_manager(self):
        manager = Mock()

        l2_adapter = Mock()
        l2_adapter.is_available = True
        l2_adapter.get_all_entries = AsyncMock(return_value=[])
        l2_adapter.evict_memories = AsyncMock(return_value=0)
        l2_adapter.update_metadata = AsyncMock()

        l3_adapter = Mock()
        l3_adapter.is_available = True
        l3_adapter.get_all_nodes = AsyncMock(return_value=[])
        l3_adapter.evict_nodes = AsyncMock(return_value=0)
        l3_adapter.merge_duplicate_nodes = AsyncMock(return_value=(0, 0))
        l3_adapter.get_node_connection_counts = AsyncMock(return_value={})

        def get_component(name):
            if name == "l2_memory":
                return l2_adapter
            elif name == "l3_kg":
                return l3_adapter
            return None

        manager.get_component = get_component

        return manager

    @pytest.fixture
    def forgetting_task(self, mock_component_manager):
        return ForgettingTask(mock_component_manager)

    @pytest.mark.asyncio
    async def test_execute_disabled(self, forgetting_task):
        with patch("iris_memory.tasks.forgetting_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key, default=None: {
                "scheduled_tasks.enable_forgetting": False,
                "eviction_batch_size": 100,
            }.get(key, default)

            await forgetting_task.execute()

            l2 = forgetting_task._component_manager.get_component("l2_memory")
            l2.evict_memories.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_l2_empty(self, forgetting_task):
        with (
            patch("iris_memory.tasks.forgetting_task.get_config") as mock_config,
            patch("iris_memory.utils.forgetting.get_config") as mock_forgetting_config,
        ):
            config_vals = {
                "scheduled_tasks.enable_forgetting": True,
                "eviction_batch_size": 100,
                "forgetting_threshold": 0.3,
                "forgetting_lambda": 0.1,
                "node_confidence_threshold": 0.3,
                "forgetting_threshold_kg": 0.2,
                "kg_retention_days": 30,
            }
            mock_config.return_value.get.side_effect = lambda key, default=None: (
                config_vals.get(key, default)
            )
            mock_forgetting_config.return_value.get.side_effect = (
                lambda key, default=None: config_vals.get(key, default)
            )

            await forgetting_task.execute()

            l2 = forgetting_task._component_manager.get_component("l2_memory")
            l2.get_all_entries.assert_called()

    @pytest.mark.asyncio
    async def test_execute_l2_with_memories(self, forgetting_task):
        old_time = (datetime.now() - timedelta(days=60)).isoformat()
        recent_time = datetime.now().isoformat()

        entries = [
            MemoryEntry(
                id="mem_old_1",
                content="旧记忆1",
                metadata={
                    "last_access_time": old_time,
                    "access_count": 0,
                    "confidence": 0.1,
                },
            ),
            MemoryEntry(
                id="mem_recent",
                content="近期记忆",
                metadata={
                    "last_access_time": recent_time,
                    "access_count": 10,
                    "confidence": 0.9,
                },
            ),
            MemoryEntry(
                id="mem_old_2",
                content="旧记忆2",
                metadata={
                    "last_access_time": old_time,
                    "access_count": 0,
                    "confidence": 0.1,
                },
            ),
        ]

        forgetting_task._component_manager.get_component(
            "l2_memory"
        ).get_all_entries = AsyncMock(return_value=entries)

        config_vals = {
            "scheduled_tasks.enable_forgetting": True,
            "eviction_batch_size": 100,
            "forgetting_threshold": 0.3,
            "forgetting_lambda": 0.1,
            "node_confidence_threshold": 0.3,
            "forgetting_threshold_kg": 0.2,
            "kg_retention_days": 30,
        }

        with (
            patch("iris_memory.tasks.forgetting_task.get_config") as mock_config,
            patch("iris_memory.utils.forgetting.get_config") as mock_forgetting_config,
            patch("iris_memory.utils.forgetting.should_evict", return_value=True),
            patch(
                "iris_memory.utils.forgetting.calculate_forgetting_score",
                return_value=0.05,
            ),
        ):
            mock_config.return_value.get.side_effect = lambda key, default=None: (
                config_vals.get(key, default)
            )
            mock_forgetting_config.return_value.get.side_effect = (
                lambda key, default=None: config_vals.get(key, default)
            )

            await forgetting_task.execute()

            l2_adapter = forgetting_task._component_manager.get_component("l2_memory")
            l2_adapter.evict_memories.assert_called()

    @pytest.mark.asyncio
    async def test_execute_l3_empty(self, forgetting_task):
        config_vals = {
            "scheduled_tasks.enable_forgetting": True,
            "eviction_batch_size": 100,
            "forgetting_threshold": 0.3,
            "forgetting_lambda": 0.1,
            "node_confidence_threshold": 0.3,
            "forgetting_threshold_kg": 0.2,
            "kg_retention_days": 30,
        }

        with (
            patch("iris_memory.tasks.forgetting_task.get_config") as mock_config,
            patch("iris_memory.utils.forgetting.get_config") as mock_forgetting_config,
        ):
            mock_config.return_value.get.side_effect = lambda key, default=None: (
                config_vals.get(key, default)
            )
            mock_forgetting_config.return_value.get.side_effect = (
                lambda key, default=None: config_vals.get(key, default)
            )

            await forgetting_task.execute()

            l3 = forgetting_task._component_manager.get_component("l3_kg")
            l3.get_all_nodes.assert_called()

    @pytest.mark.asyncio
    async def test_l2_unavailable(self, forgetting_task):
        forgetting_task._component_manager.get_component(
            "l2_memory"
        ).is_available = False

        with patch("iris_memory.tasks.forgetting_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key, default=None: {
                "scheduled_tasks.enable_forgetting": True,
                "eviction_batch_size": 100,
            }.get(key, default)

            await forgetting_task.execute()

            l2 = forgetting_task._component_manager.get_component("l2_memory")
            l2.evict_memories.assert_not_called()

    @pytest.mark.asyncio
    async def test_l3_unavailable(self, forgetting_task):
        forgetting_task._component_manager.get_component("l3_kg").is_available = False

        with patch("iris_memory.tasks.forgetting_task.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key, default=None: {
                "scheduled_tasks.enable_forgetting": True,
                "eviction_batch_size": 100,
            }.get(key, default)

            await forgetting_task.execute()

            l3 = forgetting_task._component_manager.get_component("l3_kg")
            l3.evict_nodes.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_processing(self, forgetting_task):
        old_time = (datetime.now() - timedelta(days=60)).isoformat()
        entries = [
            MemoryEntry(
                id=f"mem_{i}",
                content=f"记忆{i}",
                metadata={
                    "last_access_time": old_time,
                    "access_count": 0,
                    "confidence": 0.1,
                },
            )
            for i in range(150)
        ]

        forgetting_task._component_manager.get_component(
            "l2_memory"
        ).get_all_entries = AsyncMock(return_value=entries)

        config_vals = {
            "scheduled_tasks.enable_forgetting": True,
            "eviction_batch_size": 50,
            "forgetting_threshold": 0.3,
            "forgetting_lambda": 0.1,
            "node_confidence_threshold": 0.3,
            "forgetting_threshold_kg": 0.2,
            "kg_retention_days": 30,
        }

        with (
            patch("iris_memory.tasks.forgetting_task.get_config") as mock_config,
            patch("iris_memory.utils.forgetting.get_config") as mock_forgetting_config,
            patch("iris_memory.utils.forgetting.should_evict", return_value=True),
            patch(
                "iris_memory.utils.forgetting.calculate_forgetting_score",
                return_value=0.05,
            ),
        ):
            mock_config.return_value.get.side_effect = lambda key, default=None: (
                config_vals.get(key, default)
            )
            mock_forgetting_config.return_value.get.side_effect = (
                lambda key, default=None: config_vals.get(key, default)
            )

            await forgetting_task.execute()

            l2_adapter = forgetting_task._component_manager.get_component("l2_memory")
            assert l2_adapter.evict_memories.call_count >= 2
