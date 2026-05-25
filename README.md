# Iris Chat Memory

<p align="center">
  <img src="logo.png" alt="Iris Logo" width="128" height="128">
</p>

<p align="center">
  <img src="https://moe-counter.glitch.me/get/@astrbot_plugin_iris_chat_memory" alt="Visitor Count">
</p>

面向 AstrBot 的三层记忆插件：让机器人"记住你"，针对群聊优化。

⚠️注意：

- 插件默认启用上下文控制，会自动清理 AstrBot 内置对话历史，确保上下文完全由插件管理
- 建议关闭 AstrBot 自带的"上下文感知"以避免冲突
- `iris_mem` 指令需要管理员权限，请先在 AstrBot WebUI 中配置管理员 ID
- 项目在快速迭代，如遇问题请提交 Issue

## 功能特性

### 三层记忆架构

- **L1 消息缓冲**：三段式 FIFO 队列，自动总结，短期上下文管理
- **L2 记忆库**：ChromaDB 向量检索，遗忘/合并/去重，中期记忆
- **L3 知识图谱**：KuzuDB 实体关系图谱，图增强检索，长期结构化知识

### 核心能力

- ✅ **三段式 FIFO**：L1-1（最新段）→ L1-2（主体段）→ L1-3（辅助段），自动总结
- ✅ **向量检索**：ChromaDB 语义相似度搜索 + 查询改写 + Token 预算控制
- ✅ **知识图谱**：LLM 实体关系提取、类型白名单、图增强检索、节点淘汰
- ✅ **用户画像**：性格标签、兴趣、职业、语言风格、禁忌话题等，三层更新频率
- ✅ **群聊画像**：群聊兴趣、氛围标签、核心特征、禁忌话题
- ✅ **图片解析**：视觉模型分析图片内容，pHash 去重，无效图过滤，每日配额
- ✅ **LLM 工具**：6 个主动记忆管理工具（保存/搜索/修正记忆、图谱操作、画像查询）
- ✅ **梦境任务**：6 阶段离线记忆加工（合并重复→时间锚定→矛盾消解→模式挖掘→知识提取→遗忘清洗）
- ✅ **会话隔离**：群聊记忆隔离、群聊画像隔离、Bot 人格隔离
- ✅ **置信度分级**：总结时对每条记忆评估 high/medium/low 置信度
- ✅ **Web 管理界面**：Dashboard、L1/L2/L3 管理、画像编辑、数据管理、隐藏配置热修改

### 辅助功能

- ✅ **上下文控制**：自动清理 AstrBot 内置对话历史
- ✅ **输入清理**：Prompt 注入过滤，输入长度限制
- ✅ **被动触发检测**：区分主动对话和 sampling/主动回复，按需降级
- ✅ **组件故障隔离**：单组件初始化失败不影响其他组件
- ✅ **后台初始化**：重型组件（ChromaDB、KuzuDB）后台异步初始化，不阻塞启动
- ✅ **灵活嵌入**：L2 支持使用 AstrBot Embedding Provider 或本地 sentence-transformers 模型

## 设备要求与资源占用

L2 记忆库（ChromaDB）和 L3 知识图谱（KuzuDB）为嵌入式数据库，数据存储在本地磁盘，运行时占用一定内存和磁盘空间。

### 推荐配置

| 资源 | 最低要求 | 推荐配置 |
|------|----------|----------|
| **内存** | 2 GB 可用 | 4 GB+ 可用 |
| **磁盘** | 500 MB | 2 GB+（随记忆量增长） |
| **CPU** | 2 核 | 4 核+ |

### 资源占用说明

- **L2 ChromaDB**：内存占用与记忆条目数正相关，1 万条记忆约 200～500 MB 内存
- **L3 KuzuDB**：磁盘占用与节点/边数量正相关，5 万节点约 100～300 MB 磁盘
- **本地嵌入模型**：使用本地 `sentence-transformers` 时，模型加载约额外占用 200～500 MB 内存；使用 AstrBot Embedding Provider 则不占用本地内存
- **首次启动**：本地嵌入模型首次使用需下载约 96 MB 模型文件

> 💡 如果设备资源有限，建议使用 AstrBot Embedding Provider（默认）以避免本地模型加载的内存开销，或关闭 L3 知识图谱。

## 快速开始

### 1) 安装与启用

