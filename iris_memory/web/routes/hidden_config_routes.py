"""
隐藏配置 API 路由

提供隐藏参数的查看和修改功能：
- 获取所有隐藏配置（含默认值、类型、描述）
- 批量更新隐藏配置
- 删除单个隐藏配置项（恢复默认值）
- 重置所有隐藏配置为默认值
"""

import re
from dataclasses import asdict, fields
from typing import Dict, Any

from quart import jsonify, request
from iris_memory.config import get_config
from iris_memory.config.defaults import HiddenConfig
from iris_memory.core import get_logger

logger = get_logger("web.hidden_config")

PLUGIN_NAME = "astrbot_plugin_iris_chat_memory"

_HIDDEN_CONFIG_DESCRIPTIONS: Dict[str, str] = {
    "token_budget_max_tokens": "Token 预算上限",
    "l1_segment_1_length": "L1-1 最新段消息数（始终注入上下文）",
    "l1_segment_3_length": "L1-3 缓冲段消息数（辅助总结理解）",
    "l1_max_queue_tokens": "队列最大 Token 数，超限触发总结",
    "l1_max_single_message_tokens": "单条消息最大 Token 数，超限丢弃",
    "l1_inject_max_content_chars": "注入时单条消息最大字符数，0 不截断",
    "l1_max_memories_per_summary": "每次总结写入 L2 的最大记忆条数",
    "forgetting_lambda": "近因性衰减系数",
    "forgetting_threshold": "遗忘阈值",
    "forgetting_immediate_eviction_threshold": "极端低分直接淘汰阈值",
    "debug_mode": "启用调试模式",
    "verbose_logging": "详细日志输出",
    "log_level": "日志级别",
    "enable_context_logging": "启用 LLM 上下文日志输出",
    "chromadb_batch_size": "ChromaDB 批量写入大小",
    "l2_similarity_threshold": "L2 去重相似度阈值",
    "kuzu_query_timeout_ms": "KuzuDB 查询超时(ms)",
    "entity_extraction_temperature": "实体提取温度",
    "type_merge_threshold": "类型合并相似度阈值",
    "node_confidence_threshold": "节点最低置信度",
    "edge_weight_decay_rate": "边权重衰减率",
    "forgetting_lambda_kg": "知识图谱遗忘系数",
    "forgetting_threshold_kg": "知识图谱遗忘阈值",
    "kg_retention_days": "知识图谱保留天数",
    "call_log_max_entries": "调用日志最大保留条数",
    "forgetting_task_interval_hours": "遗忘清洗任务间隔(小时)",
    "merge_task_interval_hours": "合并任务间隔(小时)",
    "merge_similarity_threshold": "合并相似度阈值",
    "merge_batch_size": "合并批处理大小",
    "merge_scan_budget": "每轮扫描记忆条数上限",
    "merge_query_batch_size": "ChromaDB 批量查询大小",
    "merge_max_group_size": "单组合并最大条目数",
    "eviction_batch_size": "淘汰批处理大小",
    "image_cache_cleanup_interval_hours": "图片缓存清理任务间隔(小时)",
    "kg_extraction_interval_minutes": "提取任务检测间隔(分钟)",
    "kg_extraction_min_unprocessed": "最小未处理记忆数量阈值",
    "kg_extraction_batch_size": "每批处理记忆数",
    "kg_extraction_max_related": "每条记忆最多关联的相关记忆数",
    "kg_extraction_semantic_weight": "语义相似记忆权重",
    "kg_extraction_same_group_weight": "同群聊记忆权重",
    "kg_extraction_same_user_weight": "同用户记忆权重",
    "tool_memory_max_content_length": "记忆内容最大长度",
    "tool_correction_require_confirmation": "修正需确认",
    "tool_timeout_ms": "Tool调用超时(ms)",
    "tool_read_max_results": "读取记忆最大返回数",
    "profile_analysis_interval_hours": "分析任务间隔(小时)",
    "profile_max_messages_for_analysis": "分析时最大消息数",
    "profile_enable_version_control": "启用版本控制",
    "profile_mid_update_interval_summaries": "中期更新: 每隔N次总结触发",
    "profile_mid_update_interval_hours": "中期更新: 最短间隔(小时)",
    "profile_long_update_interval_hours": "长期更新: 最短间隔(小时)",
    "image_parsing_timeout_ms": "图片解析超时(ms)",
    "image_parsing_max_size_kb": "最大图片大小(KB)",
    "image_parsing_supported_formats": "支持的图片格式(逗号分隔)",
    "image_parsing_fallback_on_error": "解析失败时是否入队原始消息",
    "image_phash_enable": "启用 pHash 感知哈希去重",
    "image_phash_threshold": "pHash 汉明距离阈值",
    "image_filter_enable": "启用无效图过滤(纯色/过小)",
    "image_filter_min_size": "最小图片尺寸(像素)",
    "image_filter_std_threshold": "纯色检测标准差阈值",
    "input_sanitizer_enable": "启用 Prompt 注入过滤",
    "input_sanitizer_max_length": "输入最大长度",
    "forgetting_llm_confirm_enable": "启用 LLM 最终兜底确认遗忘",
    "forgetting_llm_confirm_provider": "确认使用的 Provider(空则使用默认)",
    "forgetting_llm_confirm_threshold": "评分低于此值才触发 LLM 确认",
    "l2_query_rewrite_enable": "启用 L2 检索查询改写",
    "l2_query_rewrite_provider": "查询改写使用的 Provider(空则使用默认)",
    "l2_query_rewrite_timeout_ms": "查询改写超时(ms)",
}

