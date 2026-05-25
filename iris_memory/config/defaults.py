"""
Iris Chat Memory - 默认配置定义

使用 dataclass 提供类型安全的配置定义，支持：
- IDE 自动补全
- 编译时类型检查
- 字段注释即文档
- 扁平化键名访问
"""

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional, Dict


@dataclass
class L1BufferConfig:
    """L1 消息上下文缓冲配置（用户可见选项）"""

    enable: bool = True
    summary_provider: str = ""
    inject_queue_length: int = 50
    enable_image_parsing: bool = False
    image_parsing_provider: str = ""
    image_parsing_mode: Literal["all", "related"] = "related"
    image_parsing_daily_quota: int = 200
    image_parsing_max_parse_per_request: int = 5
    image_parsing_max_concurrent_parse: int = 3
    image_parsing_cache_retention_days: int = 7
    image_parsing_skip_on_passive_trigger: bool = True


@dataclass
class L2MemoryConfig:
    """L2 记忆库配置"""

    enable: bool = True
    summary_provider: str = ""
    embedding_source: Literal["provider", "local"] = "provider"
    embedding_provider: str = ""
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    top_k: int = 10
    max_entries: int = 10000
    timeout_ms: int = 4000
    relevance_threshold: float = 0.3


@dataclass
class L3KGConfig:
    """L3 知识图谱配置"""

    enable: bool = True
    max_nodes: int = 50000
    max_edges: int = 100000
    timeout_ms: int = 1500
    expansion_depth: int = 2
    enable_type_whitelist: bool = True
    max_inject_tokens: int = 600


@dataclass
class ProfileConfig:
    """画像系统配置"""

    enable: bool = True
    analysis_provider: str = ""
    analysis_mode: Literal["all", "related"] = "all"
    enable_auto_injection: bool = True


@dataclass
class IsolationConfig:
    """隔离配置"""

    enable_group_memory_isolation: bool = False
    enable_group_isolation: bool = False
    enable_persona_isolation: bool = False


@dataclass
class ScheduledTasksConfig:
    """梦境任务配置"""

    provider: str = ""
    enable_dream: bool = True
    dream_enable_consolidation: bool = True
    dream_enable_temporal_anchor: bool = True
    dream_enable_contradiction: bool = True
    dream_enable_pattern_discovery: bool = True
    dream_enable_knowledge_extract: bool = True
    dream_enable_pruning: bool = True


@dataclass
class ContextControlConfig:
    """上下文控制配置"""

    enable_conversation_cleanup: bool = True