1. 在 AstrBot 插件市场搜索安装本插件，或将插件放入 `data/plugins` 目录。
2. 确认依赖可用（`chromadb`、`kuzu` 已安装，默认自动安装）。
3. L2 嵌入模型默认使用 AstrBot 配置的 Embedding Provider，无需额外下载。如需使用本地模型，需安装 `sentence-transformers` 并在配置中将嵌入来源切换为「本地」。

### 2) 推荐先做的事

- 为避免行为冲突，建议关闭 AstrBot 自带的"上下文感知"。
- 使用 `iris_mem` 指令需要管理员权限，请先在 AstrBot WebUI → 配置 → 其他配置 → 管理员 ID 列表中添加你的 ID（可用 `/sid` 获取你的用户 ID）。
- 确保在 AstrBot 中配置了可用的 Embedding Provider（如 OpenAI 兼容服务、Ollama 等），否则 L2 记忆库将降级使用本地嵌入模型。

### 3) 验证是否生效

发送以下命令检查：

- `/iris_mem l1 stats` — 查看 L1 消息缓冲统计
- `/iris_mem l2 stats` — 查看 L2 记忆库统计
- `/iris_mem l3 stats` — 查看 L3 知识图谱统计

能看到统计数据，即表示核心链路正常。

## 常用指令

所有指令需要管理员权限，基本格式：`/iris_mem <模块> <子指令> [参数]`

### `/iris_mem l1` - L1 消息缓冲

| 命令 | 说明 |
|------|------|
| `/iris_mem l1 stats` | 查看 L1 消息缓冲统计 |
| `/iris_mem l1 clear` | 清空当前用户的 L1 |
| `/iris_mem l1 clear @用户` | 清空指定用户的 L1 |
| `/iris_mem l1 clear --group` | 清空当前群聊的 L1 |
| `/iris_mem l1 clear --all` | 清空所有 L1 |

### `/iris_mem l2` - L2 记忆库

| 命令 | 说明 |
|------|------|
| `/iris_mem l2 stats` | 查看 L2 记忆库统计 |
| `/iris_mem l2 clear` | 清空当前用户的 L2 记忆 |
| `/iris_mem l2 clear @用户` | 清空指定用户的 L2 记忆 |
| `/iris_mem l2 clear --group` | 清空当前群聊的 L2 记忆 |
| `/iris_mem l2 clear --all` | 清空所有 L2 记忆 |

### `/iris_mem l3` - L3 知识图谱

| 命令 | 说明 |
|------|------|
| `/iris_mem l3 stats` | 查看 L3 知识图谱统计 |
| `/iris_mem l3 clear` | 清空当前用户的 L3 知识图谱 |
| `/iris_mem l3 clear @用户` | 清空指定用户的 L3 知识图谱 |
| `/iris_mem l3 clear --group` | 清空当前群聊的 L3 知识图谱 |
| `/iris_mem l3 clear --all` | 清空所有 L3 知识图谱 |

### `/iris_mem profile` - 画像管理

| 命令 | 说明 |
|------|------|
| `/iris_mem profile show` | 显示当前用户画像 |
| `/iris_mem profile show @用户` | 显示指定用户画像 |
| `/iris_mem profile reset` | 重置当前用户画像 |
| `/iris_mem profile reset @用户` | 重置指定用户画像 |
| `/iris_mem profile reset --group` | 重置当前群聊所有用户画像 |
| `/iris_mem profile reset --all` | 重置所有用户画像 |
| `/iris_mem profile group show` | 显示群聊画像 |
| `/iris_mem profile group reset` | 重置群聊画像 |

### `/iris_mem all` - 总删除

| 命令 | 说明 |
|------|------|
| `/iris_mem all clear` | 清空当前用户所有记忆和画像 |
| `/iris_mem all clear @用户` | 清空指定用户所有记忆和画像 |
| `/iris_mem all clear --group` | 清空当前群聊所有记忆和画像 |
| `/iris_mem all clear --all` | 清空所有记忆和画像（谨慎使用） |

### 删除粒度说明

| 粒度 | 说明 |
|------|------|
| 默认（无参数） | 仅操作当前用户在当前群聊的数据 |
| `@用户` | 操作指定用户在当前群聊的数据 |
| `--group` / `-g` | 操作当前群聊的所有数据 |
| `--all` / `-a` | 操作所有数据（全局） |

## 推荐配置

下面这套配置兼顾效果与成本，适合大多数用户：