_HIDDEN_CONFIG_GROUPS: Dict[str, list] = {
    "L1 缓冲": [
        "l1_segment_1_length",
        "l1_segment_3_length",
        "l1_max_queue_tokens",
        "l1_max_single_message_tokens",
        "l1_inject_max_content_chars",
        "l1_max_memories_per_summary",
    ],
    "Token 预算": [
        "token_budget_max_tokens",
    ],
    "遗忘算法": [
        "forgetting_lambda",
        "forgetting_threshold",
        "forgetting_immediate_eviction_threshold",
    ],
    "调试配置": [
        "debug_mode",
        "verbose_logging",
        "log_level",
        "enable_context_logging",
    ],
    "性能调优": [
        "chromadb_batch_size",
        "l2_similarity_threshold",
        "kuzu_query_timeout_ms",
    ],
    "L3 知识图谱": [
        "entity_extraction_temperature",
        "type_merge_threshold",
        "node_confidence_threshold",
        "edge_weight_decay_rate",
        "forgetting_lambda_kg",
        "forgetting_threshold_kg",
        "kg_retention_days",
    ],
    "LLM 调用管理": [
        "call_log_max_entries",
    ],
    "梦境任务": [
        "dream_task_interval_hours",
        "dream_consolidation_similarity_threshold",
        "dream_consolidation_batch_size",
        "dream_consolidation_scan_budget",
        "dream_consolidation_query_batch_size",
        "dream_consolidation_max_group_size",
        "dream_temporal_anchor_batch_size",
        "dream_contradiction_similarity_floor",
        "dream_contradiction_max_groups",
        "dream_pattern_sample_size",
        "dream_pattern_min_confidence",
        "dream_knowledge_extract_min_unprocessed",
        "dream_knowledge_extract_batch_size",
        "eviction_batch_size",
        "image_cache_cleanup_interval_hours",
    ],
    "Tool 配置": [
        "tool_memory_max_content_length",
        "tool_correction_require_confirmation",
        "tool_timeout_ms",
        "tool_read_max_results",
    ],
    "画像系统": [
        "profile_analysis_interval_hours",
        "profile_max_messages_for_analysis",
        "profile_enable_version_control",
        "profile_mid_update_interval_summaries",
        "profile_mid_update_interval_hours",
        "profile_long_update_interval_hours",
    ],
    "图片解析": [
        "image_parsing_timeout_ms",
        "image_parsing_max_size_kb",
        "image_parsing_supported_formats",
        "image_parsing_fallback_on_error",
        "image_phash_enable",
        "image_phash_threshold",
        "image_filter_enable",
        "image_filter_min_size",
        "image_filter_std_threshold",
    ],
    "输入清理": [
        "input_sanitizer_enable",
        "input_sanitizer_max_length",
    ],
    "遗忘确认": [
        "forgetting_llm_confirm_enable",
        "forgetting_llm_confirm_provider",
        "forgetting_llm_confirm_threshold",
    ],
    "L2 查询改写": [
        "l2_query_rewrite_enable",
        "l2_query_rewrite_provider",
        "l2_query_rewrite_timeout_ms",
    ],
}


