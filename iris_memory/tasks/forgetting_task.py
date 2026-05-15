"""
Iris Chat Memory - 遗忘清洗任务

定期计算记忆权重评分，批量清理评分低于阈值且超过保留期的条目。

Features:
    - L2 记忆库遗忘清洗
    - L3 知识图谱节点淘汰
    - LLM 最终兜底确认（可选）
    - 低置信度数据标记
    - 批量处理优化
    - 写锁保护
"""

from typing import TYPE_CHECKING, List
from datetime import datetime

from iris_memory.core import get_logger
from iris_memory.config import get_config
from iris_memory.l2_memory.adapter import L2MemoryAdapter
from iris_memory.l3_kg.adapter import L3KGAdapter
from iris_memory.llm.manager import LLMManager
from iris_memory.utils.forgetting import (
    calculate_forgetting_score,
    should_evict,
    calculate_kg_forgetting_score,
    should_evict_kg_node,
)

if TYPE_CHECKING:
    from iris_memory.core import ComponentManager

logger = get_logger("tasks.forgetting")


class ForgettingTask:
    """遗忘清洗任务

    定期执行遗忘清洗，清理过期和低质量记忆。

    Attributes:
        _component_manager: 组件管理器引用
        _batch_size: 批处理大小

    Examples:
        >>> task = ForgettingTask(component_manager)
        >>> await task.execute()
    """

    def __init__(self, component_manager: "ComponentManager"):
        """初始化遗忘清洗任务

        Args:
            component_manager: 组件管理器实例
        """
        self._component_manager = component_manager
        self._batch_size = 100

    async def execute(self) -> None:
        """执行遗忘清洗任务

        依次执行 L2 和 L3 的遗忘清洗。
        """
        config = get_config()
        self._batch_size = config.get("eviction_batch_size")

        if not config.get("scheduled_tasks.enable_forgetting"):
            logger.debug("遗忘清洗任务未启用，跳过")
            return

        await self._mark_low_confidence_l2()
        await self._evict_l2_memories()
        await self._merge_l3_duplicates()
        await self._mark_low_confidence_l3()
        await self._evict_l3_nodes()

    # =========================================================================
    # L2 遗忘清洗
    # =========================================================================

    async def _evict_l2_memories(self) -> None:
        """L2 记忆库遗忘清洗

        获取所有记忆，计算遗忘评分，淘汰低分记忆。
        启用 LLM 兜底确认时，对评分极低的记忆进行二次确认。
        """

        # 获取 L2 适配器
        l2_adapter = self._component_manager.get_component("l2_memory", L2MemoryAdapter)
        if not l2_adapter or not l2_adapter.is_available:
            logger.debug("L2 记忆库不可用，跳过遗忘清洗")
            return

        try:
            # 获取所有记忆条目
            entries = await l2_adapter.get_all_entries()

            if not entries:
                logger.debug("L2 记忆库为空，无需清洗")
                return

            logger.info(f"开始评估 {len(entries)} 条 L2 记忆...")

            # 计算遗忘评分并筛选待淘汰记忆
            to_evict_with_score = []

            for entry in entries:
                # 检查是否应该淘汰
                if should_evict(entry):
                    score = calculate_forgetting_score(entry)
                    to_evict_with_score.append((entry.id, entry.content, score))

            if not to_evict_with_score:
                logger.debug("L2 无需淘汰的记忆")
                return

            # LLM 兜底确认
            confirmed_ids = await self._llm_confirm_eviction(
                to_evict_with_score, source="l2"
            )

            # 批量删除确认淘汰的记忆
            evicted_count = 0
            batch = []
            for entry_id in confirmed_ids:
                batch.append(entry_id)
                if len(batch) >= self._batch_size:
                    await l2_adapter.evict_memories(batch)
                    evicted_count += len(batch)
                    batch = []

            if batch:
                await l2_adapter.evict_memories(batch)
                evicted_count += len(batch)

            logger.info(f"L2 遗忘清洗完成，共淘汰 {evicted_count} 条记忆")

        except Exception as e:
            logger.error(f"L2 遗忘清洗失败：{e}", exc_info=True)

    # =========================================================================
    # L3 图谱去重合并
    # =========================================================================

    async def _merge_l3_duplicates(self) -> None:
        """L3 知识图谱重复节点合并

        查找同名同 label 的重复节点并合并。
        """

        l3_adapter = self._component_manager.get_component("l3_kg", L3KGAdapter)
        if not l3_adapter or not l3_adapter.is_available:
            logger.debug("L3 知识图谱不可用，跳过去重合并")
            return

        try:
            merged, deleted = await l3_adapter.merge_duplicate_nodes()
            if merged > 0:
                logger.info(
                    f"L3 去重合并完成：合并 {merged} 组，删除 {deleted} 个重复节点"
                )
        except Exception as e:
            logger.error(f"L3 去重合并失败：{e}", exc_info=True)

    # =========================================================================
    # L3 图谱淘汰
    # =========================================================================

    async def _evict_l3_nodes(self) -> None:
        """L3 知识图谱节点淘汰

        使用 L3 专用遗忘评分公式，结构重要性（连接度）和验证度（来源记忆数）
        权重远高于 L2。枢纽节点和被多次验证的节点永不淘汰。
        """
        l3_adapter = self._component_manager.get_component("l3_kg", L3KGAdapter)
        if not l3_adapter or not l3_adapter.is_available:
            logger.debug("L3 知识图谱不可用，跳过淘汰")
            return

        try:
            nodes = await l3_adapter.get_all_nodes()

            if not nodes:
                logger.debug("L3 知识图谱为空，无需淘汰")
                return

            logger.info(f"开始评估 {len(nodes)} 个 L3 节点...")

            connection_counts = await l3_adapter.get_node_connection_counts()

            config = get_config()
            threshold_kg = float(config.get("forgetting_threshold_kg", 0.3))
            retention_days = int(config.get("kg_retention_days", 30))

            to_evict_with_score = []

            for node_dict in nodes:
                node_id = node_dict["id"]
                confidence = node_dict.get("confidence", 1.0)
                last_access_time = node_dict.get("last_access_time")
                access_count = node_dict.get("access_count", 0)
                properties = node_dict.get("properties", {})
                connected_count = connection_counts.get(node_id, 0)

                source_memory_ids_str = properties.get("source_memory_ids", "")
                source_memory_count = len(
                    [x for x in source_memory_ids_str.split(",") if x.strip()]
                )

                last_access_str = None
                if last_access_time:
                    if isinstance(last_access_time, datetime):
                        last_access_str = last_access_time.isoformat()
                    else:
                        last_access_str = str(last_access_time)

                if should_evict_kg_node(
                    last_access_time=last_access_str,
                    access_count=access_count,
                    confidence=confidence,
                    connected_count=connected_count,
                    source_memory_count=source_memory_count,
                    threshold=threshold_kg,
                    retention_days=retention_days,
                ):
                    score = calculate_kg_forgetting_score(
                        last_access_time=last_access_str,
                        access_count=access_count,
                        confidence=confidence,
                        connected_count=connected_count,
                        source_memory_count=source_memory_count,
                    )
                    to_evict_with_score.append(
                        (node_id, node_dict.get("content", ""), score)
                    )

            if not to_evict_with_score:
                logger.debug("L3 无需淘汰的节点")
                return

            confirmed_ids = await self._llm_confirm_eviction(
                to_evict_with_score, source="l3"
            )

            evicted_count = 0
            batch = []
            for node_id in confirmed_ids:
                batch.append(node_id)
                if len(batch) >= self._batch_size:
                    await l3_adapter.evict_nodes(batch)
                    evicted_count += len(batch)
                    batch = []

            if batch:
                await l3_adapter.evict_nodes(batch)
                evicted_count += len(batch)

            logger.info(f"L3 图谱淘汰完成，共淘汰 {evicted_count} 个节点")

        except Exception as e:
            logger.error(f"L3 图谱淘汰失败：{e}", exc_info=True)

    # =========================================================================
    # LLM 最终兜底确认
    # =========================================================================

    async def _llm_confirm_eviction(
        self, entries: List[tuple], source: str = "l2"
    ) -> List[str]:
        """使用 LLM 最终兜底确认是否遗忘

        仅在评分极低时触发 LLM 确认，避免误删有价值记忆。

        Args:
            entries: 待确认的条目列表，每项为 (id, content, score)
            source: 来源标识（"l2" 或 "l3"）

        Returns:
            经 LLM 确认后仍应淘汰的 ID 列表
        """
        config = get_config()
        if not config.get("forgetting_llm_confirm_enable"):
            return [e[0] for e in entries]

        llm_manager = self._component_manager.get_component("llm_manager", LLMManager)
        if not llm_manager or not llm_manager.is_available:
            logger.warning("LLM Manager 不可用，跳过兜底确认，直接淘汰")
            return [e[0] for e in entries]

        confirm_threshold = config.get("forgetting_llm_confirm_threshold")
        provider = config.get("forgetting_llm_confirm_provider") or None

        confirmed = []
        for entry_id, content, score in entries:
            if score >= confirm_threshold:
                confirmed.append(entry_id)
                continue

            try:
                prompt = (
                    "以下是一条记忆内容，系统评估其重要性极低，建议遗忘。\n"
                    "请判断该记忆是否确实没有保留价值。\n"
                    '回复 "FORGET" 表示确认遗忘，回复 "KEEP" 表示应保留。\n\n'
                    f"记忆内容：{content[:500]}\n\n"
                    "请只回复 FORGET 或 KEEP："
                )

                response = await llm_manager.generate_direct(
                    prompt=prompt, module="forgetting_confirm", provider_id=provider
                )

                decision = response.strip().upper() if response else "FORGET"

                if "KEEP" in decision:
                    logger.info(f"LLM 兜底确认保留记忆：{entry_id}（评分 {score:.3f}）")
                else:
                    confirmed.append(entry_id)

            except Exception as e:
                logger.warning(f"LLM 兜底确认失败：{e}，默认淘汰 {entry_id}")
                confirmed.append(entry_id)

        return confirmed

    # =========================================================================
    # 低置信度数据标记
    # =========================================================================

    async def _mark_low_confidence_l2(self) -> None:
        """自动检测并标记 L2 记忆库中的低置信度数据

        将置信度低于阈值的记忆标记为 low_confidence=True，
        但不删除，仅作为后续遗忘评估的参考。
        """

        l2_adapter = self._component_manager.get_component("l2_memory", L2MemoryAdapter)
        if not l2_adapter or not l2_adapter.is_available:
            return

        try:
            entries = await l2_adapter.get_all_entries()
            if not entries:
                return

            config = get_config()
            confidence_threshold = config.get("node_confidence_threshold")

            marked_count = 0
            for entry in entries:
                if entry.confidence < confidence_threshold:
                    if not entry.metadata.get("low_confidence"):
                        entry.metadata["low_confidence"] = True
                        await l2_adapter.update_metadata(entry.id, entry.metadata)
                        marked_count += 1

            if marked_count > 0:
                logger.info(f"L2 低置信度标记完成：{marked_count} 条记忆被标记")

        except Exception as e:
            logger.error(f"L2 低置信度标记失败：{e}", exc_info=True)

    async def _mark_low_confidence_l3(self) -> None:
        """自动检测并标记 L3 知识图谱中的低置信度数据

        将置信度低于阈值的节点标记为 properties.low_confidence=True，
        但不删除，仅作为后续遗忘评估的参考。
        """

        l3_adapter = self._component_manager.get_component("l3_kg", L3KGAdapter)
        if not l3_adapter or not l3_adapter.is_available:
            return

        try:
            nodes = await l3_adapter.get_all_nodes()
            if not nodes:
                return

            config = get_config()
            confidence_threshold = config.get("node_confidence_threshold")

            marked_count = 0
            for node_dict in nodes:
                confidence = node_dict.get("confidence", 1.0)
                properties = node_dict.get("properties", {})

                if confidence < confidence_threshold:
                    if not properties.get("low_confidence"):
                        try:
                            node_id = node_dict["id"]
                            properties["low_confidence"] = True
                            l3_adapter._conn.execute(
                                "MATCH (e:Entity {id: $id}) SET e.properties = $props",
                                {"id": node_id, "props": properties},
                            )
                            marked_count += 1
                        except Exception as e:
                            logger.debug(f"标记节点 {node_dict.get('id')} 失败：{e}")

            if marked_count > 0:
                logger.info(f"L3 低置信度标记完成：{marked_count} 个节点被标记")

        except Exception as e:
            logger.error(f"L3 低置信度标记失败：{e}", exc_info=True)