| 配置项 | 建议值 | 说明 |
|--------|--------|------|
| `l1_buffer.enable` | `true` | 开启 L1 上下文缓冲 |
| `l1_buffer.inject_queue_length` | `50` | 上下文消息条数，越大上下文越完整但 token 消耗越多 |
| `l1_buffer.enable_image_parsing` | `true` | 开启图片解析（需要视觉模型） |
| `l2_memory.enable` | `true` | 开启 L2 记忆库 |
| `l2_memory.embedding_source` | `"provider"` | 使用 AstrBot Embedding Provider（推荐，无需下载模型） |
| `l2_memory.top_k` | `10` | 检索数量，3～10 之间平衡效果与 token 消耗 |
| `l2_memory.relevance_threshold` | `0.3` | 相关性阈值，过低会注入无关记忆 |
| `l3_kg.enable` | `true` | 开启知识图谱 |
| `profile.enable` | `true` | 开启画像系统 |
| `profile.enable_auto_injection` | `true` | 自动注入画像到上下文 |
| `context_control.enable_conversation_cleanup` | `true` | 自动清理 AstrBot 内置对话历史 |
| `scheduled_tasks.enable_dream` | `true` | 开启梦境任务（含遗忘清洗、记忆合并等） |

## 配置说明

### L1 消息缓冲

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `l1_buffer.enable` | 启用 L1 上下文缓冲 | `true` |
| `l1_buffer.summary_provider` | 总结模型（留空使用默认 Provider） | `""` |
| `l1_buffer.inject_queue_length` | 上下文消息条数 | `50` |
| `l1_buffer.enable_image_parsing` | 启用图片解析 | `false` |
| `l1_buffer.image_parsing_provider` | 图片解析模型（需支持视觉能力） | `""` |
| `l1_buffer.image_parsing_mode` | 解析模式（all/related） | `"related"` |
| `l1_buffer.image_parsing_daily_quota` | 每日解析限额 | `200` |
| `l1_buffer.image_parsing_skip_on_passive_trigger` | 被动触发时跳过图片解析 | `true` |

### L2 记忆库

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `l2_memory.enable` | 启用 L2 记忆库 | `true` |
| `l2_memory.summary_provider` | L2 总结模型（留空使用默认 Provider） | `""` |
| `l2_memory.embedding_source` | 嵌入模型来源（`"provider"` / `"local"`） | `"provider"` |
| `l2_memory.embedding_provider` | Embedding Provider（仅 provider 模式，留空自动选择） | `""` |
| `l2_memory.embedding_model` | 本地嵌入模型（仅 local 模式生效） | `"BAAI/bge-small-zh-v1.5"` |
| `l2_memory.top_k` | 检索 Top-K | `10` |
| `l2_memory.max_entries` | 最大条目数 | `10000` |
| `l2_memory.timeout_ms` | 检索超时（毫秒） | `4000` |
| `l2_memory.relevance_threshold` | 相关性阈值 | `0.3` |

> ⚠️ **切换嵌入模型或来源前，请先导出备份记忆数据！** 更换嵌入模型后向量维度可能改变，插件会自动重建记忆库，已有记忆将丢失。可通过 Web 管理界面或 `MemoryExporter` 导出数据。

### L3 知识图谱

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `l3_kg.enable` | 启用 L3 知识图谱 | `true` |
| `l3_kg.extraction_provider` | 实体提取模型（留空使用默认 Provider） | `""` |
| `l3_kg.max_nodes` | 最大节点数 | `50000` |
| `l3_kg.max_edges` | 最大边数 | `100000` |
| `l3_kg.timeout_ms` | 检索超时（毫秒） | `1500` |
| `l3_kg.expansion_depth` | 图增强检索路径扩展深度 | `2` |
| `l3_kg.enable_type_whitelist` | 启用类型白名单约束 | `true` |
| `l3_kg.max_inject_tokens` | 图谱注入最大 token 数 | `600` |

### 画像系统

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `profile.enable` | 启用画像系统 | `true` |
| `profile.analysis_provider` | 画像分析模型（留空使用默认 Provider） | `""` |
| `profile.analysis_mode` | 分析模式（all/related） | `"all"` |
| `profile.enable_auto_injection` | 启用画像自动注入 | `true` |