def _get_field_type(field_obj) -> str:
    type_name = str(field_obj.type)
    if "int" in type_name:
        return "int"
    elif "float" in type_name:
        return "float"
    elif "bool" in type_name:
        return "bool"
    elif "Literal" in type_name:
        return "literal"
    elif "str" in type_name:
        return "string"
    return "string"


def _get_literal_options(field_obj) -> list:
    type_str = str(field_obj.type)
    if "Literal" not in type_str:
        return []
    matches = re.findall(r"'([^']*)'", type_str)
    return matches


async def get_hidden_config():
    try:
        config = get_config()
        all_values = config.get_all_hidden()
        defaults = asdict(HiddenConfig())
        field_map = {f.name: f for f in fields(HiddenConfig)}

        items = []
        for key, current_value in all_values.items():
            field_obj = field_map.get(key)
            if field_obj is None:
                continue

            item: Dict[str, Any] = {
                "key": key,
                "value": current_value,
                "default": defaults.get(key),
                "type": _get_field_type(field_obj),
                "description": _HIDDEN_CONFIG_DESCRIPTIONS.get(key, ""),
                "group": "",
                "options": _get_literal_options(field_obj),
            }

            for group_name, keys in _HIDDEN_CONFIG_GROUPS.items():
                if key in keys:
                    item["group"] = group_name
                    break

            items.append(item)

        groups = [
            {"name": name, "keys": keys} for name, keys in _HIDDEN_CONFIG_GROUPS.items()
        ]

        return jsonify({"success": True, "items": items, "groups": groups})

    except Exception as e:
        logger.error(f"获取隐藏配置失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


async def update_hidden_config():
    try:
        config = get_config()
        data = await request.get_json()
        updates = data.get("updates", {})

        if not updates:
            return jsonify({"success": False, "error": "未提供更新内容"}), 400

        valid_keys = {f.name for f in fields(HiddenConfig)}
        invalid_keys = [k for k in updates if k not in valid_keys]
        if invalid_keys:
            return jsonify(
                {"success": False, "error": f"无效的配置键: {', '.join(invalid_keys)}"}
            ), 400

        config.update_hidden(updates)

        logger.info(f"隐藏配置已批量更新: {list(updates.keys())}")

        return jsonify({"success": True, "updated_keys": list(updates.keys())})

    except Exception as e:
        logger.error(f"更新隐藏配置失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


async def delete_hidden_config_item():
    try:
        key = request.args.get("key")
        if not key:
            return jsonify({"success": False, "error": "缺少 key 参数"}), 400

        config = get_config()

        valid_keys = {f.name for f in fields(HiddenConfig)}
        if key not in valid_keys:
            return jsonify({"success": False, "error": f"无效的配置键: {key}"}), 400

        deleted = config.delete_hidden(key)
        if deleted:
            logger.info(f"已删除隐藏配置项: {key}，将使用默认值")
            return jsonify({"success": True, "message": f"配置项 {key} 已恢复为默认值"})
        else:
            return jsonify(
                {"success": True, "message": f"配置项 {key} 未被修改，已是默认值"}
            )

    except Exception as e:
        logger.error(f"删除隐藏配置项失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


async def reset_hidden_config():
    try:
        config = get_config()
        config.reset_hidden_to_defaults()

        logger.info("已重置所有隐藏配置为默认值")

        return jsonify({"success": True, "message": "所有隐藏配置已重置为默认值"})

    except Exception as e:
        logger.error(f"重置隐藏配置失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


def register_hidden_config_routes(context) -> None:
    prefix = f"/{PLUGIN_NAME}/hidden-config"

    routes = [
        (f"{prefix}", get_hidden_config, ["GET"], "获取隐藏配置"),
        (f"{prefix}/update", update_hidden_config, ["POST"], "更新隐藏配置"),
        (f"{prefix}/delete", delete_hidden_config_item, ["POST"], "删除隐藏配置项"),
        (f"{prefix}/reset", reset_hidden_config, ["POST"], "重置隐藏配置"),
    ]

    for route, handler, methods, desc in routes:
        context.register_web_api(route, handler, methods, desc)
