"""
记忆相关 API 路由

提供L1/L2/L3三层记忆的访问接口：
- L1 Buffer: 消息缓冲列表
- L2 Memory: 记忆搜索
- L3 KG: 知识图谱数据
"""

from quart import Blueprint, jsonify, request
from iris_memory.web.auth import dashboard_auth
from iris_memory.core import get_component_manager, get_logger

logger = get_logger("web.memory")
memory_bp = Blueprint("memory", __name__)


@memory_bp.route("/l2/search", methods=["POST"])
@dashboard_auth.require_auth
async def search_l2_memory():
    """
    搜索 L2 记忆

    Request Body:
        {
            "query": "搜索关键词",
            "group_id": "群聊ID（可选）",
            "top_k": 10
        }

    Response:
        {
            "success": true,
            "results": [
                {
                    "id": "mem_xxx",
                    "content": "记忆内容",
                    "score": 0.95,
                    "metadata": {},
                    "timestamp": "2026-03-29T12:00:00",
                    "access_count": 3,
                    "last_access_time": "2026-04-01T10:00:00",
                    "confidence": 0.85,
                    "source": "summary",
                    "group_id": "group_123"
                }
            ]
        }
    """
    try:
        data = await request.get_json()
        query = data.get("query", "")
        group_id = data.get("group_id")
        top_k = data.get("top_k", 10)

        # 参数验证
        if not query:
            return jsonify({"success": False, "error": "搜索关键词不能为空"}), 400

        # 获取L2检索器
        manager = get_component_manager()
        l2_retriever = manager.get_component("l2_memory")

        if not l2_retriever or not l2_retriever.is_available:
            return jsonify({"success": False, "error": "L2 记忆库不可用"}), 503

        # 执行搜索
        results = await l2_retriever.retrieve(query, group_id, top_k)

        # 格式化响应
        formatted_results = [
            {
                "id": r.entry.id,
                "content": r.entry.content,
                "score": r.score,
                "metadata": r.entry.metadata,
                "timestamp": r.entry.metadata.get("timestamp"),
                "access_count": r.entry.metadata.get("access_count", 0),
                "last_access_time": r.entry.metadata.get("last_access_time"),
                "confidence": r.entry.metadata.get("confidence", 0.5),
                "source": r.entry.metadata.get("source"),
                "group_id": r.entry.metadata.get("group_id"),
            }
            for r in results
        ]

        logger.info(f"搜索L2记忆成功：查询='{query[:20]}...', 结果数={len(results)}")

        return jsonify({"success": True, "results": formatted_results})

    except Exception as e:
        logger.error(f"搜索 L2 记忆失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l2/latest", methods=["GET"])
@dashboard_auth.require_auth
async def get_latest_l2_memories():
    """
    获取最新的 L2 记忆

    Query Params:
        limit: 返回数量（默认 20，可选值：10, 20, 50, 100）
        group_id: 群聊ID（可选）
        sort_by: 排序字段（默认 timestamp，可选值：timestamp, access_count, confidence, last_access_time）
        sort_order: 排序方向（默认 desc，可选值：desc, asc）

    Response:
        {
            "success": true,
            "results": [
                {
                    "id": "mem_xxx",
                    "content": "记忆内容",
                    "score": 1.0,
                    "metadata": {},
                    "timestamp": "2026-03-29T12:00:00",
                    "access_count": 3,
                    "last_access_time": "2026-04-01T10:00:00",
                    "confidence": 0.85,
                    "source": "summary",
                    "group_id": "group_123"
                }
            ]
        }
    """
    try:
        limit = request.args.get("limit", default=20, type=int)
        group_id = request.args.get("group_id")
        sort_by = request.args.get("sort_by", default="timestamp")
        sort_order = request.args.get("sort_order", default="desc")

        valid_limits = [10, 20, 50, 100]
        if limit not in valid_limits:
            limit = 20

        valid_sort_fields = [
            "timestamp",
            "access_count",
            "confidence",
            "last_access_time",
        ]
        if sort_by not in valid_sort_fields:
            sort_by = "timestamp"

        if sort_order not in ("asc", "desc"):
            sort_order = "desc"

        manager = get_component_manager()
        l2_adapter = manager.get_component("l2_memory")

        if not l2_adapter or not l2_adapter.is_available:
            return jsonify({"success": False, "error": "L2 记忆库不可用"}), 503

        if group_id:
            all_entries = await l2_adapter.get_entries_by_group(group_id)
        else:
            all_entries = await l2_adapter.get_all_entries()

        raw_entries = []
        for entry in all_entries:
            meta = entry.metadata
            raw_entries.append(
                {
                    "id": entry.id,
                    "content": entry.content,
                    "score": 1.0,
                    "metadata": meta,
                    "timestamp": meta.get("timestamp"),
                    "access_count": meta.get("access_count", 0),
                    "last_access_time": meta.get("last_access_time"),
                    "confidence": meta.get("confidence", 0.5),
                    "source": meta.get("source"),
                    "group_id": meta.get("group_id"),
                }
            )

        def sort_key(entry):
            val = entry.get(sort_by)
            if val is None:
                if sort_by in ("access_count", "confidence"):
                    val = 0
                else:
                    val = ""
            if sort_by in ("access_count", "confidence") and isinstance(val, str):
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    val = 0
            return val

        raw_entries.sort(key=sort_key, reverse=(sort_order == "desc"))

        formatted_results = raw_entries[:limit]

        logger.info(
            f"获取最新L2记忆成功：limit={limit}, sort_by={sort_by}, sort_order={sort_order}, 结果数={len(formatted_results)}"
        )

        return jsonify({"success": True, "results": formatted_results})

    except Exception as e:
        logger.error(f"获取最新 L2 记忆失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l1/list", methods=["GET"])
