"""L3 知识图谱实体提取器测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil

from iris_memory.l3_kg import (
    EntityExtractor,
    GraphNode,
    GraphEdge,
    ExtractionResult,
)
from iris_memory.config import init_config


class TestEntityExtractor:
    """EntityExtractor 测试"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def mock_llm_manager(self):
        """创建模拟 LLM 管理器"""
        manager = MagicMock()
        manager.generate_direct = AsyncMock()
        manager.is_available = True
        return manager

    @pytest.fixture
    def extractor(self, mock_llm_manager, temp_dir):
        from unittest.mock import Mock

        astrbot_config = Mock()
        astrbot_config.__getitem__ = Mock(
            return_value={"enable": True, "enable_type_whitelist": True}
        )
        astrbot_config.__contains__ = Mock(return_value=True)
        init_config(astrbot_config, temp_dir)

        return EntityExtractor(mock_llm_manager)

    def test_build_extraction_prompt(self, extractor):
        """测试构建提取 prompt"""
        text = "Alice 和 Bob 讨论了 AI 技术"

        prompt = extractor._build_extraction_prompt(text)

        # 验证 prompt 包含必要内容
        assert "Alice 和 Bob 讨论了 AI 技术" in prompt
        assert "可用节点类型" in prompt
        assert "可用关系类型" in prompt
        assert "Person" in prompt  # 白名单中的类型
        assert "KNOWS" in prompt  # 白名单中的关系

    def test_build_extraction_prompt_without_whitelist(self, extractor):
        """测试不使用白名单的 prompt"""
        from unittest.mock import patch

        with patch.object(extractor.config, "get", return_value=False):
            text = "Alice 和 Bob 讨论了 AI 技术"
            prompt = extractor._build_extraction_prompt(text)

            assert "可用节点类型" not in prompt

    @pytest.mark.asyncio
    async def test_parse_extraction_result_success(self, extractor):
        """测试解析成功的提取结果"""
        llm_response = """```json
{
  "nodes": [
    {
      "label": "Person",
      "name": "Alice",
      "content": "软件工程师",
      "confidence": 0.9
    },
    {
      "label": "Person",
      "name": "Bob",
      "content": "数据科学家",
      "confidence": 0.85
    }
  ],
  "edges": [
    {
      "source_name": "Alice",
      "target_name": "Bob",
      "relation_type": "KNOWS",
      "confidence": 0.8
    }
  ],
  "extraction_confidence": 0.85
}
```"""

        context = {"group_id": "group_123", "source_memory_id": "mem_456"}

        result = extractor._parse_extraction_result(llm_response, context)

        # 验证结果
        assert not result.is_empty()
        assert len(result.nodes) == 2
        assert len(result.edges) == 1
        assert result.extraction_confidence == 0.85

        # 验证节点
        alice_node = result.nodes[0]
        assert alice_node.label == "Person"
        assert alice_node.name == "Alice"
        assert alice_node.confidence == 0.9
        assert alice_node.group_id == "group_123"

        # 验证边
        edge = result.edges[0]
        assert edge.relation_type == "KNOWS"
        assert edge.confidence == 0.8

    @pytest.mark.asyncio
    async def test_parse_extraction_result_empty(self, extractor):
        """测试解析空的提取结果"""
        llm_response = """```json
{
  "nodes": [],
  "edges": [],
  "extraction_confidence": 0.5
}
```"""

        result = extractor._parse_extraction_result(llm_response, {})

        assert result.is_empty()
        assert len(result.nodes) == 0
        assert len(result.edges) == 0

    @pytest.mark.asyncio
    async def test_parse_extraction_result_invalid_json(self, extractor):
        """测试解析无效 JSON"""
        llm_response = "这不是 JSON 格式"

        result = extractor._parse_extraction_result(llm_response, {})

        # 应该返回空结果
        assert result.is_empty()

    @pytest.mark.asyncio
    async def test_extract_from_text_success(self, extractor, mock_llm_manager):
        """测试完整的提取流程"""
        # 模拟 LLM 响应
        mock_llm_manager.generate_direct.return_value = """{
  "nodes": [
    {
      "label": "Person",
      "name": "Alice",
      "content": "软件工程师",
      "confidence": 0.9
    }
  ],
  "edges": [],
  "extraction_confidence": 0.9
}"""

        text = "Alice 是一名软件工程师，她喜欢编程"
        context = {"group_id": "group_123"}

        result = await extractor.extract_from_text(text, context)

        mock_llm_manager.generate_direct.assert_called_once()

        # 验证结果
        assert not result.is_empty()
        assert len(result.nodes) == 1
        assert result.nodes[0].name == "Alice"

    @pytest.mark.asyncio
    async def test_extract_from_text_with_llm_error(self, extractor, mock_llm_manager):
        """测试 LLM 调用失败"""
        # 模拟 LLM 抛出异常
        mock_llm_manager.generate_direct.side_effect = Exception("LLM 调用失败")

        text = "测试文本"
        result = await extractor.extract_from_text(text, {})

        # 应该返回空结果
        assert result.is_empty()

    @pytest.mark.asyncio
    async def test_extract_from_text_creates_valid_ids(
        self, extractor, mock_llm_manager
    ):
        """测试提取结果生成有效 ID"""
        mock_llm_manager.generate_direct.return_value = """{
  "nodes": [
    {
      "label": "Person",
      "name": "Alice",
      "content": "软件工程师",
      "confidence": 0.9
    }
  ],
  "edges": [],
  "extraction_confidence": 0.9
}"""

        result = await extractor.extract_from_text("测试", {})

        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.id != ""
        assert node.id.startswith("person_")

    @pytest.mark.asyncio
    async def test_extract_from_text_handles_dynamic_types(
        self, extractor, mock_llm_manager
    ):
        """测试动态类型处理"""
        # 使用不在白名单中的类型
        mock_llm_manager.generate_direct.return_value = """{
  "nodes": [
    {
      "label": "CustomType",
      "name": "CustomEntity",
      "content": "自定义实体",
      "confidence": 0.8
    }
  ],
  "edges": [
    {
      "source_name": "CustomEntity",
      "target_name": "CustomEntity",
      "relation_type": "CUSTOM_RELATION",
      "confidence": 0.7
    }
  ],
  "extraction_confidence": 0.75
}"""

        result = await extractor.extract_from_text("测试", {})

        assert len(result.nodes) == 1
        assert result.nodes[0].label == "CustomType"

        assert len(result.edges) == 1
        assert result.edges[0].relation_type == "CUSTOM_RELATION"

    def test_parse_source_memory_ids_joined_by_comma(self, extractor):
        """回归：source_memory_ids 列表应全部用逗号拼接，而非仅取 [0]

        此前 node.source_memory_id 仅取 context["source_memory_ids"][0]，
        导致多来源记忆的引用丢失。修复后用 ",".join 拼接全部 ID。
        """
        llm_response = """{
  "nodes": [
    {
      "label": "Person",
      "name": "Alice",
      "content": "软件工程师",
      "confidence": 0.9
    }
  ],
  "edges": [],
  "extraction_confidence": 0.9
}"""

        context = {"group_id": "group_123", "source_memory_ids": ["mem_1", "mem_2"]}

        result = extractor._parse_extraction_result(llm_response, context)

        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.source_memory_id == "mem_1,mem_2"

    def test_filter_low_quality_removes_subjectless_nodes(self, extractor):
        """回归：_filter_low_quality 降级无 Person 关联的主体绑定节点

        Preference/Trait/Belief/Goal/Skill 节点描述的是"某人的属性"，
        若没有边连接到 Person 节点则成为无主节点（如"有特定角色偏好"
        不知道是谁的偏好）。此前硬删除会误伤有用信息，现改为降级置信度
        并标记 orphaned_subject，交由梦境遗忘清洗按综合评分处理。

        场景：
        - Person 节点 "张三"（应保留，非主体绑定类型）
        - Preference 节点 "角色偏好"（无 Person 边，应被降级标记）
        - Trait 节点 "性格开朗"（有 Person -> HAS_TRAIT 边，应保留原置信度）
        """
        # 构建 Person 节点
        person = GraphNode(
            id="",
            label="Person",
            name="张三",
            content="一个用户",
            confidence=0.9,
        )
        person.id = person.generate_id()

        # 无 Person 关联的 Preference 节点（应被降级标记，不删除）
        preference = GraphNode(
            id="",
            label="Preference",
            name="角色偏好",
            content="有特定角色偏好",
            confidence=0.9,
        )
        preference.id = preference.generate_id()

        # 有 Person 关联的 Trait 节点（应保留原置信度）
        trait = GraphNode(
            id="",
            label="Trait",
            name="性格开朗",
            content="性格开朗",
            confidence=0.9,
        )
        trait.id = trait.generate_id()

        # Person -> Trait 的边（让 Trait 通过主体关联检查）
        edge = GraphEdge(
            source_id=person.id,
            target_id=trait.id,
            relation_type="HAS_TRAIT",
            confidence=0.8,
        )

        result = ExtractionResult(
            nodes=[person, preference, trait],
            edges=[edge],
            extraction_confidence=0.85,
        )

        filtered = extractor._filter_low_quality(result)

        node_names = {n.name for n in filtered.nodes}

        # 所有节点都保留（不硬删除）
        assert "性格开朗" in node_names
        assert "张三" in node_names
        assert "角色偏好" in node_names

        # Preference 节点被降级置信度并标记
        pref_node = next(n for n in filtered.nodes if n.name == "角色偏好")
        assert pref_node.confidence <= 0.4
        assert pref_node.properties.get("orphaned_subject") == "true"

        # Trait 节点保持原置信度，无 orphaned 标记
        trait_node = next(n for n in filtered.nodes if n.name == "性格开朗")
        assert trait_node.confidence == 0.9
        assert "orphaned_subject" not in trait_node.properties