@dataclass
class HiddenConfig:
    """隐藏配置(内部参数)

    这些配置项不会在 WebUI 中展示，用于控制内部行为。
    支持运行时热修改，并自动持久化到 data/iris_memory/hidden_config.json
    """

    # Token 预算控制
    token_budget_max_tokens: int = 2000

    # L1 缓冲内部参数
    l1_segment_1_length: int = 10  # L1-1 最新段消息数
    l1_segment_3_length: int = 10  # L1-3 缓冲段消息数
    l1_max_queue_tokens: int = 4000  # 队列最大 Token 数，超限触发总结
    l1_max_single_message_tokens: int = 500  # 单条消息最大 Token 数，超限丢弃
    l1_inject_max_content_chars: int = 200  # 注入时单条消息最大字符数，0 不截断
    l1_max_memories_per_summary: int = 10  # 每次总结写入 L2 的最大记忆条数

    # 遗忘权重算法参数
    forgetting_lambda: float = 0.1  # 近因性衰减系数
    forgetting_threshold: float = 0.3  # 遗忘阈值
    forgetting_immediate_eviction_threshold: float = 0.1  # 极端低分直接淘汰阈值

    # 调试配置
    debug_mode: bool = False  # 启用调试模式
    verbose_logging: bool = False  # 详细日志输出
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    enable_context_logging: bool = False  # 启用 LLM 上下文日志输出

    # 性能调优
    chromadb_batch_size: int = 100  # ChromaDB 批量写入大小
    l2_similarity_threshold: float = 0.90  # L2 去重相似度阈值
    kuzu_query_timeout_ms: int = 5000  # KuzuDB 查询超时

    # L3 知识图谱参数
    entity_extraction_temperature: float = 0.3  # 实体提取温度
    type_merge_threshold: float = 0.8  # 类型合并相似度阈值
    node_confidence_threshold: float = 0.3  # 节点最低置信度
    edge_weight_decay_rate: float = 0.01  # 边权重衰减率
    forgetting_lambda_kg: float = 0.01  # 知识图谱遗忘系数
    forgetting_threshold_kg: float = 0.2  # 知识图谱遗忘阈值
    kg_retention_days: int = 30  # 知识图谱保留天数

    # LLM 调用管理参数
    call_log_max_entries: int = 100  # 调用日志最大保留条数

    # 梦境任务参数
    dream_task_interval_hours: int = 24
    dream_consolidation_similarity_threshold: float = 0.85
    dream_consolidation_batch_size: int = 10
    dream_consolidation_scan_budget: int = 500
    dream_consolidation_query_batch_size: int = 50
    dream_consolidation_max_group_size: int = 5
    dream_temporal_anchor_batch_size: int = 50
    dream_contradiction_similarity_floor: float = 0.55
    dream_contradiction_similarity_ceiling: float = 0.85
    dream_contradiction_max_groups: int = 20
    dream_pattern_sample_size: int = 30
    dream_pattern_min_confidence: str = "medium"
    dream_knowledge_extract_min_unprocessed: int = 10
    dream_knowledge_extract_batch_size: int = 20
    eviction_batch_size: int = 100
    image_cache_cleanup_interval_hours: int = 24

    # Tool 配置参数
    tool_memory_max_content_length: int = 500  # 记忆内容最大长度
    tool_correction_require_confirmation: bool = False  # 修正需确认
    tool_timeout_ms: int = 2000  # Tool调用超时
    tool_read_max_results: int = 10  # 读取记忆最大返回数

    # 画像系统参数
    profile_analysis_interval_hours: int = 24  # 分析任务间隔（小时）
    profile_max_messages_for_analysis: int = 50  # 分析时最大消息数
    profile_enable_version_control: bool = True  # 启用版本控制
    profile_mid_update_interval_summaries: int = 5  # 中期更新：每隔N次总结触发
    profile_mid_update_interval_hours: float = 24.0  # 中期更新：最短间隔（小时）
    profile_long_update_interval_hours: float = (
        168.0  # 长期更新：最短间隔（小时，默认7天）
    )

    # 图片解析参数
    image_parsing_timeout_ms: int = 30000  # 图片解析超时（毫秒）
    image_parsing_max_size_kb: int = 4096  # 最大图片大小（KB）
    image_parsing_supported_formats: str = "jpg,jpeg,png,gif,webp"  # 支持的图片格式
    image_parsing_fallback_on_error: bool = True  # 解析失败时是否入队原始消息
    image_phash_enable: bool = True  # 启用 pHash 感知哈希去重
    image_phash_threshold: int = 10  # pHash 汉明距离阈值（越小越严格）
    image_filter_enable: bool = True  # 启用无效图过滤（纯色/过小）
    image_filter_min_size: int = 16  # 最小图片尺寸（像素）
    image_filter_std_threshold: float = 5.0  # 纯色检测标准差阈值

    # 输入清理参数
    input_sanitizer_enable: bool = True  # 启用 Prompt 注入过滤
    input_sanitizer_max_length: int = 10000  # 输入最大长度

    # 遗忘确认参数
    forgetting_llm_confirm_enable: bool = False  # 启用 LLM 最终兜底确认遗忘
    forgetting_llm_confirm_provider: str = ""  # 确认使用的 Provider（空则使用默认）
    forgetting_llm_confirm_threshold: float = 0.15  # 评分低于此值才触发 LLM 确认

    # L2 查询改写参数
    l2_query_rewrite_enable: bool = True  # 启用 L2 检索查询改写
    l2_query_rewrite_provider: str = ""  # 查询改写使用的 Provider（空则使用默认）
    l2_query_rewrite_timeout_ms: int = 3000  # 查询改写超时（毫秒）


@dataclass
class Defaults:
    """所有默认配置的统一入口

    提供扁平化键名访问方法，支持 "l1_buffer.enable" 格式的键名。
    """

    l1_buffer: L1BufferConfig = field(default_factory=L1BufferConfig)
    l2_memory: L2MemoryConfig = field(default_factory=L2MemoryConfig)
    l3_kg: L3KGConfig = field(default_factory=L3KGConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    isolation_config: IsolationConfig = field(default_factory=IsolationConfig)
    scheduled_tasks: ScheduledTasksConfig = field(default_factory=ScheduledTasksConfig)
    context_control: ContextControlConfig = field(default_factory=ContextControlConfig)
    hidden: HiddenConfig = field(default_factory=HiddenConfig)

    def get_by_flat_key(self, flat_key: str) -> Optional[object]:
        """通过扁平化键名获取默认值

        Args:
            flat_key: 扁平化键名，支持两种格式：
                - "l1_buffer.enable" (用户配置)
                - "debug_mode" (隐藏配置)

        Returns:
            默认值，找不到返回 None

        Examples:
            >>> defaults = Defaults()
            >>> defaults.get_by_flat_key("l1_buffer.enable")
            True
            >>> defaults.get_by_flat_key("debug_mode")
            False
        """
        parts = flat_key.split(".")

        if len(parts) == 1:
            # 隐藏配置项(单层键名)
            return getattr(self.hidden, parts[0], None)
        elif len(parts) == 2:
            # 用户配置项(双层键名：section.key)
            section, key = parts
            section_config = getattr(self, section, None)
            if section_config is not None:
                return getattr(section_config, key, None)

        return None

    def get_section_defaults(self, section: str) -> Dict[str, object]:
        """获取指定配置分组的所有默认值

        Args:
            section: 配置分组名，如 "l1_buffer"

        Returns:
            配置字典

        Examples:
            >>> defaults = Defaults()
            >>> l1_defaults = defaults.get_section_defaults("l1_buffer")
            >>> print(l1_defaults["enable"])
            True
        """
        section_config = getattr(self, section, None)
        if section_config is None:
            return {}
        return asdict(section_config)
