"""
Iris Chat Memory - 梦境阶段4：模式挖掘

跨记忆发现隐含的行为规律、偏好模式、因果关联。

Features:
    - 按群聊/用户分组采样
    - LLM 模式提取
    - 写入 L2 + L3（Pattern 类型节点）
    - 向量检索去重
"""

import random
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, cast

from iris_memory.core import get_logger
from iris_memory.config import get_config
from iris_memory.l2_memory.adapter import L2MemoryAdapter
from iris_memory.l3_kg.adapter import L3KGAdapter
from iris_memory.llm.manager import LLMManager
from iris_memory.l3_kg.models import GraphNode

logger = get_logger("dream.pattern_discovery")


class PatternDiscoveryPhase:
    """模式挖掘阶段

    跨记忆发现隐含的行为规律、偏好模式、因果关联。
    """

    def __init__(self):
        self._sample_size = 30
        self._min_confidence = "medium"

    async def execute(
        self,
        l2: "L2MemoryAdapter",
        l3: Optional["L3KGAdapter"],
        llm: Optional["LLMManager"],
        entries: Optional[list] = None,
    ) -> dict:
        config = get_config()
        self._sample_size = cast(int, config.get("dream_pattern_sample_size"))
        self._min_confidence = cast(str, config.get("dream_pattern_min_confidence"))

        if not llm:
            logger.warning("LLMManager 不可用，跳过模式挖掘")
            return {"groups_analyzed": 0, "patterns_found": 0, "patterns_written": 0}

        try:
            if entries is None:
                entries = await l2.get_all_entries()

            if not entries:
                logger.debug("L2 记忆库为空，跳过模式挖掘")
                return {
                    "groups_analyzed": 0,
                    "patterns_found": 0,
                    "patterns_written": 0,
                }

            groups = self._group_entries(entries)

            logger.info(f"开始模式挖掘：{len(groups)} 个分组，共 {len(entries)} 条记忆")

            groups_analyzed = 0
            patterns_found = 0
            patterns_written = 0

            for group_key, group_entries in groups.items():
                if len(group_entries) < 3:
                    continue

                groups_analyzed += 1

                sample = (
                    random.sample(group_entries, self._sample_size)
                    if len(group_entries) > self._sample_size
                    else group_entries
                )

                try:
                    patterns = await self._extract_patterns(sample, llm)
                    patterns_found += len(patterns)

                    for pattern in patterns:
                        if pattern["confidence"] == "low":
                            continue

                        is_dup = await self._check_duplicate(pattern["description"], l2)
                        if is_dup:
                            logger.debug(
                                f"模式已存在，跳过：{pattern['description'][:50]}"
                            )
                            continue

                        written = await self._write_pattern(pattern, group_key, l2, l3)
                        if written:
                            patterns_written += 1

                except Exception as e:
                    logger.error(f"分组 [{group_key}] 模式挖掘失败：{e}", exc_info=True)

            logger.info(
                f"模式挖掘完成：分析 {groups_analyzed} 组，"
                f"发现 {patterns_found} 个模式，写入 {patterns_written} 个"
            )
            return {
                "groups_analyzed": groups_analyzed,
                "patterns_found": patterns_found,
                "patterns_written": patterns_written,
            }

        except Exception as e:
            logger.error(f"模式挖掘失败：{e}", exc_info=True)
            return {
                "groups_analyzed": 0,
                "patterns_found": 0,
                "patterns_written": 0,
                "error": str(e),
            }

    def _group_entries(self, entries: list) -> Dict[str, list]:
        config = get_config()
        enable_group_isolation = bool(
            config.get("isolation_config.enable_group_memory_isolation")
        )

        groups: Dict[str, list] = defaultdict(list)

        if enable_group_isolation:
            for entry in entries:
                gid = entry.group_id or "_no_group"
                groups[gid].append(entry)
        else:
            groups["_all"] = entries

        return dict(groups)

    async def _extract_patterns(self, entries: list, llm: "LLMManager") -> List[dict]:
        memory_texts = []
        for i, entry in enumerate(entries, 1):
            user_id = entry.metadata.get("user_id", "")
            user_prefix = f"[用户:{user_id}] " if user_id else ""
            memory_texts.append(f"{i}. {user_prefix}{entry.content}")

        prompt = f"""以下是同一用户/群聊的若干记忆片段，请挖掘其中隐含的行为模式、偏好规律或因果关联。
只输出你确信发现的模式，不要猜测。

记忆片段：
{chr(10).join(memory_texts)}

输出格式（每行一个模式，严格按以下格式）：
PATTERN: <模式描述>
EVIDENCE: <支撑该模式的记忆编号，用逗号分隔>
CONFIDENCE: <high/medium/low>

如果没有发现任何可靠模式，输出 NONE。"""

        try:
            response = await llm.generate_direct(
                prompt=prompt, module="dream_pattern_discovery"
            )

            if not response or not response.strip():
                return []

            if "NONE" in response.strip().upper():
                return []

            return self._parse_patterns(response)

        except Exception as e:
            logger.error(f"LLM 模式提取失败：{e}")
            return []

    def _parse_patterns(self, response: str) -> List[dict]:
        patterns = []
        current = {}

        for line in response.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("PATTERN:"):
                if current.get("description"):
                    patterns.append(current)
                current = {"description": line.split(":", 1)[1].strip()}
            elif line.upper().startswith("EVIDENCE:") and current.get("description"):
                current["evidence"] = line.split(":", 1)[1].strip()
            elif line.upper().startswith("CONFIDENCE:") and current.get("description"):
                conf = line.split(":", 1)[1].strip().lower()
                current["confidence"] = (
                    conf if conf in ("high", "medium", "low") else "low"
                )

        if current.get("description"):
            patterns.append(current)

        return patterns

    async def _check_duplicate(self, description: str, l2: "L2MemoryAdapter") -> bool:
        try:
            results = await l2.retrieve(description, top_k=3)
            for result in results:
                if (
                    result.score > 0.9
                    and result.entry.metadata.get("source") == "dream_pattern"
                ):
                    return True
        except Exception:
            pass
        return False

    async def _write_pattern(
        self,
        pattern: dict,
        group_key: str,
        l2: "L2MemoryAdapter",
        l3: Optional["L3KGAdapter"],
    ) -> bool:
        description = pattern["description"]
        confidence_map = {"high": 0.9, "medium": 0.7, "low": 0.4}
        confidence = confidence_map.get(pattern.get("confidence", "low"), 0.4)

        new_id = await l2.add_memory(
            description,
            metadata={
                "source": "dream_pattern",
                "confidence": confidence,
                "timestamp": datetime.now().isoformat(),
                "group_id": group_key if group_key != "_all" else None,
                "evidence": pattern.get("evidence", ""),
            },
        )

        if not new_id:
            return False

        if l3 and l3.is_available:
            try:
                node = GraphNode(
                    id="",
                    label="Pattern",
                    name=description[:50],
                    content=description,
                    confidence=confidence,
                    group_id=group_key if group_key != "_all" else None,
                )
                node.id = node.generate_id()
                await l3.add_node(node)
            except Exception as e:
                logger.debug(f"写入 L3 Pattern 节点失败：{e}")

        return True
