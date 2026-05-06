"""图谱检索器"""

from iris_memory.core import get_logger
from iris_memory.config import get_config
from .adapter import L3KGAdapter
from datetime import datetime
from collections import defaultdict
import asyncio

logger = get_logger("l3_kg")

_RELATION_TYPE_LABELS = {
    "KNOWS": "认识",
    "MENTIONED": "提及",
    "RELATED_TO": "相关",
    "PART_OF": "属于",
    "LOCATED_AT": "位于",
    "HAPPENED_AT": "发生在",
    "DISCUSSED": "讨论过",
    "PARTICIPATED": "参与",
}

_NODE_TYPE_LABELS = {
    "Person": "人物",
    "Event": "事件",
    "Concept": "概念",
    "Location": "地点",
    "Item": "物品",
    "Topic": "话题",
}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)


class GraphRetriever:
    """图谱检索器

    提供：
    - 路径扩展检索
    - 超时保护
    - 访问计数更新
    - 结果格式化
    """

    def __init__(self, adapter: L3KGAdapter):
        self.adapter = adapter
        self.config = get_config()

    async def retrieve_with_expansion(
        self, memory_node_ids: list[str], group_id: str = None
    ) -> tuple[list[dict], list[dict]]:
        if not self.adapter._is_available:
            return [], []

        try:
            max_depth = self.config.get("l3_kg.expansion_depth", 2)
            timeout_ms = self.config.get("l3_kg.timeout_ms", 1500)

            nodes, edges = await asyncio.wait_for(
                self.adapter.expand_from_nodes(
                    node_ids=memory_node_ids, max_depth=max_depth, group_id=group_id
                ),
                timeout=timeout_ms / 1000,
            )

            logger.info(
                f"图增强检索完成：{len(nodes)} 个节点，"
                f"{len(edges)} 条边，深度 {max_depth}"
            )

            return nodes, edges
        except asyncio.TimeoutError:
            logger.warning(f"图增强检索超时（{timeout_ms}ms），跳过")
            return [], []
        except Exception as e:
            logger.error(f"图增强检索失败：{e}")
            return [], []

    async def retrieve_by_keywords(
        self, keywords: list[str], group_id: str = None, limit: int = 10
    ) -> tuple[list[dict], list[dict]]:
        """基于关键词搜索图谱节点并扩展

        Args:
            keywords: 搜索关键词列表
            group_id: 群聊ID
            limit: 每个关键词最大返回节点数

        Returns:
            (节点列表, 边列表)
        """
        if not self.adapter._is_available or not keywords:
            return [], []

        matched_node_ids: set[str] = set()

        for keyword in keywords:
            try:
                found = await self.adapter.search_nodes(keyword, limit=5)
                for node in found:
                    node_id = node.get("id")
                    if node_id:
                        matched_node_ids.add(node_id)
            except Exception as e:
                logger.debug(f"关键词 '{keyword}' 搜索失败：{e}")

        if not matched_node_ids:
            return [], []

        if len(matched_node_ids) > 20:
            matched_node_ids = set(list(matched_node_ids)[:20])

        return await self.retrieve_with_expansion(
            memory_node_ids=list(matched_node_ids), group_id=group_id
        )

    async def update_access_count(self, node_ids: list[str]):
        if not self.adapter._is_available:
            return

        try:
            for node_id in node_ids:
                self.adapter._conn.execute(
                    """
                    MATCH (e:Entity {id: $id})
                    SET e.access_count = e.access_count + 1,
                        e.last_access_time = $now
                """,
                    {"id": node_id, "now": datetime.now()},
                )

            logger.debug(f"更新了 {len(node_ids)} 个节点的访问计数")
        except Exception as e:
            logger.error(f"更新节点访问计数失败：{e}")

    def format_for_context(
        self,
        nodes: list[dict],
        edges: list[dict],
        max_tokens: int = 400,
        max_content_length: int = 150,
    ) -> str:
        """格式化图谱结果为上下文文本

        按节点类型分组展示实体，使用自然语言描述关系，
        支持 token 预算控制。

        Args:
            nodes: 节点列表
            edges: 边列表
            max_tokens: 最大 token 预算（估算）
            max_content_length: 节点描述最大字符数

        Returns:
            格式化的文本，如果为空则返回空字符串
        """
        if not nodes:
            return ""

        node_map: dict[str, dict] = {}
        for node in nodes:
            node_id = node.get("id")
            if node_id:
                node_map[node_id] = node

        type_groups: dict[str, list[dict]] = defaultdict(list)
        for node in nodes:
            label = node.get("label", "Entity")
            type_groups[label].append(node)

        lines: list[str] = []
        token_budget = max_tokens

        header = "【知识图谱】以下是你了解的结构化知识，请自然地运用："
        lines.append(header)
        token_budget -= _estimate_tokens(header)

        ordered_types = sorted(
            type_groups.keys(),
            key=lambda t: (0 if t == "Person" else 1 if t == "Event" else 2, t),
        )

        for node_type in ordered_types:
            if token_budget <= 0:
                break

            group = type_groups[node_type]
            type_label = _NODE_TYPE_LABELS.get(node_type, node_type)

            entity_lines: list[str] = []
            for node in group:
                name = node.get("name", "")
                content = node.get("content", "")
                if name and content:
                    if len(content) > max_content_length:
                        content = content[:max_content_length] + "..."
                    entity_lines.append(f"  - {name}：{content}")
                elif name:
                    entity_lines.append(f"  - {name}")

            if not entity_lines:
                continue

            section = f"{type_label}：\n" + "\n".join(entity_lines)
            section_tokens = _estimate_tokens(section)

            if section_tokens > token_budget:
                remaining = max(1, token_budget // 30)
                section = f"{type_label}：\n" + "\n".join(entity_lines[:remaining])
                section_tokens = _estimate_tokens(section)

            if section_tokens <= token_budget:
                lines.append(section)
                token_budget -= section_tokens

        if edges and token_budget > 20:
            edge_lines: list[str] = []
            for edge in edges:
                source_id = edge.get("source", edge.get("_src", ""))
                target_id = edge.get("target", edge.get("_dst", ""))
                relation = edge.get("relation_type", "")

                source_node = node_map.get(source_id, {})
                target_node = node_map.get(target_id, {})

                source_name = source_node.get("name", source_id)
                target_name = target_node.get("name", target_id)

                if source_name and target_name and relation:
                    rel_label = _RELATION_TYPE_LABELS.get(relation, relation)
                    edge_lines.append(f"  - {source_name} {rel_label} {target_name}")

            if edge_lines:
                rel_section = "关系：\n" + "\n".join(edge_lines)
                rel_tokens = _estimate_tokens(rel_section)

                if rel_tokens > token_budget:
                    remaining = max(1, token_budget // 20)
                    rel_section = "关系：\n" + "\n".join(edge_lines[:remaining])

                if _estimate_tokens(rel_section) <= token_budget:
                    lines.append(rel_section)

        result = "\n".join(lines)
        if result.strip() == header.strip():
            return ""

        return result
