"""
Iris Chat Memory - L2 记忆库 FAISS + SQLite 适配器

实现 L2 记忆库的存储和检索功能，支持：
- FAISS 向量索引（IndexFlatIP，余弦相似度）
- SQLite 元数据存储（文档、元数据、ID 映射）
- 群聊隔离检索
- 人格隔离（独立目录）
- 去重检查
- 超时保护
- 自动降级
"""

import asyncio
import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import uuid

import numpy as np

from iris_memory.core import Component, get_logger, InitMode
from iris_memory.config import get_config
from .models import MemoryEntry, MemorySearchResult

logger = get_logger("l2_memory.adapter")

SUPPORTED_EMBEDDING_MODELS = {
    "BAAI/bge-small-zh-v1.5": {
        "dimensions": 512,
        "size_mb": 96,
        "description": "BGE v1.5 中文小模型（默认推荐）",
        "language": "zh",
    },
    "moka-ai/m3e-small": {
        "dimensions": 512,
        "size_mb": 96,
        "description": "M3E 中文小模型，s2s 能力强",
        "language": "zh",
    },
    "moka-ai/m3e-base": {
        "dimensions": 768,
        "size_mb": 409,
        "description": "M3E 中英双语，s2p 检索能力强",
        "language": "zh+en",
    },
    "BAAI/bge-base-zh-v1.5": {
        "dimensions": 768,
        "size_mb": 409,
        "description": "BGE v1.5 中文 base 模型，精度更高",
        "language": "zh",
    },
    "shibing624/text2vec-base-chinese": {
        "dimensions": 768,
        "size_mb": 409,
        "description": "text2vec 中文模型，语义匹配强",
        "language": "zh",
    },
    "all-MiniLM-L6-v2": {
        "dimensions": 384,
        "size_mb": 80,
        "description": "英文默认模型，中文效果差",
        "language": "en",
    },
}


