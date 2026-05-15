"""
Iris Chat Memory - 记忆合并任务

定期检索相似记忆并使用 LLM 合并碎片化记忆。

Features:
    - 批量向量检索（ChromaDB batch query）
    - 并查集连通分量（传递性合并）
    - 采样扫描预算（大数据量优化）
    - LLM 智能合并
"""

import random
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, cast

from iris_memory.core import get_logger
from iris_memory.config import get_config
from iris_memory.llm.manager import LLMManager
from iris_memory.l2_memory.adapter import L2MemoryAdapter

if TYPE_CHECKING:
    from iris_memory.core import ComponentManager
    from iris_memory.l2_memory.models import MemoryEntry, MemorySearchResult

logger = get_logger("tasks.merge")


class UnionFind:
    """并查集数据结构

    用于构建相似记忆的连通分量，支持传递性合并：
    若 A~B 且 B~C，则 A、B、C 属于同一合并组。

    使用路径压缩和按秩合并优化，均摊时间复杂度 O(α(n)) ≈ O(1)。
    """

    __slots__ = ("_parent", "_rank")

    def __init__(self):
        self._parent: Dict[str, str] = {}
        self._rank: Dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            next_x = self._parent[x]
            self._parent[x] = root
            x = next_x
        return root

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def groups(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for x in self._parent:
            root = self.find(x)
            if root not in result:
                result[root] = []
            result[root].append(x)
        return {k: v for k, v in result.items() if len(v) > 1}


class MergeTask:
    """记忆合并任务

    定期合并碎片化的相似记忆，提高记忆质量。

    大数据量优化策略：
    1. 批量向量检索：利用 ChromaDB batch query 一次查询多条记忆
    2. 采样扫描：每次仅扫描有限数量记忆，多轮覆盖全量
    3. 并查集分组：传递性相似（A~B~C）归为同一合并组
    4. O(1) 条目查找：ID→Entry 字典替代线性扫描
    """

    def __init__(self, component_manager: "ComponentManager"):
        self._component_manager = component_manager
        self._similarity_threshold = 0.85
        self._batch_size = 10
        self._scan_budget = 500
        self._query_batch_size = 50
        self._max_group_size = 5

    async def execute(self) -> None:
        config = get_config()
        self._similarity_threshold = cast(
            float, config.get("merge_similarity_threshold")
        )
        self._batch_size = cast(int, config.get("merge_batch_size"))
        self._scan_budget = cast(int, config.get("merge_scan_budget"))
        self._query_batch_size = cast(int, config.get("merge_query_batch_size"))
        self._max_group_size = cast(int, config.get("merge_max_group_size"))

        if not config.get("scheduled_tasks.enable_merging"):
            logger.debug("记忆合并任务未启用，跳过")
            return

        await self._merge_similar_memories()

    # =========================================================================
    # 记忆合并
    # =========================================================================

    async def _merge_similar_memories(self) -> None:
        l2_adapter = self._component_manager.get_component("l2_memory", L2MemoryAdapter)
        if not l2_adapter or not l2_adapter.is_available:
            logger.debug("L2 记忆库不可用，跳过合并")
            return

        llm_manager = self._component_manager.get_component("llm_manager", LLMManager)
        if not llm_manager or not llm_manager.is_available:
            logger.warning("LLMManager 不可用，无法合并记忆")
            return

        try:
            entries = await l2_adapter.get_all_entries()

            if len(entries) < 2:
                logger.debug("记忆数量不足，无需合并")
                return

            entry_index: Dict[str, "MemoryEntry"] = {e.id: e for e in entries}

            logger.info(f"开始分析 {len(entries)} 条记忆的相似度...")

            merge_groups = await self._find_merge_groups(
                entries, entry_index, l2_adapter
            )

            if not merge_groups:
                logger.debug("未发现相似记忆，无需合并")
                return

            logger.info(f"发现 {len(merge_groups)} 组相似记忆")

            merged_count = 0
            deleted_count = 0

            for group_ids in merge_groups[: self._batch_size]:
                group_entries = [
                    entry_index[eid] for eid in group_ids if eid in entry_index
                ]
                if len(group_entries) < 2:
                    continue

                try:
                    m, d = await self._merge_group(
                        group_entries, l2_adapter, llm_manager
                    )
                    merged_count += m
                    deleted_count += d
                except Exception as e:
                    logger.error(f"合并记忆组失败：{e}", exc_info=True)

            logger.info(
                f"记忆合并完成，共合并 {merged_count} 组记忆，删除 {deleted_count} 条旧记忆"
            )

        except Exception as e:
            logger.error(f"记忆合并任务失败：{e}", exc_info=True)

    # =========================================================================
    # 相似记忆检测
    # =========================================================================

    async def _find_merge_groups(
        self,
        entries: List["MemoryEntry"],
        entry_index: Dict[str, "MemoryEntry"],
        adapter: "L2MemoryAdapter",
    ) -> List[List[str]]:
        """找出相似记忆的合并组

        算法流程：
        1. 若记忆数超过 scan_budget，随机采样
        2. 按群聊分组（若启用群聊隔离）
        3. 对每组内记忆分批调用 batch_retrieve
        4. 用 Union-Find 构建连通分量
        5. 返回大小 > 1 的组合并为待合并组

        Args:
            entries: 所有记忆条目
            entry_index: ID→Entry 索引
            adapter: L2 适配器

        Returns:
            合并组列表 [[id1, id2, ...], ...]
        """
        config = get_config()
        enable_group_isolation = bool(
            config.get("isolation_config.enable_group_memory_isolation")
        )

        if len(entries) > self._scan_budget:
            scan_entries = random.sample(entries, self._scan_budget)
            logger.info(
                f"记忆数量 {len(entries)} 超过扫描预算 {self._scan_budget}，"
                f"随机采样 {self._scan_budget} 条"
            )
        else:
            scan_entries = entries

        if enable_group_isolation:
            groups_by_gid: Dict[Optional[str], List["MemoryEntry"]] = {}
            for e in scan_entries:
                gid = e.metadata.get("group_id")
                groups_by_gid.setdefault(gid, []).append(e)
        else:
            groups_by_gid = {None: scan_entries}

        uf = UnionFind()
        total_queries = 0

        for gid, group_entries in groups_by_gid.items():
            for i in range(0, len(group_entries), self._query_batch_size):
                batch = group_entries[i : i + self._query_batch_size]
                queries = [e.content for e in batch]
                query_ids = [e.id for e in batch]

                try:
                    results_batch = cast(
                        List[List["MemorySearchResult"]],
                        await adapter.batch_retrieve(
                            queries=queries, group_id=gid, top_k=5
                        ),
                    )

                    for query_id, results in zip(query_ids, results_batch):  # type: ignore[assignment]
                        query_entry = entry_index.get(query_id)
                        if not query_entry:
                            continue
                        query_gid = query_entry.metadata.get("group_id")

                        for result in results:  # type: ignore[union-attr]
                            if result.entry.id == query_id:  # type: ignore[union-attr]
                                continue
                            if result.score < self._similarity_threshold:  # type: ignore[union-attr]
                                continue
                            if enable_group_isolation:
                                if result.entry.metadata.get("group_id") != query_gid:  # type: ignore[union-attr]
                                    continue
                            uf.union(query_id, result.entry.id)  # type: ignore[union-attr]

                    total_queries += len(batch)
                    if (
                        total_queries % max(100, self._query_batch_size)
                        < self._query_batch_size
                    ):
                        logger.info(
                            f"已扫描 {total_queries}/{len(scan_entries)} 条记忆..."
                        )

                except Exception as e:
                    logger.warning(f"批量检索失败：{e}")

        raw_groups = list(uf.groups().values())

        result: List[List[str]] = []
        for group in raw_groups:
            if len(group) > self._max_group_size:
                result.append(group[: self._max_group_size])
            else:
                result.append(group)

        logger.info(f"扫描 {total_queries} 条记忆，发现 {len(result)} 组相似记忆")
        return result

    # =========================================================================
    # 记忆合并执行
    # =========================================================================

    async def _merge_group(
        self,
        entries: List["MemoryEntry"],
        l2_adapter: "L2MemoryAdapter",
        llm_manager: "LLMManager",
    ) -> tuple:
        """合并一组相似记忆

        先删除所有旧记忆，再迭代合并内容，最后写入合并结果。

        Args:
            entries: 待合并的记忆条目列表
            l2_adapter: L2 适配器
            llm_manager: LLM 管理器

        Returns:
            (合并成功数, 删除条数)
        """
        ids_to_delete = [e.id for e in entries]

        sorted_entries = sorted(
            entries,
            key=lambda e: (e.metadata.get("confidence", 0.5), len(e.content)),
            reverse=True,
        )

        current_content = sorted_entries[0].content
        best_metadata = sorted_entries[0].metadata

        for i in range(1, len(sorted_entries)):
            merged = await self._merge_memories(
                current_content, sorted_entries[i].content, llm_manager
            )
            if merged:
                current_content = merged
            else:
                if len(sorted_entries[i].content) > len(current_content):
                    current_content = sorted_entries[i].content

        group_id = best_metadata.get("group_id")
        max_confidence = max(e.metadata.get("confidence", 0.5) for e in entries)
        merged_from = ",".join(e.id for e in entries)

        new_id = await l2_adapter.add_memory(
            current_content,
            metadata={
                "group_id": group_id,
                "confidence": max_confidence,
                "timestamp": datetime.now().isoformat(),
                "merged_from": merged_from,
            },
            skip_dedup=True,
        )

        if new_id:
            await l2_adapter.delete_entries(ids_to_delete)
            deleted_count = len(ids_to_delete)
            logger.info(f"已合并 {len(entries)} 条记忆 -> {new_id}")
            return 1, deleted_count
        else:
            logger.warning("合并记忆存储失败，保留原记忆")
            return 0, 0

    async def _merge_memories(
        self, content1: str, content2: str, llm_manager: "LLMManager"
    ) -> Optional[str]:
        """使用 LLM 合并两条记忆

        Args:
            content1: 第一条记忆内容
            content2: 第二条记忆内容
            llm_manager: LLM 管理器

        Returns:
            合并后的记忆内容，失败时返回 None
        """
        try:
            prompt = f"""请将以下两条相似的记忆合并为一条更完整、更准确的记忆。

记忆1：{content1}

记忆2：{content2}

要求：
1. 合并重复信息
2. 保留所有独特细节
3. 保持简洁清晰
4. 仅输出合并后的记忆内容，不要添加额外说明

合并后的记忆："""

            merged = await llm_manager.generate_direct(
                prompt=prompt, module="scheduled_tasks"
            )

            if not merged or not merged.strip():
                logger.warning(
                    f"LLM 合并记忆返回空结果，"
                    f"content1={content1[:50]}..., content2={content2[:50]}..."
                )
                return None

            return merged.strip()

        except Exception as e:
            logger.error(f"LLM 合并记忆失败：{e}")
            return None