@dashboard_auth.require_auth
async def list_l1_buffer():
    """
    获取 L1 缓冲列表

    Query Params:
        group_id: 群聊ID（可选）

    Response:
        {
            "success": true,
            "messages": [
                {
                    "role": "user",
                    "content": "消息内容",
                    "timestamp": "2026-03-29T12:00:00"
                }
            ],
            "count": 10
        }
    """
    try:
        group_id = request.args.get("group_id")

        # 获取L1缓冲
        manager = get_component_manager()
        l1_buffer = manager.get_component("l1_buffer")

        if not l1_buffer or not l1_buffer.is_available:
            return jsonify({"success": False, "error": "L1 缓冲不可用"}), 503

        # 获取消息列表
        messages = l1_buffer.get_context(group_id)

        formatted_messages = [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                "user_id": msg.source if hasattr(msg, "source") else None,
                "user_name": msg.metadata.get("user_name")
                if hasattr(msg, "metadata") and msg.metadata
                else None,
            }
            for msg in messages
        ]

        logger.info(f"获取L1缓冲成功：群聊={group_id}, 消息数={len(messages)}")

        return jsonify(
            {
                "success": True,
                "messages": formatted_messages,
                "count": len(formatted_messages),
            }
        )

    except Exception as e:
        logger.error(f"获取 L1 缓冲失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l1/queues", methods=["GET"])
@dashboard_auth.require_auth
async def list_l1_queues():
    """
    获取所有群聊的 L1 缓冲统计

    Response:
        {
            "success": true,
            "queues": [
                {
                    "group_id": "group_123",
                    "message_count": 10,
                    "total_tokens": 500
                }
            ]
        }
    """
    try:
        manager = get_component_manager()
        l1_buffer = manager.get_component("l1_buffer")

        if not l1_buffer or not l1_buffer.is_available:
            return jsonify({"success": False, "error": "L1 缓冲不可用"}), 503

        queues = l1_buffer.get_all_queues_stats()

        group_names: dict[str, str] = {}
        profile_storage = manager.get_component("profile")
        if profile_storage and profile_storage.is_available:
            try:
                from iris_memory.profile import GroupProfileManager

                group_manager = GroupProfileManager(profile_storage)
                for q in queues:
                    gid = q.get("group_id", "")
                    if gid and gid not in group_names:
                        try:
                            profile = await group_manager._storage.get_group_profile(
                                gid
                            )
                            group_names[gid] = (
                                profile.group_name
                                if profile and profile.group_name
                                else ""
                            )
                        except Exception:
                            group_names[gid] = ""
            except Exception as e:
                logger.debug(f"获取群聊名称失败: {e}")

        for q in queues:
            gid = q.get("group_id", "")
            q["group_name"] = group_names.get(gid, "")

        return jsonify({"success": True, "queues": queues})

    except Exception as e:
        logger.error(f"获取 L1 队列列表失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l3/graph", methods=["GET"])