class L2MemoryAdapter(Component):
    """L2 记忆库适配器

    使用 FAISS + SQLite 存储和检索记忆向量。

    Attributes:
        _index: FAISS 向量索引
        _db: SQLite 连接
        _embedding_provider: AstrBot Embedding Provider 实例
        _local_model: sentence-transformers 模型实例
        _persist_dir: 数据持久化目录
        _persona_id: 当前人格 ID
        _free_list: 已删除的可复用 FAISS 槽位
        _dirty: 索引是否需要保存
    """

    def __init__(self, persona_id: str = "default", context=None):
        super().__init__()
        self._index = None
        self._db: Optional[sqlite3.Connection] = None
        self._embedding_provider = None
        self._local_model = None
        self._actual_embedding_model: str = ""
        self._embedding_dimensions: int = 0
        self._embedding_source: str = "provider"
        self._persist_dir: Optional[Path] = None
        self._persona_id = persona_id
        self._context = context
        self._similarity_threshold = 0.90
        self._free_list: List[int] = []
        self._dirty = False
        self._db_lock = threading.Lock()
        self._init_mode = InitMode.BACKGROUND

    @property
    def name(self) -> str:
        return "l2_memory"

    # ========================================================================
    # 初始化与关闭
    # ========================================================================

    async def initialize(self) -> None:
        config = get_config()

        if not config.get("l2_memory.enable"):
            logger.info("L2 记忆库未启用，跳过初始化")
            self._is_available = False
            self._init_error = "L2 记忆库未启用"
            return

        try:
            import faiss  # noqa: F401 -- availability check
        except ImportError:
            raise ImportError(
                "faiss-cpu 未安装。请在 AstrBot 管理面板的插件依赖中添加 faiss-cpu，"
                "或在插件目录执行 pip install faiss-cpu"
            )

        try:
            self._persist_dir = config.data_dir / "faiss" / f"memory_{self._persona_id}"
            self._persist_dir.mkdir(parents=True, exist_ok=True)

            self._similarity_threshold = config.get("l2_similarity_threshold", 0.90)

            # 初始化嵌入源
            self._embedding_source = config.get(
                "l2_memory.embedding_source", "provider"
            )

            try:
                if self._embedding_source == "provider":
                    self._init_provider_embedding(config)
                else:
                    await self._init_local_embedding(config)
            except ImportError as emb_err:
                logger.error(
                    f"嵌入模型加载失败，L2 记忆库将不可用：{emb_err}\n"
                    f"  → 解决方法：在插件配置中将「嵌入模型来源」切换为 Provider，"
                    f"并在 AstrBot「模型」页面配置一个 Embedding 类型的 Provider"
                )
                self._is_available = False
                self._init_error = str(emb_err)
                return
            except Exception as emb_err:
                logger.error(
                    f"嵌入模型加载失败，L2 记忆库将不可用：{emb_err}\n"
                    f"  → 当前来源：{self._embedding_source}"
                    f"{'，请检查 Embedding Provider 是否已配置并可用' if self._embedding_source == 'provider' else ''}",
                    exc_info=True,
                )
                self._is_available = False
                self._init_error = f"嵌入模型加载失败：{emb_err}"
                return

            if not self._actual_embedding_model:
                self._actual_embedding_model = "unknown"

            # 确定维度：优先从 provider 获取，否则用已知模型参数，最后通过试算得到
            if not self._embedding_dimensions:
                self._embedding_dimensions = await self._detect_dimensions()

            # 加载或创建索引
            meta = self._load_meta()
            stored_model = meta.get("embedding_model", "")
            stored_dim = meta.get("embedding_dimensions", 0)

            needs_migration = False
            if stored_model and stored_model != self._actual_embedding_model:
                needs_migration = True
                logger.warning(
                    f"嵌入模型已变更：{stored_model} -> {self._actual_embedding_model}，"
                    f"开始自动迁移..."
                )
            elif (
                self._embedding_dimensions
                and stored_dim
                and self._embedding_dimensions != stored_dim
            ):
                needs_migration = True
                logger.warning(
                    f"嵌入维度已变更：{stored_dim} -> {self._embedding_dimensions}，"
                    f"开始自动迁移..."
                )

            if needs_migration:
                ok = await self._migrate_on_model_change(
                    self._actual_embedding_model, self._embedding_dimensions
                )
                if not ok:
                    logger.error(
                        "自动迁移失败，L2 记忆库不可用。\n"
                        "  → 解决方法：检查 Embedding Provider 配置是否变更，"
                        "或手动删除 data/faiss 目录后重启插件重建记忆库"
                    )
                    self._is_available = False
                    self._init_error = "自动迁移失败，旧数据与新嵌入模型不兼容"
                    return
            else:
                # 加载已有索引和数据
                await self._load_existing(stored_dim)
                # 补全元数据
                if not stored_model or (not stored_dim and self._embedding_dimensions):
                    self._save_meta()

            self._is_available = True

            count = self._count_db()
            logger.info(
                f"L2 记忆库初始化成功，persona: {self._persona_id}，"
                f"嵌入来源: {self._embedding_source}，"
                f"嵌入模型: {self._actual_embedding_model}，"
                f"维度: {self._embedding_dimensions}，"
                f"当前条目数: {count}"
            )

        except ImportError as e:
            logger.error(
                f"L2 记忆库初始化失败：{e}\n"
                f"  → 解决方法：请在 AstrBot 管理面板的插件依赖中安装缺少的依赖包"
            )
            self._is_available = False
            self._init_error = str(e)
        except Exception as e:
            logger.error(f"L2 记忆库初始化失败：{e}", exc_info=True)
            self._is_available = False
            self._init_error = f"L2 记忆库初始化失败：{e}"

    async def _load_existing(self, stored_dim: int) -> None:
        """加载已有的 FAISS 索引和 SQLite 数据库"""
        import faiss

        db_path = self._persist_dir / "metadata.db"
        self._db = self._open_db(db_path)

        index_path = self._persist_dir / "index.faiss"
        if index_path.exists() and self._count_db() > 0:
            self._index = faiss.read_index(str(index_path))
            actual_dim = self._index.d
            if stored_dim and actual_dim != stored_dim:
                logger.warning(
                    f"FAISS 索引维度({actual_dim})与元数据记录({stored_dim})不一致，"
                    f"以索引为准"
                )
            self._embedding_dimensions = actual_dim
        else:
            self._index = self._create_index(self._embedding_dimensions)

        # 加载 free-list
        meta = self._load_meta()
        self._free_list = meta.get("free_list", [])

    async def _detect_dimensions(self) -> int:
        """通过试算检测嵌入维度"""
        try:
            vecs = await self._embed(["test"])
            return len(vecs[0])
        except Exception:
            return 384

    def _create_index(self, dim: int):
        """创建 FAISS IndexIDMap(IndexFlatIP) 索引"""
        import faiss

        base = faiss.IndexFlatIP(dim)
        return faiss.IndexIDMap(base)

    def _open_db(self, path: Path) -> sqlite3.Connection:
        """打开 SQLite 数据库并确保表结构"""
        db = sqlite3.connect(str(path), check_same_thread=False)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                faiss_idx INTEGER PRIMARY KEY,
                memory_id TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                group_id TEXT,
                user_id TEXT,
                timestamp TEXT,
                kg_processed INTEGER DEFAULT 0
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_group_id ON memories(group_id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_kg_processed ON memories(kg_processed)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp)"
        )
        db.commit()
        return db

    def _load_meta(self) -> Dict[str, Any]:
        """加载 index_meta.json"""
        meta_path = self._persist_dir / "index_meta.json"
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_meta(self) -> None:
        """保存 index_meta.json"""
        meta = {
            "version": 1,
            "embedding_model": self._actual_embedding_model,
            "embedding_dimensions": self._embedding_dimensions,
            "persona_id": self._persona_id,
            "free_list": self._free_list,
        }
        meta_path = self._persist_dir / "index_meta.json"
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def shutdown(self) -> None:
        if self._dirty and self._index is not None:
            try:
                import faiss

                faiss.write_index(self._index, str(self._persist_dir / "index.faiss"))
                self._save_meta()
                logger.info("FAISS 索引已保存")
            except Exception as e:
                logger.error(f"保存 FAISS 索引失败：{e}")

        if self._db:
            try:
                self._db.close()
            except Exception:
                pass

        self._index = None
        self._db = None
        self._embedding_provider = None
        self._local_model = None
        self._actual_embedding_model = ""
        self._embedding_source = "provider"
        self._reset_state()
        logger.info("L2 记忆库已关闭")

    # ========================================================================
    # 嵌入源初始化
    # ========================================================================

    def _init_provider_embedding(self, config) -> None:
        """初始化 AstrBot Embedding Provider 嵌入源"""
        provider_id = config.get("l2_memory.embedding_provider", "")
        provider = None

        if provider_id:
            provider = self._get_embedding_provider_by_id(provider_id)
            if not provider:
                logger.warning(
                    f"指定的 Embedding Provider '{provider_id}' 不可用，"
                    f"请检查 ID 是否正确"
                )

        if not provider:
            provider = self._get_first_embedding_provider()

        if not provider:
            raise ImportError(
                "未找到可用的 AstrBot Embedding Provider\n"
                "  → 建议：在 AstrBot「模型」页面添加 Embedding 类型的 Provider"
            )

        model_name = getattr(provider, "model_name", None)
        if not model_name and hasattr(provider, "meta"):
            model_name = getattr(provider.meta, "model_name", None)
        model_name = model_name or provider_id

        dim = 0
        try:
            dim = provider.get_dim()
        except Exception:
            pass

        logger.info(
            f"使用 AstrBot Embedding Provider: {provider_id}，"
            f"模型: {model_name}，维度: {dim}"
        )

        self._embedding_provider = provider
        self._actual_embedding_model = f"provider:{provider_id}/{model_name}"
        self._embedding_dimensions = dim

    async def _init_local_embedding(self, config) -> None:
        """初始化本地 sentence-transformers 嵌入源"""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers 未安装。"
                "请在 AstrBot 管理面板安装插件依赖，"
                "或将嵌入来源切换为 Provider 模式"
            )

        model_name = config.get(
            "l2_memory.embedding_model", "BAAI/bge-small-zh-v1.5"
        )
        model_info = SUPPORTED_EMBEDDING_MODELS.get(model_name)
        dim = model_info["dimensions"] if model_info else 0

        if model_info:
            logger.info(
                f"加载嵌入模型：{model_name} "
                f"(维度={model_info['dimensions']}, "
                f"大小≈{model_info['size_mb']}MB, "
                f"{model_info['description']})"
            )
        else:
            logger.info(f"加载自定义嵌入模型：{model_name}")

        import os

        try:
            loop = asyncio.get_event_loop()
            self._local_model = await loop.run_in_executor(
                None, lambda: SentenceTransformer(model_name)
            )
        except Exception as first_err:
            logger.warning(f"加载嵌入模型 {model_name} 失败：{first_err}，尝试离线模式...")
            old_offline = os.environ.get("HF_HUB_OFFLINE")
            try:
                os.environ["HF_HUB_OFFLINE"] = "1"
                self._local_model = await loop.run_in_executor(
                    None, lambda: SentenceTransformer(model_name)
                )
                logger.info(f"离线模式加载嵌入模型 {model_name} 成功")
            except Exception as offline_err:
                raise ImportError(
                    f"加载嵌入模型 {model_name} 失败"
                    f"（在线：{first_err}，离线：{offline_err}）。"
                    f"请确保模型已下载，或切换为 Provider 模式"
                )
            finally:
                if old_offline is not None:
                    os.environ["HF_HUB_OFFLINE"] = old_offline
                else:
                    os.environ.pop("HF_HUB_OFFLINE", None)

        # 如果没有预知维度，从模型推断
        if not dim:
            dim = self._local_model.get_sentence_embedding_dimension()

        self._actual_embedding_model = model_name
        self._embedding_dimensions = dim

    def _get_embedding_provider_by_id(self, provider_id: str):
        try:
            if hasattr(self._context, "get_provider_by_id"):
                provider = self._context.get_provider_by_id(provider_id)
                if provider and hasattr(provider, "get_embeddings"):
                    return provider

            if hasattr(self._context, "provider_manager"):
                pm = self._context.provider_manager
                if hasattr(pm, "inst_map"):
                    p = pm.inst_map.get(provider_id)
                    if p and hasattr(p, "get_embeddings"):
                        return p
        except Exception as e:
            logger.debug(f"通过 ID 获取 Embedding Provider 失败: {e}")
        return None

    def _get_first_embedding_provider(self):
        try:
            if hasattr(self._context, "provider_manager"):
                pm = self._context.provider_manager
                if hasattr(pm, "embedding_provider_insts"):
                    providers = pm.embedding_provider_insts
                    if providers:
                        return providers[0]
                if hasattr(pm, "inst_map"):
                    for pid, p in pm.inst_map.items():
                        if hasattr(p, "get_embeddings"):
                            return p
        except Exception as e:
            logger.debug(f"获取 Embedding Provider 失败: {e}")
        return None

    # ========================================================================
    # 嵌入计算
    # ========================================================================

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """计算文本嵌入向量并 L2 归一化"""
        if self._embedding_source == "provider" and self._embedding_provider:
            vectors = await self._embedding_provider.get_embeddings(texts)
        elif self._local_model:
            loop = asyncio.get_event_loop()
            vectors = await loop.run_in_executor(
                None, lambda: self._local_model.encode(texts).tolist()
            )
        else:
            raise RuntimeError("没有可用的嵌入源")

        # L2 归一化，使内积 = 余弦相似度
        normalized = []
        for v in vectors:
            arr = np.array(v, dtype=np.float32)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            normalized.append(arr.tolist())

        return normalized

    # ========================================================================
    # 记忆存储
    # ========================================================================

    async def add_memory(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        skip_dedup: bool = False,
    ) -> Optional[str]:
        if not self._is_available:
            logger.warning("L2 记忆库不可用，跳过添加记忆")
            return None

        if metadata is None:
            metadata = {}

        if "timestamp" not in metadata:
            metadata["timestamp"] = datetime.now().isoformat()
        if "access_count" not in metadata:
            metadata["access_count"] = 0
        if "confidence" not in metadata:
            metadata["confidence"] = 0.5
        if "last_access_time" not in metadata:
            metadata["last_access_time"] = datetime.now().isoformat()

        try:
            if not skip_dedup:
                existing_id = await self._check_similarity(content)
                if existing_id:
                    logger.debug(f"发现相似记忆，跳过存储：{content[:50]}...")
                    return existing_id

            memory_id = f"mem_{uuid.uuid4().hex[:12]}"

            # 计算嵌入
            vectors = await self._embed([content])
            vector = vectors[0]

            # 分配 FAISS 槽位
            if self._free_list:
                faiss_idx = self._free_list.pop(0)
            else:
                faiss_idx = self._index.ntotal

            # 添加到 FAISS
            self._index.add_with_ids(
                np.array([vector], dtype=np.float32),
                np.array([faiss_idx], dtype=np.int64),
            )

            # 添加到 SQLite
            self._upsert_db(faiss_idx, memory_id, content, metadata)

            self._dirty = True
            logger.debug(f"已添加记忆：{memory_id}")
            return memory_id

        except Exception as e:
            logger.error(f"添加记忆失败：{e}", exc_info=True)
            return None

    async def _check_similarity(self, content: str) -> Optional[str]:
        try:
            vectors = await self._embed([content])
            vector = np.array([vectors[0]], dtype=np.float32)

            if self._index.ntotal == 0:
                return None

            scores, indices = self._index.search(vector, 1)
            if indices[0][0] < 0:
                return None

            score = float(scores[0][0])
            if score >= self._similarity_threshold:
                faiss_idx = int(indices[0][0])
                row = self._db_execute(
                    "SELECT memory_id FROM memories WHERE faiss_idx = ?",
                    (faiss_idx,),
                ).fetchone()
                if row:
                    return row[0]

            return None
        except Exception as e:
            logger.warning(f"相似度检查失败：{e}")
            return None

    # ========================================================================
    # 记忆检索
    # ========================================================================

    async def retrieve(
        self, query: str, group_id: Optional[str] = None, top_k: int = 10
    ) -> List[MemorySearchResult]:
        if not self._is_available:
            return []

        config = get_config()
        timeout_ms = config.get("l2_timeout_ms")
        timeout_sec = timeout_ms / 1000.0

        try:
            # 在主线程中计算嵌入（provider 模式避免 asyncio.run 开销）
            vector = await self._embed([query])
            vector_np = np.array([vector[0]], dtype=np.float32)

            loop = asyncio.get_event_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: self._search_with_vector(vector_np, group_id, top_k)
                ),
                timeout=timeout_sec,
            )
            return results
        except asyncio.TimeoutError:
            logger.warning(f"L2 记忆检索超时（{timeout_sec}s），跳过")
            return []
        except Exception as e:
            logger.error(f"L2 记忆检索失败：{e}", exc_info=True)
            return []

    def _search_with_vector(
        self, vector: np.ndarray, group_id: Optional[str], top_k: int
    ) -> List[MemorySearchResult]:
        if self._index.ntotal == 0:
            return []

        # IndexFlatIP 是暴力搜索，成本与 k 无关（总是全量扫描），
        # 所以 k 取 max(group_count, top_k) 确保过滤后有足够结果
        if group_id:
            row = self._db_execute(
                "SELECT COUNT(*) FROM memories WHERE group_id = ?", (group_id,)
            ).fetchone()
            group_count = row[0]
            if group_count == 0:
                return []
            n_probe = min(max(group_count, top_k), self._index.ntotal)
        else:
            n_probe = min(top_k, self._index.ntotal)

        scores, indices = self._index.search(vector, n_probe)

        results = []
        for i in range(len(indices[0])):
            faiss_idx = int(indices[0][i])
            if faiss_idx < 0:
                continue

            score = float(scores[0][i])
            row = self._db_execute(
                "SELECT memory_id, content, metadata, group_id FROM memories WHERE faiss_idx = ?",
                (faiss_idx,),
            ).fetchone()

            if not row:
                continue

            row_memory_id, row_content, row_metadata_json, row_group_id = row

            if group_id and row_group_id != group_id:
                continue

            entry = MemoryEntry(
                id=row_memory_id,
                content=row_content,
                metadata=json.loads(row_metadata_json),
            )
            results.append(
                MemorySearchResult(entry=entry, score=score, distance=1.0 - score)
            )

            if len(results) >= top_k:
                break

        return results

    def _batch_search_with_vectors(
        self, vector_matrix: np.ndarray, group_id: Optional[str], top_k: int
    ) -> List[List[MemorySearchResult]]:
        if self._index.ntotal == 0:
            return [[] for _ in range(len(vector_matrix))]

        if group_id:
            row = self._db_execute(
                "SELECT COUNT(*) FROM memories WHERE group_id = ?", (group_id,)
            ).fetchone()
            group_count = row[0]
            if group_count == 0:
                return [[] for _ in range(len(vector_matrix))]
            n_probe = min(max(group_count, top_k), self._index.ntotal)
        else:
            n_probe = min(top_k, self._index.ntotal)

        all_scores, all_indices = self._index.search(vector_matrix, n_probe)

        all_results: List[List[MemorySearchResult]] = []
        for q_idx in range(len(vector_matrix)):
            results: List[MemorySearchResult] = []
            for i in range(len(all_indices[q_idx])):
                faiss_idx = int(all_indices[q_idx][i])
                if faiss_idx < 0:
                    continue

                score = float(all_scores[q_idx][i])
                row = self._db_execute(
                    "SELECT memory_id, content, metadata, group_id FROM memories WHERE faiss_idx = ?",
                    (faiss_idx,),
                ).fetchone()

                if not row:
                    continue

                row_memory_id, row_content, row_metadata_json, row_group_id = row

                if group_id and row_group_id != group_id:
                    continue

                entry = MemoryEntry(
                    id=row_memory_id,
                    content=row_content,
                    metadata=json.loads(row_metadata_json),
                )
                results.append(
                    MemorySearchResult(entry=entry, score=score, distance=1.0 - score)
                )

                if len(results) >= top_k:
                    break

            all_results.append(results)

        return all_results

    async def batch_retrieve(
        self, queries: List[str], group_id: Optional[str] = None, top_k: int = 10
    ) -> List[List[MemorySearchResult]]:
        if not self._is_available or not queries:
            return [[] for _ in queries]

        config = get_config()
        base_timeout_ms = config.get("l2_timeout_ms")
        timeout_sec = base_timeout_ms / 1000.0 * max(1, len(queries) // 10 + 1)

        try:
            # 在主线程中计算嵌入（provider 模式避免 asyncio.run 开销）
            vectors = await self._embed(queries)
            vector_matrix = np.array(vectors, dtype=np.float32)
            # L2 归一化
            norms = np.linalg.norm(vector_matrix, axis=1, keepdims=True)
            norms = np.where(norms > 0, norms, 1.0)
            vector_matrix = vector_matrix / norms

            loop = asyncio.get_event_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: self._batch_search_with_vectors(vector_matrix, group_id, top_k)
                ),
                timeout=timeout_sec,
            )
            return results
        except asyncio.TimeoutError:
            logger.warning(
                f"批量检索超时（{timeout_sec:.1f}s），跳过 {len(queries)} 条查询"
            )
            return [[] for _ in queries]
        except Exception as e:
            logger.error(f"批量检索失败：{e}", exc_info=True)
            return [[] for _ in queries]

    # ========================================================================
    # 访问更新
    # ========================================================================

    async def update_access(self, memory_id: str) -> bool:
        if not self._is_available:
            return False

        try:
            with self._db_lock:
                row = self._db.execute(
                    "SELECT metadata FROM memories WHERE memory_id = ?", (memory_id,)
                ).fetchone()

                if not row:
                    logger.warning(f"记忆不存在：{memory_id}")
                    return False

                metadata = json.loads(row[0])
                metadata["access_count"] = metadata.get("access_count", 0) + 1
                metadata["last_access_time"] = datetime.now().isoformat()

                self._db.execute(
                    "UPDATE memories SET metadata = ? WHERE memory_id = ?",
                    (json.dumps(metadata, ensure_ascii=False), memory_id),
                )
                self._db.commit()
            logger.debug(f"记忆访问更新成功：{memory_id}")
            return True
        except Exception as e:
            logger.error(f"更新记忆访问失败：{e}", exc_info=True)
            return False

    # ========================================================================
    # 内容与元数据更新
    # ========================================================================

    async def update_metadata(self, memory_id: str, metadata: Dict[str, Any]) -> bool:
        if not self._is_available or not memory_id:
            return False

        try:
            group_id = metadata.get("group_id")
            user_id = metadata.get("user_id")
            timestamp = metadata.get("timestamp")
            kg_processed = 1 if metadata.get("kg_processed") else 0

            self._db_write(
                "UPDATE memories SET metadata = ?, group_id = ?, user_id = ?, timestamp = ?, kg_processed = ? WHERE memory_id = ?",
                (
                    json.dumps(metadata, ensure_ascii=False),
                    group_id,
                    user_id,
                    timestamp,
                    kg_processed,
                    memory_id,
                ),
            )
            return True
        except Exception as e:
            logger.error(f"更新元数据失败：{e}", exc_info=True)
            return False

    async def update_content(self, memory_id: str, new_content: str) -> bool:
        if not self._is_available or not memory_id:
            return False

        try:
            row = self._db_execute(
                "SELECT faiss_idx, metadata FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()

            if not row:
                logger.warning(f"记忆不存在：{memory_id}")
                return False

            faiss_idx, metadata_json = row
            metadata = json.loads(metadata_json)
            metadata["timestamp"] = datetime.now().isoformat()

            # 重新计算嵌入
            vectors = await self._embed([new_content])
            new_vector = np.array([vectors[0]], dtype=np.float32)

            # 替换 FAISS 中的向量：先移除再添加
            self._index.remove_ids(np.array([faiss_idx], dtype=np.int64))
            self._index.add_with_ids(new_vector, np.array([faiss_idx], dtype=np.int64))

            # 更新 SQLite
            self._upsert_db(faiss_idx, memory_id, new_content, metadata)

            self._dirty = True
            logger.info(f"已更新记忆内容：{memory_id}")
            return True
        except Exception as e:
            logger.error(f"更新记忆内容失败：{e}", exc_info=True)
            return False

    # ========================================================================
    # 删除操作
    # ========================================================================

    async def delete_entries(self, memory_ids: List[str]) -> bool:
        if not self._is_available or not memory_ids:
            return False

        try:
            with self._db_lock:
                # 获取对应的 faiss_idx
                placeholders = ",".join("?" for _ in memory_ids)
                rows = self._db.execute(
                    f"SELECT faiss_idx FROM memories WHERE memory_id IN ({placeholders})",
                    memory_ids,
                ).fetchall()

                if not rows:
                    return False

                faiss_indices = [row[0] for row in rows]

                # 从 FAISS 移除
                self._index.remove_ids(np.array(faiss_indices, dtype=np.int64))

                # 加入 free-list
                self._free_list.extend(faiss_indices)
                self._free_list.sort()

                # 从 SQLite 删除
                self._db.execute(
                    f"DELETE FROM memories WHERE memory_id IN ({placeholders})",
                    memory_ids,
                )
                self._db.commit()

            self._dirty = True
            logger.info(f"已删除 {len(faiss_indices)} 条记忆")
            return True
        except Exception as e:
            logger.error(f"删除记忆失败：{e}", exc_info=True)
            return False

    async def delete_collection(self) -> bool:
        if self._persist_dir is None:
            return False

        try:
            # 关闭数据库
            if self._db:
                self._db.close()
                self._db = None

            # 删除所有文件
            import shutil

            if self._persist_dir.exists():
                shutil.rmtree(self._persist_dir)

            self._index = None
            self._free_list = []
            self._dirty = False
            logger.info(f"已删除 collection: {self._persona_id}")
            return True
        except Exception as e:
            logger.error(f"删除 collection 失败：{e}", exc_info=True)
            return False

    # ========================================================================
    # 容量管理
    # ========================================================================

    async def get_entry_count(self) -> int:
        if not self._is_available or not self._db:
            return 0
        try:
            return self._count_db()
        except Exception as e:
            logger.error(f"获取条目数失败：{e}")
            return 0

    async def get_all_entries(self) -> List[MemoryEntry]:
        if not self._is_available or not self._db:
            return []

        try:
            rows = self._db_execute(
                "SELECT memory_id, content, metadata FROM memories"
            ).fetchall()

            return [
                MemoryEntry(
                    id=row[0],
                    content=row[1],
                    metadata=json.loads(row[2]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取所有条目失败：{e}")
            return []

    async def get_entries_by_group(self, group_id: str) -> List[MemoryEntry]:
        if not self._is_available or not self._db:
            return []

        try:
            rows = self._db_execute(
                "SELECT memory_id, content, metadata FROM memories WHERE group_id = ?",
                (group_id,),
            ).fetchall()

            return [
                MemoryEntry(
                    id=row[0],
                    content=row[1],
                    metadata=json.loads(row[2]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取群聊条目失败：{e}")
            return []

    async def get_entries_by_user(self, user_id: str) -> List[MemoryEntry]:
        if not self._is_available or not self._db:
            return []

        try:
            rows = self._db_execute(
                "SELECT memory_id, content, metadata FROM memories WHERE user_id = ?",
                (user_id,),
            ).fetchall()

            return [
                MemoryEntry(
                    id=row[0],
                    content=row[1],
                    metadata=json.loads(row[2]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取用户条目失败：{e}")
            return []

    async def get_stats(self) -> Dict[str, Any]:
        if not self._is_available or not self._db:
            return {"total_count": 0, "group_count": 0}

        try:
            row = self._db_execute(
                "SELECT COUNT(*), COUNT(DISTINCT group_id) FROM memories"
            ).fetchone()
            return {"total_count": row[0], "group_count": row[1]}
        except Exception as e:
            logger.error(f"获取L2统计失败：{e}", exc_info=True)
            return {"total_count": 0, "group_count": 0}

    async def delete_by_group(self, group_id: str) -> int:
        if not self._is_available:
            return 0

        try:
            with self._db_lock:
                rows = self._db.execute(
                    "SELECT faiss_idx FROM memories WHERE group_id = ?", (group_id,)
                ).fetchall()

                if not rows:
                    logger.debug(f"群聊 {group_id} 没有记忆记录")
                    return 0

                faiss_indices = [row[0] for row in rows]

                self._index.remove_ids(np.array(faiss_indices, dtype=np.int64))
                self._free_list.extend(faiss_indices)
                self._free_list.sort()

                self._db.execute(
                    "DELETE FROM memories WHERE group_id = ?", (group_id,)
                )
                self._db.commit()

            self._dirty = True
            logger.info(f"已删除群聊 {group_id} 的 {len(faiss_indices)} 条记忆")
            return len(faiss_indices)
        except Exception as e:
            logger.error(f"删除群聊记忆失败: {e}", exc_info=True)
            return 0

    async def delete_by_user(self, user_id: str, group_id: Optional[str] = None) -> int:
        if not self._is_available:
            return 0

        try:
            with self._db_lock:
                if group_id:
                    rows = self._db.execute(
                        "SELECT faiss_idx, memory_id, metadata FROM memories WHERE group_id = ?",
                        (group_id,),
                    ).fetchall()
                else:
                    rows = self._db.execute(
                        "SELECT faiss_idx, memory_id, metadata FROM memories"
                    ).fetchall()

                if not rows:
                    return 0

                ids_to_delete = []
                faiss_indices_to_delete = []
                for faiss_idx, memory_id, metadata_json in rows:
                    metadata = json.loads(metadata_json)
                    active_users = metadata.get("active_users", "")
                    if active_users:
                        users = [u.strip() for u in active_users.split(",") if u.strip()]
                        if user_id in users:
                            ids_to_delete.append(memory_id)
                            faiss_indices_to_delete.append(faiss_idx)

                if not ids_to_delete:
                    logger.debug(f"用户 {user_id} 没有记忆记录")
                    return 0

                self._index.remove_ids(np.array(faiss_indices_to_delete, dtype=np.int64))
                self._free_list.extend(faiss_indices_to_delete)
                self._free_list.sort()

                placeholders = ",".join("?" for _ in ids_to_delete)
                self._db.execute(
                    f"DELETE FROM memories WHERE memory_id IN ({placeholders})",
                    ids_to_delete,
                )
                self._db.commit()

            self._dirty = True
            logger.info(f"已删除用户 {user_id} 的 {len(ids_to_delete)} 条记忆")
            return len(ids_to_delete)
        except Exception as e:
            logger.error(f"删除用户记忆失败: {e}", exc_info=True)
            return 0

    async def delete_all(self) -> int:
        if not self._is_available:
            return 0

        try:
            count = self._count_db()
            if count == 0:
                return 0

            # 重建空索引
            self._index = self._create_index(self._embedding_dimensions)

            self._db_write("DELETE FROM memories")

            self._free_list = []
            self._dirty = True
            logger.info(f"已删除所有记忆，共 {count} 条")
            return count
        except Exception as e:
            logger.error(f"删除所有记忆失败: {e}", exc_info=True)
            return 0

    async def evict_memories(self, memory_ids: List[str]) -> int:
        if not self._is_available or not memory_ids:
            return 0

        try:
            placeholders = ",".join("?" for _ in memory_ids)
            docs = self._db_execute(
                f"SELECT content FROM memories WHERE memory_id IN ({placeholders})",
                memory_ids,
            ).fetchall()

            success = await self.delete_entries(memory_ids)

            if success and docs:
                logger.info(
                    f"已淘汰 {len(memory_ids)} 条记忆：\n"
                    + "\n".join(f"  - {doc[0][:100]}..." for doc in docs[:5])
                )
                return len(memory_ids)
            return 0
        except Exception as e:
            logger.error(f"淘汰记忆失败：{e}", exc_info=True)
            return 0

    # ========================================================================
    # 知识图谱处理相关
    # ========================================================================

    async def get_unprocessed_count(self) -> int:
        if not self._is_available or not self._db:
            return 0

        try:
            row = self._db_execute(
                "SELECT COUNT(*) FROM memories WHERE kg_processed = 0"
            ).fetchone()
            return row[0]
        except Exception as e:
            logger.error(f"获取未处理记忆数量失败: {e}")
            return 0

    async def get_unprocessed_memories(self, limit: int = 20) -> List[MemoryEntry]:
        if not self._is_available or not self._db:
            return []

        try:
            rows = self._db_execute(
                "SELECT memory_id, content, metadata FROM memories WHERE kg_processed = 0 LIMIT ?",
                (limit,),
            ).fetchall()

            return [
                MemoryEntry(
                    id=row[0],
                    content=row[1],
                    metadata=json.loads(row[2]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取未处理记忆失败: {e}")
            return []

    async def mark_memories_processed(self, memory_ids: List[str]) -> bool:
        if not self._is_available or not memory_ids:
            return False

        try:
            with self._db_lock:
                for memory_id in memory_ids:
                    row = self._db.execute(
                        "SELECT metadata FROM memories WHERE memory_id = ?", (memory_id,)
                    ).fetchone()
                    if not row:
                        continue

                    metadata = json.loads(row[0])
                    metadata["kg_processed"] = True

                    self._db.execute(
                        "UPDATE memories SET metadata = ?, kg_processed = 1 WHERE memory_id = ?",
                        (json.dumps(metadata, ensure_ascii=False), memory_id),
                    )

                self._db.commit()
            logger.info(f"已标记 {len(memory_ids)} 条记忆为已处理")
            return True
        except Exception as e:
            logger.error(f"标记记忆失败: {e}", exc_info=True)
            return False

    async def get_latest_memories(
        self, limit: int = 20, group_id: Optional[str] = None
    ) -> List[MemorySearchResult]:
        if not self._is_available:
            return []

        try:
            if group_id:
                rows = self._db_execute(
                    "SELECT memory_id, content, metadata FROM memories WHERE group_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (group_id, limit),
                ).fetchall()
            else:
                rows = self._db_execute(
                    "SELECT memory_id, content, metadata FROM memories ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            return [
                MemorySearchResult(
                    entry=MemoryEntry(
                        id=row[0],
                        content=row[1],
                        metadata=json.loads(row[2]),
                    ),
                    score=1.0,
                    distance=0.0,
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取最新记忆失败: {e}", exc_info=True)
            return []

    # ========================================================================
    # 模型迁移
    # ========================================================================

    async def _migrate_on_model_change(
        self, new_model: str, new_dim: int
    ) -> bool:
        from .io import MemoryExporter, MemoryImporter

        old_count = self._count_db()
        if old_count == 0:
            # 空库，直接创建新索引
            self._index = self._create_index(new_dim)
            self._embedding_dimensions = new_dim
            self._save_meta()
            return True

        logger.info(
            f"开始迁移 {old_count} 条记忆"
            f"（模型: {new_model}，维度: {new_dim}）"
        )

        backup_path = self._persist_dir / "_migration_backup.json"

        try:
            # 1. 导出所有记忆
            exporter = MemoryExporter(self)
            export_stats = await exporter.export_all(backup_path)
            logger.info(
                f"迁移步骤 1/4：导出完成，"
                f"共 {export_stats.total_count} 条，导出 {export_stats.exported_count} 条"
            )

            if export_stats.exported_count == 0:
                logger.warning("导出 0 条记忆，跳过迁移")
                backup_path.unlink(missing_ok=True)
                return False

            # 2. 删除旧数据
            deleted = await self.delete_collection()
            if not deleted:
                logger.error("迁移步骤 2/4：删除旧数据失败")
                return False
            logger.info("迁移步骤 2/4：已删除旧数据")

            # 3. 重新初始化（使用新模型）
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            db_path = self._persist_dir / "metadata.db"
            self._db = self._open_db(db_path)
            self._index = self._create_index(new_dim)
            self._embedding_dimensions = new_dim
            self._free_list = []
            self._save_meta()
            logger.info("迁移步骤 3/4：已创建新索引")

            # 4. 重新导入记忆
            importer = MemoryImporter(self)
            import_stats = await importer.import_from_file(
                backup_path, skip_duplicates=False
            )
            logger.info(
                f"迁移步骤 4/4：导入完成，"
                f"共 {import_stats.total_count} 条，导入 {import_stats.imported_count} 条，"
                f"跳过 {import_stats.skipped_count} 条，错误 {import_stats.error_count} 条"
            )

            backup_path.unlink(missing_ok=True)

            success = import_stats.imported_count > 0
            if success:
                logger.info(
                    f"迁移成功：{export_stats.exported_count} -> {import_stats.imported_count} 条"
                )
            else:
                logger.error("迁移后导入 0 条记忆，迁移失败")

            return success

        except Exception as e:
            logger.error(f"迁移过程异常：{e}", exc_info=True)

            # 尝试恢复
            if self._index is None and backup_path.exists():
                try:
                    self._persist_dir.mkdir(parents=True, exist_ok=True)
                    db_path = self._persist_dir / "metadata.db"
                    self._db = self._open_db(db_path)
                    self._index = self._create_index(new_dim)
                    self._embedding_dimensions = new_dim
                    self._save_meta()

                    importer = MemoryImporter(self)
                    await importer.import_from_file(backup_path, skip_duplicates=False)
                    logger.info("已从备份恢复数据")
                except Exception as restore_err:
                    logger.error(f"恢复数据失败：{restore_err}", exc_info=True)

            backup_path.unlink(missing_ok=True)
            return False

    # ========================================================================
    # 内部辅助
    # ========================================================================

    def _db_execute(self, sql: str, params=()):
        """线程安全的 DB 执行（用于 SELECT）"""
        with self._db_lock:
            return self._db.execute(sql, params)

    def _db_write(self, sql: str, params=()):
        """线程安全的 DB 写入（INSERT/UPDATE/DELETE + COMMIT）"""
        with self._db_lock:
            self._db.execute(sql, params)
            self._db.commit()

    def _count_db(self) -> int:
        if not self._db:
            return 0
        with self._db_lock:
            row = self._db.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0]

    def _upsert_db(
        self,
        faiss_idx: int,
        memory_id: str,
        content: str,
        metadata: Dict[str, Any],
    ) -> None:
        """插入或更新 SQLite 记录"""
        group_id = metadata.get("group_id")
        user_id = metadata.get("user_id")
        timestamp = metadata.get("timestamp")
        kg_processed = 1 if metadata.get("kg_processed") else 0
        metadata_json = json.dumps(metadata, ensure_ascii=False)

        with self._db_lock:
            self._db.execute(
                """INSERT OR REPLACE INTO memories
                   (faiss_idx, memory_id, content, metadata, group_id, user_id, timestamp, kg_processed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    faiss_idx,
                    memory_id,
                    content,
                    metadata_json,
                    group_id,
                    user_id,
                    timestamp,
                    kg_processed,
                ),
            )
            self._db.commit()