### 隔离配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `isolation_config.enable_group_memory_isolation` | 群聊记忆隔离 | `false` |
| `isolation_config.enable_group_isolation` | 群聊用户画像隔离 | `false` |
| `isolation_config.enable_persona_isolation` | Bot 人格隔离 | `false` |

### 梦境任务

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `scheduled_tasks.provider` | 梦境任务模型（留空使用默认 Provider） | `""` |
| `scheduled_tasks.enable_dream` | 启用梦境任务 | `true` |
| `scheduled_tasks.dream_enable_consolidation` | 阶段 1：合并重复项 | `true` |
| `scheduled_tasks.dream_enable_temporal_anchor` | 阶段 2：时间锚定 | `true` |
| `scheduled_tasks.dream_enable_contradiction` | 阶段 3：矛盾消解 | `true` |
| `scheduled_tasks.dream_enable_pattern_discovery` | 阶段 4：模式挖掘 | `true` |
| `scheduled_tasks.dream_enable_knowledge_extract` | 阶段 5：知识提取 | `true` |
| `scheduled_tasks.dream_enable_pruning` | 阶段 6：遗忘清洗 | `true` |

### 上下文控制

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `context_control.enable_conversation_cleanup` | 自动清理 AstrBot 内置对话历史 | `true` |

### 隐藏配置

隐藏配置不在 WebUI 中展示，用于控制内部行为。存储在 `data/iris_memory/hidden_config.json`，支持运行时热修改。

#### Token 预算与 L1 缓冲

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `token_budget_max_tokens` | `2000` | L2 记忆注入最大 token 数 |
| `l1_segment_1_length` | `10` | L1-1 最新段消息数 |
| `l1_segment_3_length` | `10` | L1-3 缓冲段消息数 |
| `l1_max_queue_tokens` | `4000` | 队列最大 Token 数 |
| `l1_max_single_message_tokens` | `500` | 单条消息最大 Token 数 |
| `l1_inject_max_content_chars` | `200` | 注入时单条消息最大字符数，0 不截断 |
| `l1_max_memories_per_summary` | `10` | 每次总结写入 L2 的最大记忆条数 |

#### 遗忘算法

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `forgetting_lambda` | `0.1` | 近因性衰减系数 |
| `forgetting_threshold` | `0.3` | 遗忘阈值 |
| `forgetting_immediate_eviction_threshold` | `0.1` | 极端低分直接淘汰阈值 |
| `forgetting_llm_confirm_enable` | `false` | 启用 LLM 兜底确认遗忘 |
| `forgetting_llm_confirm_provider` | `""` | 确认使用的 Provider（空则使用默认） |
| `forgetting_llm_confirm_threshold` | `0.15` | 评分低于此值才触发 LLM 确认 |

#### L2 检索与去重

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `l2_similarity_threshold` | `0.90` | L2 去重相似度阈值 |
| `l2_query_rewrite_enable` | `true` | 启用 L2 检索查询改写 |
| `l2_query_rewrite_provider` | `""` | 查询改写使用的 Provider（空则使用默认） |
| `l2_query_rewrite_timeout_ms` | `3000` | 查询改写超时（毫秒） |

#### L3 知识图谱

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `entity_extraction_temperature` | `0.3` | 实体提取温度 |
| `type_merge_threshold` | `0.8` | 类型合并相似度阈值 |
| `node_confidence_threshold` | `0.3` | 节点最低置信度 |
| `edge_weight_decay_rate` | `0.01` | 边权重衰减率 |
| `forgetting_lambda_kg` | `0.01` | 知识图谱遗忘系数 |
| `forgetting_threshold_kg` | `0.2` | 知识图谱遗忘阈值 |
| `kg_retention_days` | `30` | 知识图谱保留天数 |
| `kuzu_query_timeout_ms` | `5000` | KuzuDB 查询超时 |