@dashboard_auth.require_auth
async def get_l3_graph():
    """
    获取 L3 知识图谱数据（支持拓展）

    Query Params:
        node_id: 起始节点ID（可选，不指定则随机选择 Person 节点）
        depth: 拓展深度 1-3（可选，默认2）
        max_nodes: 最大节点数（可选，默认50）
        max_edges: 最大边数（可选，默认100）

    Response:
        {
            "success": true,
            "start_node": {...},
            "nodes": [...],
            "edges": [...]
        }
    """
    try:
        node_id = request.args.get("node_id")
        depth = request.args.get("depth", default=1, type=int)
        max_nodes = request.args.get("max_nodes", default=20, type=int)
        max_edges = request.args.get("max_edges", default=100, type=int)

        manager = get_component_manager()
        l3_adapter = manager.get_component("l3_kg")

        if not l3_adapter or not l3_adapter.is_available:
            return jsonify({"success": False, "error": "L3 知识图谱不可用"}), 503

        if not node_id:
            random_node = await l3_adapter.get_random_person_node()
            if random_node:
                node_id = random_node["id"]
            else:
                return jsonify(
                    {
                        "success": True,
                        "start_node": None,
                        "nodes": [],
                        "edges": [],
                        "message": "图谱中没有 Person 类型节点",
                    }
                )

        nodes, edges = await l3_adapter.expand_from_node(
            node_id=node_id, depth=depth, max_nodes=max_nodes, max_edges=max_edges
        )

        start_node = None
        for node in nodes:
            if node["id"] == node_id:
                start_node = node
                break

        formatted_nodes = [
            {
                "id": node["id"],
                "label": node.get("label", "Entity"),
                "name": node.get("name", node["id"]),
                "confidence": node.get("confidence", 0.5),
            }
            for node in nodes
        ]

        formatted_edges = [
            {
                "source": edge["source"],
                "target": edge["target"],
                "relation": edge.get("relation", "RELATED"),
            }
            for edge in edges
        ]

        logger.info(
            f"获取L3图谱成功：起始={node_id}, 深度={depth}, 节点={len(formatted_nodes)}, 边={len(formatted_edges)}"
        )

        return jsonify(
            {
                "success": True,
                "start_node": start_node,
                "nodes": formatted_nodes,
                "edges": formatted_edges,
            }
        )

    except Exception as e:
        logger.error(f"获取 L3 图谱失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l2/stats", methods=["GET"])
@dashboard_auth.require_auth
async def get_l2_stats():
    """
    获取 L2 记忆库统计信息

    Response:
        {
            "success": true,
            "stats": {
                "total_count": 1000,
                "group_count": 10
            }
        }
    """
    try:
        manager = get_component_manager()
        l2_retriever = manager.get_component("l2_memory")

        if not l2_retriever or not l2_retriever.is_available:
            return jsonify({"success": False, "error": "L2 记忆库不可用"}), 503

        stats = await l2_retriever.get_stats()

        return jsonify({"success": True, "stats": stats})

    except Exception as e:
        logger.error(f"获取 L2 统计失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l3/search/nodes", methods=["GET"])
@dashboard_auth.require_auth
async def search_l3_nodes():
    """
    搜索 L3 知识图谱节点

    Query Params:
        keyword: 搜索关键词
        limit: 返回数量（默认20）

    Response:
        {
            "success": true,
            "nodes": [
                {
                    "id": "node_id",
                    "label": "Person",
                    "name": "节点名称",
                    "content": "节点内容",
                    "confidence": 0.9
                }
            ]
        }
    """
    try:
        keyword = request.args.get("keyword", "")
        limit = request.args.get("limit", default=20, type=int)

        if not keyword:
            return jsonify({"success": False, "error": "搜索关键词不能为空"}), 400

        manager = get_component_manager()
        l3_adapter = manager.get_component("l3_kg")

        if not l3_adapter or not l3_adapter.is_available:
            return jsonify({"success": False, "error": "L3 知识图谱不可用"}), 503

        nodes = await l3_adapter.search_nodes(keyword, limit)

        logger.info(f"搜索L3节点成功：关键词='{keyword}', 结果数={len(nodes)}")

        return jsonify({"success": True, "nodes": nodes})

    except Exception as e:
        logger.error(f"搜索 L3 节点失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l3/search/edges", methods=["GET"])
