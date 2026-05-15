"""
Iris Chat Memory - L3 知识图谱提取任务

定期检测未处理的 L2 记忆，按群聊/用户分组后批量聚合提取实体，
将实体和关系写入 L3 知识图谱。

Features:
    - 按群聊/用户分组批量聚合提取（而非逐条提取）
    - 空提取结果不标记为已处理
    - 批量处理优化
"""

from typing import TYPE_CHECKING, List, Optional
from collections import defaultdict

from iris_memory.core import get_logger
from iris_memory.config import get_config
from iris_memory.l2_memory.adapter import L2MemoryAdapter
from iris_memory.l3_kg.adapter import L3KGAdapter
from iris_memory.llm.manager import LLMManager

if TYPE_CHECKING:
    from iris_memory.core import ComponentManager

logger = get_logger("tasks.kg_extraction")


class KGExtractionTask:
    """L3 知识图谱提取任务

    定期检测未处理的 L2 记忆数量，达到阈值时按群聊/用户分组后
    批量聚合提取实体。

    流程：
    1. 检测未处理记忆数量
    2. 数量 >= 阈值时执行提取
    3. 按群聊分组，每组记忆合并后调用一次 LLM 提取
    4. 写入 L3 知识图谱（自动合并已有节点）
    5. 仅对有效提取的记忆标记为已处理

    Attributes:
        _component_manager: 组件管理器引用
    """

    def __init__(self, component_manager: "ComponentManager"):
        self._component_manager = component_manager

    async def execute(self) -> None:
        """执行提取任务"""
        config = get_config()

        l3_kg_enable = config.get("l3_kg.enable")
        if not l3_kg_enable:
            logger.debug("L3 知识图谱未启用，跳过提取任务")
            return

        l2_adapter = self._get_l2_adapter()
        if not l2_adapter:
            logger.debug("L2 记忆库不可用，跳过提取任务")
            return

        kg_adapter = self._get_kg_adapter()
        if not kg_adapter:
            logger.debug("L3 知识图谱不可用，跳过提取任务")
            return

        llm_manager = self._get_llm_manager()
        if not llm_manager:
            logger.debug("LLM Manager 不可用，跳过提取任务")
            return

        min_unprocessed = config.get("kg_extraction_min_unprocessed")
        unprocessed_count = await l2_adapter.get_unprocessed_count()

        if unprocessed_count < min_unprocessed:
            logger.debug(
                f"未处理记忆数量 {unprocessed_count} < {min_unprocessed}，跳过提取"
            )
            return

        logger.info(f"开始 L3 知识图谱提取，未处理记忆数：{unprocessed_count}")

        batch_size = config.get("kg_extraction_batch_size")

        unprocessed_memories = await l2_adapter.get_unprocessed_memories(
            limit=batch_size
        )

        if not unprocessed_memories:
            logger.debug("没有未处理的记忆")
            return

        groups = self._group_memories(unprocessed_memories)

        logger.info(
            f"按群聊分组：{len(groups)} 个组，共 {len(unprocessed_memories)} 条记忆"
        )

        from iris_memory.l3_kg import EntityExtractor

        extractor = EntityExtractor(llm_manager)

        all_processed_ids: List[str] = []

        for group_key, memories in groups.items():
            try:
                context = {"group_id": memories[0].group_id}

                result = await extractor.extract_from_memories(memories, context)

                if result.nodes or result.edges:
                    node_count = 0
                    for node in result.nodes:
                        success = await kg_adapter.add_node(node)
                        if success:
                            node_count += 1

                    edge_count = 0
                    for edge in result.edges:
                        success = await kg_adapter.add_edge(edge)
                        if success:
                            edge_count += 1

                    logger.info(
                        f"群组 [{group_key}] 提取完成："
                        f"{node_count}/{len(result.nodes)} 个节点，"
                        f"{edge_count}/{len(result.edges)} 条边"
                    )

                    for mem in memories:
                        all_processed_ids.append(mem.id)
                else:
                    logger.debug(f"群组 [{group_key}] 提取结果为空，不标记为已处理")

            except Exception as e:
                logger.error(f"处理群组 [{group_key}] 失败：{e}", exc_info=True)

        if all_processed_ids:
            await l2_adapter.mark_memories_processed(all_processed_ids)
            logger.info(f"L3 提取任务完成，已处理 {len(all_processed_ids)} 条记忆")

    def _group_memories(self, memories: list) -> dict[str, list]:
        """按群聊 ID 分组记忆

        同一群聊的记忆聚合后一起提取，让 LLM 能看到跨记忆的关联。

        Args:
            memories: 未处理的记忆列表

        Returns:
            分组字典 {group_key: [memories]}
        """
        groups: dict[str, list] = defaultdict(list)

        for mem in memories:
            group_key = mem.group_id or "_no_group"
            groups[group_key].append(mem)

        return dict(groups)

    def _get_l2_adapter(self) -> Optional["L2MemoryAdapter"]:
        adapter = self._component_manager.get_component("l2_memory", L2MemoryAdapter)
        if adapter and adapter.is_available:
            return adapter
        return None

    def _get_kg_adapter(self) -> Optional["L3KGAdapter"]:
        adapter = self._component_manager.get_component("l3_kg", L3KGAdapter)
        if adapter and adapter.is_available:
            return adapter
        return None

    def _get_llm_manager(self) -> Optional["LLMManager"]:
        manager = self._component_manager.get_component("llm_manager", LLMManager)
        if manager and manager.is_available:
            return manager
        return None
