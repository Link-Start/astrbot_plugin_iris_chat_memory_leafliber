"""修正记忆 LLM Tool"""

from datetime import datetime
from pydantic import Field
from pydantic.dataclasses import dataclass
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from iris_memory.core import get_logger, get_component_manager

logger = get_logger("tools")


@dataclass
class CorrectMemoryTool(FunctionTool[AstrAgentContext]):
    """修正错误记忆的Tool

    允许用户纠正LLM产生的错误记忆或幻觉。
    同时更新L2记忆库和L3知识图谱中的相关节点。
    """

    name: str = "correct_memory"
    description: str = "修正错误记忆或幻觉，用户主动纠正不准确的信息"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "要修正的记忆ID（格式：mem_xxxxxxxxxx）",
                },
                "correction": {
                    "type": "string",
                    "description": "修正后的正确内容",
                },
                "reason": {
                    "type": "string",
                    "description": "修正原因（为什么原记忆是错误的）",
                },
            },
            "required": ["memory_id", "correction", "reason"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs,
    ) -> str:
        try:
            memory_id = kwargs.get("memory_id", "").strip()
            correction = kwargs.get("correction", "").strip()
            reason = kwargs.get("reason", "").strip()

            if not all([memory_id, correction, reason]):
                return "参数不完整：需要提供 memory_id、correction 和 reason"

            from iris_memory.utils import sanitize_input

            correction = sanitize_input(correction, source="tool:correct_memory")
            reason = sanitize_input(reason, source="tool:correct_memory")

            event = context.context.event
            from iris_memory.platform import get_adapter

            adapter = get_adapter(event)
            user_id = adapter.get_user_id(event)

            manager = get_component_manager()
            l2_adapter = manager.get_component("l2_memory")
            l3_adapter = manager.get_component("l3_kg")

            if not l2_adapter or not l2_adapter._is_available:
                return "L2记忆库当前不可用"

            try:
                results = await l2_adapter.retrieve(query=memory_id, top_k=1)

                if not results:
                    return f"未找到ID为 {memory_id} 的记忆"

                original_memory = results[0].entry
                original_content = original_memory.content

            except Exception as e:
                logger.error(f"检索原始记忆失败：{e}")
                return f"无法检索原始记忆：{str(e)}"

            try:
                await l2_adapter.delete_entries([memory_id])

                now = datetime.now().isoformat()
                new_metadata = original_memory.metadata.copy()
                new_metadata.update(
                    {
                        "corrected": True,
                        "correction_time": now,
                        "correction_reason": reason,
                        "corrected_by": user_id,
                        "confidence": 1.0,
                    }
                )

                await l2_adapter.add_memory(content=correction, metadata=new_metadata)

                logger.info(
                    f"用户修正记忆: user={user_id}, memory_id={memory_id}, "
                    f"original={original_content[:30]}..., "
                    f"corrected={correction[:30]}..."
                )

            except Exception as e:
                logger.error(f"更新L2记忆失败：{e}", exc_info=True)
                return f"更新L2记忆失败：{str(e)}"

            kg_message = ""

            if l3_adapter and l3_adapter._is_available:
                try:
                    cypher = (
                        "MATCH (n:Entity {source_memory_id: $memory_id}) "
                        "RETURN n.id, n.name, n.content"
                    )
                    result_set = l3_adapter._conn.execute(
                        cypher, {"memory_id": memory_id}
                    )

                    if result_set.has_next():
                        node = result_set.get_next()
                        node_id = node[0]

                        update_cypher = (
                            "MATCH (n:Entity {id: $node_id}) "
                            "SET n.content = $correction, "
                            "    n.corrected = true, "
                            "    n.correction_time = timestamp(), "
                            "    n.confidence = 1.0"
                        )
                        l3_adapter._conn.execute(
                            update_cypher,
                            {"node_id": node_id, "correction": correction},
                        )
                        kg_message = "已更新知识图谱中的相关节点"
                        logger.info(f"已更新图谱节点: node_id={node_id}")
                    else:
                        kg_message = "知识图谱中未找到相关节点"

                except Exception as e:
                    logger.warning(f"更新L3图谱失败：{e}")
                    kg_message = f"更新知识图谱失败：{str(e)}"
            else:
                kg_message = "知识图谱未启用或不可用"

            result_lines = [
                "✓ 记忆修正完成",
                "",
                f"记忆ID: {memory_id}",
                f"原始内容: {original_content}",
                f"修正内容: {correction}",
                f"修正原因: {reason}",
                "",
                "L2记忆库: 已更新",
                f"L3知识图谱: {kg_message}",
            ]

            return "\n".join(result_lines)

        except Exception as e:
            logger.error(f"修正记忆失败：{e}", exc_info=True)
            return f"修正记忆失败：{str(e)}"