#### 梦境任务

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `dream_task_interval_hours` | `24` | 梦境任务执行间隔（小时） |
| `dream_consolidation_similarity_threshold` | `0.85` | 合并阶段相似度阈值 |
| `dream_consolidation_batch_size` | `10` | 合并阶段批次大小 |
| `dream_consolidation_scan_budget` | `500` | 合并阶段每轮扫描条数上限 |
| `dream_consolidation_query_batch_size` | `50` | 合并阶段查询批次大小 |
| `dream_consolidation_max_group_size` | `5` | 合并阶段最大分组大小 |
| `dream_temporal_anchor_batch_size` | `50` | 时间锚定阶段批次大小 |
| `dream_contradiction_similarity_floor` | `0.55` | 矛盾消解相似度下限 |
| `dream_contradiction_similarity_ceiling` | `0.85` | 矛盾消解相似度上限 |
| `dream_contradiction_max_groups` | `20` | 矛盾消解最大分组数 |
| `dream_pattern_sample_size` | `30` | 模式挖掘采样数 |
| `dream_pattern_min_confidence` | `"medium"` | 模式挖掘最低置信度 |
| `dream_knowledge_extract_min_unprocessed` | `10` | 知识提取最小未处理记忆数 |
| `dream_knowledge_extract_batch_size` | `20` | 知识提取批次大小 |
| `eviction_batch_size` | `100` | 遗忘清洗批次大小 |

#### 画像系统

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `profile_analysis_interval_hours` | `24` | 分析任务间隔（小时） |
| `profile_max_messages_for_analysis` | `50` | 分析时最大消息数 |
| `profile_enable_version_control` | `true` | 启用版本控制 |
| `profile_mid_update_interval_summaries` | `5` | 中期更新：每隔 N 次总结触发 |
| `profile_mid_update_interval_hours` | `24.0` | 中期更新：最短间隔（小时） |
| `profile_long_update_interval_hours` | `168.0` | 长期更新：最短间隔（小时，默认 7 天） |

#### 图片解析

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `image_parsing_timeout_ms` | `30000` | 图片解析超时（毫秒） |
| `image_parsing_max_size_kb` | `4096` | 最大图片大小（KB） |
| `image_parsing_supported_formats` | `"jpg,jpeg,png,gif,webp"` | 支持的图片格式 |
| `image_parsing_fallback_on_error` | `true` | 解析失败时是否入队原始消息 |
| `image_phash_enable` | `true` | 启用 pHash 感知哈希去重 |
| `image_phash_threshold` | `10` | pHash 汉明距离阈值（越小越严格） |
| `image_filter_enable` | `true` | 启用无效图过滤（纯色/过小） |
| `image_filter_min_size` | `16` | 最小图片尺寸（像素） |
| `image_filter_std_threshold` | `5.0` | 纯色检测标准差阈值 |
| `image_cache_cleanup_interval_hours` | `24` | 图片缓存清理间隔（小时） |

#### 输入清理

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `input_sanitizer_enable` | `true` | 启用 Prompt 注入过滤 |
| `input_sanitizer_max_length` | `10000` | 输入最大长度 |

#### LLM 工具

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `tool_memory_max_content_length` | `500` | 记忆内容最大长度 |
| `tool_correction_require_confirmation` | `false` | 修正需确认 |
| `tool_timeout_ms` | `2000` | Tool 调用超时 |
| `tool_read_max_results` | `10` | 读取记忆最大返回数 |

#### 性能与调试

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `chromadb_batch_size` | `100` | ChromaDB 批量写入大小 |
| `call_log_max_entries` | `100` | 调用日志最大保留条数 |
| `debug_mode` | `false` | 调试模式 |
| `verbose_logging` | `false` | 详细日志输出 |
| `log_level` | `"INFO"` | 日志级别 |
| `enable_context_logging` | `false` | 启用 LLM 上下文日志输出 |

## 常见问题（FAQ）

### 1. 为什么"记不住"或记忆效果不好？

- 确认 `l1_buffer.enable`、`l2_memory.enable`、`l3_kg.enable` 均为 `true`。
- 检查是否配置了可用的 LLM Provider，总结、提取、分析等核心功能依赖 LLM。
- 使用 `/iris_mem l2 stats` 查看记忆库是否有记录。
- 确认你查询的是同一会话（群聊记忆隔离时，不同群聊的记忆独立）。

### 2. 为什么会出现回复冲突或重复发言？

- 常见原因是与 AstrBot 自带上下文功能重叠。
- 建议关闭 AstrBot 同类能力，保留 `context_control.enable_conversation_cleanup = true`。

### 3. 搜索不到刚保存的记忆？

- 先用 `/iris_mem l2 stats` 看当前记忆库是否有记录。
- 再确认你查询的是同一会话（群聊记忆隔离时，不同群聊的记忆独立）。
- 可尝试更语义化的关键词，而不是只搜原句片段。
- 检查 `l2_memory.relevance_threshold` 是否过高。