@dashboard_auth.require_auth
async def search_l3_edges():
    """
    搜索 L3 知识图谱边

    Query Params:
        keyword: 搜索关键词
        limit: 返回数量（默认20）

    Response:
        {
            "success": true,
            "edges": [
                {
                    "source": {"id": "...", "label": "...", "name": "..."},
                    "target": {"id": "...", "label": "...", "name": "..."},
                    "relation": "关系类型",
                    "confidence": 0.9
                }
            ]
        }
    """
    try:
        keyword = request.args.get("keyword", "")
        limit = request.args.get("limit", default=20, type=int)

        if not keyword:
            return jsonify({"success": False, "error": "搜索关键词不能为空"}), 400

        manager = get_component_manager()
        l3_adapter = manager.get_component("l3_kg")

        if not l3_adapter or not l3_adapter.is_available:
            return jsonify({"success": False, "error": "L3 知识图谱不可用"}), 503

        edges = await l3_adapter.search_edges(keyword, limit)

        logger.info(f"搜索L3边成功：关键词='{keyword}', 结果数={len(edges)}")

        return jsonify({"success": True, "edges": edges})

    except Exception as e:
        logger.error(f"搜索 L3 边失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l2/delete", methods=["POST"])
@dashboard_auth.require_auth
async def delete_l2_entries():
    """
    删除指定的 L2 记忆条目

    Request Body:
        {
            "ids": ["mem_xxx", "mem_yyy"]
        }

    Response:
        {
            "success": true,
            "deleted_count": 2
        }
    """
    try:
        data = await request.get_json()
        ids = data.get("ids", [])

        if not ids:
            return jsonify(
                {"success": False, "error": "请提供要删除的记忆 ID 列表"}
            ), 400

        manager = get_component_manager()
        l2_adapter = manager.get_component("l2_memory")

        if not l2_adapter or not l2_adapter.is_available:
            return jsonify({"success": False, "error": "L2 记忆库不可用"}), 503

        success = await l2_adapter.delete_entries(ids)

        if success:
            logger.info(f"已删除 {len(ids)} 条 L2 记忆")
            return jsonify({"success": True, "deleted_count": len(ids)})
        else:
            return jsonify({"success": False, "error": "删除失败"}), 500

    except Exception as e:
        logger.error(f"删除 L2 记忆失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l2/update", methods=["POST"])
@dashboard_auth.require_auth
async def update_l2_entry():
    """
    更新 L2 记忆条目内容

    Request Body:
        {
            "id": "mem_xxx",
            "content": "新的记忆内容"
        }

    Response:
        {
            "success": true
        }
    """
    try:
        data = await request.get_json()
        memory_id = data.get("id", "")
        new_content = data.get("content", "")

        if not memory_id or not new_content:
            return jsonify({"success": False, "error": "请提供记忆 ID 和新内容"}), 400

        manager = get_component_manager()
        l2_adapter = manager.get_component("l2_memory")

        if not l2_adapter or not l2_adapter.is_available:
            return jsonify({"success": False, "error": "L2 记忆库不可用"}), 503

        success = await l2_adapter.update_content(memory_id, new_content)

        if success:
            logger.info(f"已更新 L2 记忆：{memory_id}")
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "更新失败，记忆可能不存在"}), 500

    except Exception as e:
        logger.error(f"更新 L2 记忆失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l3/nodes", methods=["GET"])
