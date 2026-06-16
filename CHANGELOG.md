# 更新日志 (CHANGELOG)

本项目所有重要变更均会记录于此文件。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 安全

- **修复图片 URL 的 SSRF 漏洞**：图片可达性检查新增主机安全校验（仅允许 http/https，通过 DNS 解析拒绝私网 / 环回 / 链路本地 / 云元数据等非全局地址），并禁用自动重定向，防止恶意用户构造图片 URL 探测内网。
- **修复跨群隔离越权**：
  - `save_knowledge` 工具现在按群记忆隔离绑定 `group_id`，与 `search_knowledge_graph` 对齐，避免跨群写入污染其他群的知识图谱；
  - `correct_memory` 的群隔离校验改用正确的记忆隔离配置键 `enable_group_memory_isolation`。
- **修复异常信息泄露**：Web API 与管理指令不再把 `str(e)`（可能含文件路径、SQL/Cypher 片段）回显给客户端，统一返回通用错误消息，详情仅写入服务日志。

### 修复

- **`correct_memory` 误删与数据丢失**：原先用语义检索定位 `memory_id`（几乎必然误命中不相关记忆）、且「先删后写」无回滚。现改为按 ID 精确查询（L2 adapter 新增 `get_entry_by_id`）+「先写后删」，确保写入失败时原记忆不丢失。
- **画像并发丢失更新**：引入 `@profile_lock` 装饰器，按 (persona, group, user) 命名空间串行化所有画像「读-改-写」操作；画像索引更新加独立 `_index_lock`。
- **L2 记忆去重竞态（TOCTOU）**：去重检查与 FAISS / SQLite 写入并入同一锁临界区（新增 `_find_similar_unlocked`），消除「检查通过→释放锁→另一并发写入→重新取锁」的竞态，同时避免原先的重复嵌入计算。
- **图片解析任务泄漏**：超时取消的 pending 任务现被正确 `await`，避免任务泄漏与「Task was destroyed but it is pending」警告，确保 httpx 连接及时回收。
- **图片解析配额静默耗尽**：新增配额退还机制（`QuotaStatus.release` / `ImageQuotaManager.release_quota`），解析失败 / 跳过 / 超时后按实际失败数回补预扣配额。
- **组件系统状态重建竞态**：`SystemStatus` 改为先在局部构建完整对象再原子替换，避免后台组件并发完成初始化时读到半重建状态（如某组件已就绪却被报不可用）。
- **初始化异常静默降级**：`initialize_components` 在异常路径下仍尝试启动不依赖后台组件的定时任务，避免调度任务完全不注册。
- **`ImageCacheManager` 索引竞态**：缓存元数据索引（`hashes` 列表）的「读-改-写」加 `_lock` 保护，避免并发丢失更新。
- **L2 `delete_collection` 未持锁**：数据库关闭与目录清理纳入 `_lock` 保护，避免与并发检索 / 写入交错触发 SQLite 错误。
- **Dream 模块逻辑错误**：
  - 矛盾消解的 `NO_CONFLICT` 判定改为前缀匹配，避免正文包含该子串时误判为无矛盾；
  - 模式挖掘启用此前被忽略的 `dream_pattern_min_confidence` 配置阈值过滤低置信度模式。
- **Token 预算估算偏小**：L2 检索的 Token 估算改用 `count_tokens`，修正原先 `len//2+1` 对中文严重偏小导致预算超用。
- **指令误触发**：`/iris_mem` 指令前缀改用单词边界匹配，避免正文出现「iris_memory」等子串被误判为指令。

### 变更

- **统一原子持久化**：新增 `iris_memory/utils/persistence.py`（写入临时文件 → `fsync` → `os.replace`），替换 L2 导出 / 导入、隐藏配置、L2 索引元数据等处此前的非原子覆盖写，避免写入中途崩溃导致文件截断与数据丢失（部分加载逻辑此前会静默丢弃全部数据回到默认）。

### 开发与质量

- `requirements.txt` 修正：移除代码未使用的 `PyJWT`，补充实际依赖但未声明的 `httpx`。
- 全量通过 `ruff check` 与 `ruff format`（共修复 62 处 lint 问题）。
- 新增与本次改动的代码通过 `pyright` 类型检查（0 错误）。
- 单元测试与组件测试 **617 项全部通过**。

### 已知技术债

- 全项目 `pyright` 仍有约 195 个既有类型标注告警（Optional 未判空、参数类型、Dict 当对象访问等），为长期累积、不影响运行时，将作为独立技术债迭代。