### 4. Token 消耗太高怎么办？

- 降低 `l1_buffer.inject_queue_length`（如 30）。
- 降低 `l2_memory.top_k`（如 3～5）。
- 关闭不需要的功能（如 `l1_buffer.enable_image_parsing = false`）。
- 为不同任务配置不同的 Provider（使用轻量模型处理总结/提取等任务）。

### 5. 切换嵌入模型后检索变差或报维度问题？

- 不同模型维度可能不同（512/768/1024），切换后插件会自动重建记忆库，已有记忆将丢失。
- **切换前请务必备份记忆数据**，可通过 Web 管理界面导出。
- 建议在初期确定好嵌入模型后不要频繁更换。

### 6. `iris_mem` 指令无响应？

- 确认你已配置为管理员。使用 `/sid` 获取用户 ID，在 AstrBot WebUI 中添加管理员 ID。
- 确认指令格式正确：`/iris_mem <模块> <子指令>`。

### 7. 数据会上传到云端吗？

- 默认存储在本地（ChromaDB / KuzuDB / 本地文件）。
- 仅在你配置并调用外部 LLM 时，会向所选 Provider 发送必要文本。

### 8. 如何彻底清空所有插件数据？

使用管理员指令：

```
/iris_mem all clear --all
```

这会删除所有层级的记忆和画像数据。

### 9. L2 嵌入模型应该选 Provider 还是本地？

- **Provider（推荐）**：使用 AstrBot 配置的 Embedding Provider（如 OpenAI 兼容服务、Ollama 等），无需下载模型，不占用本地内存，适合大多数场景。
- **本地**：使用内置 `sentence-transformers` 模型，首次使用需下载约 96 MB 模型文件，运行时额外占用 200～500 MB 内存。适合无法访问外部 Embedding 服务的离线环境。
- 如果选择 Provider 模式但未配置可用的 Embedding Provider，插件会自动降级到本地模型。

## 其他注意事项

1. 私聊和群聊记忆可通过 `isolation_config` 配置隔离策略。
2. 敏感信息会进行输入清理（Prompt 注入过滤、输入长度限制）。
3. **切换嵌入模型或来源前请先导出备份记忆数据**，更换后向量维度可能改变导致记忆库重建。
4. 开启群聊画像隔离或 Bot 人格隔离后，切换配置会导致画像重建。
5. 重型组件（ChromaDB、KuzuDB）后台异步初始化，首次启动可能需要短暂等待。
6. L2 和 L3 数据量较大时会占用较多内存和磁盘，资源受限设备可考虑关闭 L3 或使用 Provider 嵌入。

## 三层记忆系统详解

本插件采用分层记忆架构，实现从短期到长期的记忆流转，针对群聊场景优化。

### L1 消息缓冲

**定位**：短期上下文管理，相当于"工作记忆"

**特性**：

- 三段式 FIFO 队列：L1-1（最新段）→ L1-2（主体段）→ L1-3（辅助段）
- L1-2 满时触发 LLM 总结，保守提取策略（宁缺毋滥）
- 总结时对每条记忆评估 high/medium/low 置信度
- 自动回填回复消息的内容和发送者信息

**流转**：

- L1-2 满时触发总结 → 写入 L2 记忆库
- 同时触发画像系统更新

### L2 记忆库

**定位**：中期向量记忆，基于 ChromaDB 语义检索

**嵌入模型**：

- **Provider 模式（默认）**：通过 AstrBot 的 Embedding Provider 生成向量，支持 OpenAI API 兼容服务（OpenAI、Ollama、硅基流动等），无需本地模型
- **本地模式**：使用 `sentence-transformers` 加载本地模型（bge-small-zh-v1.5、m3e-small 等），首次使用需下载模型文件
- Provider 不可用时自动降级到本地模式

**特性**：

- 向量检索 + 查询改写 + Token 预算控制
- 遗忘清洗：基于近因性、访问频率、置信度的遗忘评分算法
- 记忆合并：并查集连通分量检测相似记忆，LLM 智能合并
- LLM 兜底确认：极低评分记忆淘汰前可选 LLM 二次确认
- 低置信度标记：自动检测并标记低置信度数据

**遗忘评分算法**：

```
评分 = 近因性权重 × e^(-λ × 天数) + 访问频率权重 + 置信度权重
```