class TestPersonCanonicalization:
    """Person 节点标识归一化测试

    验证修复：同一用户在 L3 知识图谱中按昵称/QQ号分裂为两个独立实体节点。
    归一化后 Person 节点 name 统一为稳定 user_id，昵称降级为 aliases 属性。
    """

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def extractor(self, temp_dir):
        from unittest.mock import Mock

        manager = MagicMock()
        manager.generate_direct = AsyncMock()
        manager.is_available = True

        astrbot_config = Mock()
        astrbot_config.__getitem__ = Mock(
            return_value={"enable": True, "enable_type_whitelist": True}
        )
        astrbot_config.__contains__ = Mock(return_value=True)
        init_config(astrbot_config, temp_dir)

        return EntityExtractor(manager)

    def test_nickname_canonicalized_to_user_id(self, extractor):
        """LLM 用昵称建 Person 节点时，归一化为 user_id 并记录别名"""
        llm_response = """{
          "nodes": [
            {"label": "Person", "name": "庭", "content": "用户", "confidence": 0.9}
          ],
          "edges": [],
          "extraction_confidence": 0.9
        }"""
        context = {
            "group_id": "g1",
            "user_aliases": {"234916823": ["庭"]},
            "active_users": ["234916823"],
        }

        result = extractor._parse_extraction_result(llm_response, context)

        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.name == "234916823"
        assert node.properties.get("user_id") == "234916823"
        assert "庭" in node.properties.get("aliases", "")
        # id 基于 user_id 生成，稳定可去重
        assert node.id == node.generate_id()

    def test_edge_resolves_via_alias_after_canonicalization(self, extractor):
        """边引用旧昵称时，归一化后仍能解析到正确 Person 节点"""
        llm_response = """{
          "nodes": [
            {"label": "Person", "name": "庭", "content": "用户", "confidence": 0.9},
            {"label": "Preference", "name": "苹果", "content": "喜欢苹果", "confidence": 0.8}
          ],
          "edges": [
            {"source_label": "Person", "source_name": "庭",
             "target_label": "Preference", "target_name": "苹果",
             "relation_type": "HAS_PREFERENCE", "confidence": 0.8}
          ],
          "extraction_confidence": 0.85
        }"""
        context = {
            "group_id": "g1",
            "user_aliases": {"234916823": ["庭"]},
            "active_users": ["234916823"],
        }

        result = extractor._parse_extraction_result(llm_response, context)

        person = next(n for n in result.nodes if n.label == "Person")
        assert person.name == "234916823"

        # 边应成功解析并指向归一化后的 Person
        assert len(result.edges) == 1
        edge = result.edges[0]
        assert edge.source_id == person.id
        assert edge.relation_type == "HAS_PREFERENCE"

    def test_duplicate_person_nodes_deduped_by_user_id(self, extractor):
        """同一 user_id 的两个 Person 节点（昵称+QQ号）归一为单一节点"""
        llm_response = """{
          "nodes": [
            {"label": "Person", "name": "庭", "content": "喜欢吃苹果", "confidence": 0.9},
            {"label": "Person", "name": "234916823", "content": "是程序员", "confidence": 0.85}
          ],
          "edges": [],
          "extraction_confidence": 0.85
        }"""
        context = {
            "group_id": "g1",
            "user_aliases": {"234916823": ["庭"]},
            "active_users": ["234916823"],
        }

        result = extractor._parse_extraction_result(llm_response, context)

        # 两个节点归一为同一 id，去重后只剩一个
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.name == "234916823"
        assert node.properties.get("user_id") == "234916823"
        # 两个 content 合并
        assert "苹果" in node.content
        assert "程序员" in node.content
        # 昵称记录为别名
        assert "庭" in node.properties.get("aliases", "")

    def test_no_user_aliases_leaves_person_unchanged(self, extractor):
        """无 user_aliases 时，非已知用户的 Person 节点保持原样"""
        llm_response = """{
          "nodes": [
            {"label": "Person", "name": "张三", "content": "路人", "confidence": 0.9}
          ],
          "edges": [],
          "extraction_confidence": 0.9
        }"""
        result = extractor._parse_extraction_result(llm_response, {"group_id": "g1"})

        assert len(result.nodes) == 1
        assert result.nodes[0].name == "张三"
        assert "user_id" not in result.nodes[0].properties

    def test_prompt_includes_canonicalization_rule(self, extractor):
        """提取 prompt 应包含人物标识归一化硬规则"""
        prompt = extractor._build_extraction_prompt("测试文本")
        assert "[用户:ID]" in prompt
        assert "必须" in prompt