@dashboard_auth.require_auth
async def list_l3_nodes():
    """
    获取 L3 知识图谱节点列表

    Query Params:
        limit: 返回数量（默认 100）
        keyword: 搜索关键词（可选）

    Response:
        {
            "success": true,
            "nodes": [
                {
                    "id": "node_id",
                    "label": "Person",
                    "name": "节点名称",
                    "content": "节点内容",
                    "confidence": 0.9,
                    "group_id": "group_123",
                    "access_count": 5,
                    "created_time": "2026-03-29T12:00:00"
                }
            ]
        }
    """
    try:
        limit = request.args.get("limit", default=100, type=int)
        keyword = request.args.get("keyword", "")

        manager = get_component_manager()
        l3_adapter = manager.get_component("l3_kg")

        if not l3_adapter or not l3_adapter.is_available:
            return jsonify({"success": False, "error": "L3 知识图谱不可用"}), 503

        if keyword:
            nodes = await l3_adapter.search_nodes(keyword, limit)
        else:
            nodes = await l3_adapter.get_all_nodes(limit)

        logger.info(f"获取L3节点列表成功：关键词='{keyword}', 结果数={len(nodes)}")

        return jsonify({"success": True, "nodes": nodes})

    except Exception as e:
        logger.error(f"获取 L3 节点列表失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l3/edges", methods=["GET"])
@dashboard_auth.require_auth
async def list_l3_edges():
    """
    获取 L3 知识图谱关系列表

    Query Params:
        limit: 返回数量（默认 100）
        keyword: 搜索关键词（可选）

    Response:
        {
            "success": true,
            "edges": [
                {
                    "source": {"id": "...", "label": "...", "name": "..."},
                    "target": {"id": "...", "label": "...", "name": "..."},
                    "relation": "关系类型",
                    "confidence": 0.9,
                    "weight": 1.0
                }
            ]
        }
    """
    try:
        limit = request.args.get("limit", default=100, type=int)
        keyword = request.args.get("keyword", "")

        manager = get_component_manager()
        l3_adapter = manager.get_component("l3_kg")

        if not l3_adapter or not l3_adapter.is_available:
            return jsonify({"success": False, "error": "L3 知识图谱不可用"}), 503

        if keyword:
            edges = await l3_adapter.search_edges(keyword, limit)
        else:
            edges = await l3_adapter.get_all_edges(limit)

        logger.info(f"获取L3关系列表成功：关键词='{keyword}', 结果数={len(edges)}")

        return jsonify({"success": True, "edges": edges})

    except Exception as e:
        logger.error(f"获取 L3 关系列表失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l3/nodes/delete", methods=["POST"])
@dashboard_auth.require_auth
async def delete_l3_nodes():
    """
    删除指定的 L3 知识图谱节点

    Request Body:
        {
            "ids": ["node_id_1", "node_id_2"]
        }

    Response:
        {
            "success": true,
            "deleted_count": 2
        }
    """
    try:
        data = await request.get_json()
        ids = data.get("ids", [])

        if not ids:
            return jsonify(
                {"success": False, "error": "请提供要删除的节点 ID 列表"}
            ), 400

        manager = get_component_manager()
        l3_adapter = manager.get_component("l3_kg")

        if not l3_adapter or not l3_adapter.is_available:
            return jsonify({"success": False, "error": "L3 知识图谱不可用"}), 503

        deleted_count = await l3_adapter.evict_nodes(ids)

        logger.info(f"已删除 {deleted_count} 个 L3 节点")

        return jsonify({"success": True, "deleted_count": deleted_count})

    except Exception as e:
        logger.error(f"删除 L3 节点失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/l3/edges/delete", methods=["POST"])
@dashboard_auth.require_auth
async def delete_l3_edge():
    """
    删除指定的 L3 知识图谱关系

    Request Body:
        {
            "source_id": "源节点ID",
            "target_id": "目标节点ID",
            "relation": "关系类型"
        }

    Response:
        {
            "success": true
        }
    """
    try:
        data = await request.get_json()
        source_id = data.get("source_id", "")
        target_id = data.get("target_id", "")
        relation = data.get("relation", "")

        if not source_id or not target_id or not relation:
            return jsonify(
                {"success": False, "error": "请提供源节点ID、目标节点ID和关系类型"}
            ), 400

        manager = get_component_manager()
        l3_adapter = manager.get_component("l3_kg")

        if not l3_adapter or not l3_adapter.is_available:
            return jsonify({"success": False, "error": "L3 知识图谱不可用"}), 503

        success = await l3_adapter.delete_edge(source_id, target_id, relation)

        if success:
            logger.info(f"已删除 L3 关系：{source_id} -[{relation}]-> {target_id}")
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "删除失败，关系可能不存在"}), 500

    except Exception as e:
        logger.error(f"删除 L3 关系失败：{e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