- 近因性衰减系数 `forgetting_lambda`（默认 0.1）
- 遗忘阈值 `forgetting_threshold`（默认 0.3）
- 极端低分直接淘汰阈值 `forgetting_immediate_eviction_threshold`（默认 0.1）

**流转**：

- 梦境任务 KG 提取 → 写入 L3 知识图谱
- LLM 请求时向量检索 → 注入上下文

### L3 知识图谱

**定位**：长期结构化知识，基于 KuzuDB 实体关系图谱

**特性**：

- LLM 从 L2 记忆中批量提取抽象实体和关系
- 类型白名单：12 种节点类型 + 14 种关系类型，优先使用白名单类型
- 图增强检索：基于 L2 记忆关联节点的路径扩展检索
- 节点淘汰：结构重要性（连接度）和验证度加权的遗忘评分
- 去重合并：同名同类型节点自动合并

**流转**：

- LLM 请求时图增强检索 → 注入上下文
- 梦境任务节点淘汰

### 画像系统

**定位**：用户/群聊特征画像，辅助 LLM 理解上下文

**特性**：

- **用户画像**：性格标签、兴趣、职业、语言风格、沟通偏好、情感基线、禁忌话题等
- **群聊画像**：群聊兴趣、氛围标签、核心特征、禁忌话题等
- **三层更新频率**：中期字段（按总结次数/时间触发）、长期字段（仅显著新信息时更新）
- **字段置信度**：每个字段独立追踪置信度和更新历史
- **自动注入**：LLM 请求前自动注入画像到上下文

### 梦境任务

**定位**：记忆的离线深度加工，6 阶段流水线

| 阶段 | 名称 | 说明 |
|------|------|------|
| 1 | 合并重复 | 归拢同一话题的碎片记忆 |
| 2 | 时间锚定 | 将相对时间表达（昨天、上周等）转换为绝对日期 |
| 3 | 矛盾消解 | 检测并解决记忆间的逻辑冲突 |
| 4 | 模式挖掘 | 发现隐含的行为规律和偏好模式 |
| 5 | 知识提取 | 从 L2 记忆提取实体和关系写入 L3 知识图谱 |
| 6 | 遗忘清洗 | 淘汰低价值记忆和图谱节点 |

每个阶段可通过配置独立启用/禁用。

### 数据流

```
用户消息 ──→ L1 Buffer (三段式 FIFO)
                  │
                  ├── L1-2 满时触发总结
                  │       │
                  │       ├──→ L2 记忆库 (ChromaDB 向量存储)
                  │       │       │
                  │       │       ├── LLM 请求时向量检索注入上下文
                  │       │       └── 梦境任务
                  │       │               ├── 合并重复
                  │       │               ├── 时间锚定
                  │       │               ├── 矛盾消解
                  │       │               ├── 模式挖掘
                  │       │               ├── 知识提取 ──→ L3 知识图谱 (KuzuDB)
                  │       │               │                       │
                  │       │               │                       ├── 图增强检索注入上下文
                  │       │               │                       └── 节点淘汰
                  │       │               └── 遗忘清洗
                  │       │
                  │       └──→ 画像系统 (用户/群聊画像更新)
                  │
                  └── LLM 请求时注入上下文
                          │
                          ├── L1 对话记录
                          ├── 用户/群聊画像
                          ├── L2 相关记忆
                          └── L3 知识图谱
```

### LLM 工具

为 LLM 提供 6 个主动记忆管理工具：

| 工具 | 功能 |
|------|------|
| `save_memory` | 保存重要记忆到 L2 记忆库 |
| `search_memory` | 从 L2 记忆库检索相关记忆，可选附带图谱上下文 |
| `correct_memory` | 修正错误记忆或幻觉，同时更新 L2 和 L3 |
| `save_knowledge` | 手动添加实体和关系到知识图谱 |
| `search_knowledge_graph` | 搜索知识图谱中的实体和关系 |
| `get_profile` | 获取用户或群聊画像信息 |

### 定时任务

| 任务 | 说明 | 默认间隔 |
|------|------|----------|
| 梦境任务 | 6 阶段记忆离线加工 | 24 小时 |
| 图片缓存清理 | 过期解析缓存清理 | 24 小时 |

## 文档与链接

- [AstrBot 主项目](https://github.com/AstrBotDevs/AstrBot)
- [插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)

## 许可证

AGPL-3.0

欢迎提交 Issue 和 Pull Request。
