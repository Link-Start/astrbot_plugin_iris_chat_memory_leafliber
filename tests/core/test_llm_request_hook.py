"""测试 LLM 请求钩子处理模块"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from contextlib import ExitStack
from datetime import datetime

from iris_memory.l1_buffer.models import ContextMessage
from iris_memory.core.llm_request_hook import (
    preprocess_llm_request,
    _extract_original_prompt,
    _wrap_prompt_section,
    _inject_all_to_system_prompt,
    _build_image_map,
    _get_inline_image_desc,
)


def _make_msg(role, content, source="user1", metadata=None, token_count=1):
    return ContextMessage(
        role=role,
        content=content,
        timestamp=datetime.now(),
        token_count=token_count,
        source=source,
        metadata=metadata or {},
    )


def _make_component_manager(buffer=None):
    cm = MagicMock()
    if buffer is not None:
        cm.get_component.return_value = buffer
        cm.get_available_component.return_value = (
            buffer if buffer.is_available else None
        )
    return cm


_ADAPTER_PATCH = "iris_memory.platform.get_adapter"
_COLLECT_PROFILE_PATCH = "iris_memory.core.llm_request_hook._collect_user_profile"
_COLLECT_L2_PATCH = "iris_memory.core.llm_request_hook._collect_l2_memory"
_COLLECT_L3_PATCH = "iris_memory.core.llm_request_hook._collect_l3_knowledge_graph"
_PARSE_IMAGES_PATCH = "iris_memory.core.llm_request_hook._parse_images_if_related_mode"
_BUILD_IMAGE_MAP_PATCH = "iris_memory.core.llm_request_hook._build_image_map"
_LOG_CONTEXT_PATCH = "iris_memory.core.llm_request_hook._log_final_context"
_GET_CONFIG_PATCH = "iris_memory.config.get_config"


def _default_config():
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: {
        "l1_buffer.inject_queue_length": 30,
        "l1_buffer.inject_max_content_chars": 200,
    }.get(key, default)
    return cfg


def _patch_collect_fns(
    profile_text="", l2_text="", l2_results=None, l3_text="", adapter=None
):
    patches = [
        patch(
            _COLLECT_PROFILE_PATCH, new_callable=AsyncMock, return_value=profile_text
        ),
        patch(
            _COLLECT_L2_PATCH,
            new_callable=AsyncMock,
            return_value=(l2_text, l2_results or []),
        ),
        patch(_COLLECT_L3_PATCH, new_callable=AsyncMock, return_value=l3_text),
        patch(_PARSE_IMAGES_PATCH, new_callable=AsyncMock, return_value=None),
        patch(_BUILD_IMAGE_MAP_PATCH, new_callable=AsyncMock, return_value={}),
        patch(_LOG_CONTEXT_PATCH),
        patch(_GET_CONFIG_PATCH, return_value=_default_config()),
    ]
    if adapter:
        patches.append(patch(_ADAPTER_PATCH, return_value=adapter))
    return patches


class TestHelperFunctions:
    """测试标记辅助函数"""

    def test_extract_original_prompt_empty(self):
        assert _extract_original_prompt("") == ""
        assert _extract_original_prompt(None) == ""

    def test_extract_original_prompt_no_markers(self):
        assert _extract_original_prompt("你好世界") == "你好世界"

    def test_extract_original_prompt_with_markers(self):
        prompt = (
            "原始提示词\n\n"
            "<!-- iris:start:profile -->\n画像内容\n<!-- iris:end:profile -->\n\n"
            "<!-- iris:start:l2_memory -->\n记忆内容\n<!-- iris:end:l2_memory -->"
        )
        assert _extract_original_prompt(prompt) == "原始提示词"

    def test_extract_original_prompt_only_markers(self):
        prompt = "<!-- iris:start:profile -->\n画像内容\n<!-- iris:end:profile -->"
        assert _extract_original_prompt(prompt) == ""

    def test_extract_original_prompt_multiple_sections(self):
        prompt = (
            "系统提示\n\n"
            "<!-- iris:start:profile -->\n画像\n<!-- iris:end:profile -->\n\n"
            "<!-- iris:start:l3_kg -->\n图谱\n<!-- iris:end:l3_kg -->\n\n"
            "<!-- iris:start:l2_memory -->\n记忆\n<!-- iris:end:l2_memory -->"
        )
        assert _extract_original_prompt(prompt) == "系统提示"

    def test_wrap_prompt_section(self):
        result = _wrap_prompt_section("profile", "画像内容")
        assert result == (
            "<!-- iris:start:profile -->\n画像内容\n<!-- iris:end:profile -->"
        )

    def test_wrap_prompt_section_l2_memory(self):
        result = _wrap_prompt_section("l2_memory", "记忆内容")
        assert "<!-- iris:start:l2_memory -->" in result
        assert "<!-- iris:end:l2_memory -->" in result
        assert "记忆内容" in result


class TestInjectAllToSystemPrompt:
    """测试所有内容注入到 system_prompt"""

    def test_inject_all_to_empty_system_prompt(self):
        req = MagicMock()
        req.system_prompt = ""
        _inject_all_to_system_prompt(req, "对话", "画像", "记忆", "图谱")
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "对话" in req.system_prompt
        assert "<!-- iris:start:profile -->" in req.system_prompt
        assert "画像" in req.system_prompt
        assert "<!-- iris:start:l3_kg -->" in req.system_prompt
        assert "图谱" in req.system_prompt
        assert "<!-- iris:start:l2_memory -->" in req.system_prompt
        assert "记忆" in req.system_prompt

    def test_inject_all_preserves_original(self):
        req = MagicMock()
        req.system_prompt = "你是一个助手"
        _inject_all_to_system_prompt(req, "对话", "画像", "", "")
        assert "你是一个助手" in req.system_prompt
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "<!-- iris:start:profile -->" in req.system_prompt

    def test_inject_all_replaces_existing(self):
        req = MagicMock()
        req.system_prompt = (
            "你是一个助手\n\n"
            "<!-- iris:start:l1_context -->\n旧对话\n<!-- iris:end:l1_context -->\n\n"
            "<!-- iris:start:profile -->\n旧画像\n<!-- iris:end:profile -->"
        )
        _inject_all_to_system_prompt(req, "新对话", "新画像", "", "")
        assert "旧对话" not in req.system_prompt
        assert "新对话" in req.system_prompt
        assert "旧画像" not in req.system_prompt
        assert "新画像" in req.system_prompt
        assert "你是一个助手" in req.system_prompt
        assert req.system_prompt.count("<!-- iris:start:l1_context -->") == 1
        assert req.system_prompt.count("<!-- iris:start:profile -->") == 1

    def test_inject_all_empty_removes_markers(self):
        req = MagicMock()
        req.system_prompt = (
            "你是一个助手\n\n"
            "<!-- iris:start:l1_context -->\n旧对话\n<!-- iris:end:l1_context -->\n\n"
            "<!-- iris:start:profile -->\n旧画像\n<!-- iris:end:profile -->"
        )
        _inject_all_to_system_prompt(req, "", "", "", "")
        assert "<!-- iris:start:l1_context -->" not in req.system_prompt
        assert "旧对话" not in req.system_prompt
        assert "<!-- iris:start:profile -->" not in req.system_prompt
        assert "旧画像" not in req.system_prompt
        assert "你是一个助手" in req.system_prompt

    def test_inject_all_only_l1(self):
        req = MagicMock()
        req.system_prompt = "系统提示"
        _inject_all_to_system_prompt(req, "对话内容", "", "", "")
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "对话内容" in req.system_prompt
        assert "<!-- iris:start:profile -->" not in req.system_prompt
        assert "<!-- iris:start:l2_memory -->" not in req.system_prompt
        assert "<!-- iris:start:l3_kg -->" not in req.system_prompt

    def test_inject_all_section_order(self):
        req = MagicMock()
        req.system_prompt = "系统提示"
        _inject_all_to_system_prompt(req, "对话", "画像", "记忆", "图谱")
        l1_idx = req.system_prompt.index("l1_context")
        profile_idx = req.system_prompt.index("profile")
        l2_idx = req.system_prompt.index("l2_memory")
        l3_idx = req.system_prompt.index("l3_kg")
        assert l1_idx < profile_idx < l2_idx < l3_idx


class TestBuildImageMap:
    """测试图片映射表构建"""

    @pytest.mark.asyncio
    async def test_build_image_map_empty_images(self):
        l1_buffer = MagicMock()
        l1_buffer.get_images.return_value = []
        component_manager = MagicMock()

        result = await _build_image_map(l1_buffer, "group1", component_manager)
        assert result == {}

    @pytest.mark.asyncio
    async def test_build_image_map_with_cached_images(self):
        from iris_memory.image import ImageParseStatus
        from datetime import datetime

        img_item = MagicMock()
        img_item.status = ImageParseStatus.SUCCESS
        img_item.message_id = "msg123"
        img_item.image_hash = "hash1"
        img_item.timestamp = datetime.now()
        img_item.user_id = "user1"

        l1_buffer = MagicMock()
        l1_buffer.get_images.return_value = [img_item]

        cached_result = MagicMock()
        cached_result.content = "一只猫的照片"

        cache_manager = MagicMock()
        cache_manager.is_available = True
        cache_manager.get_cache = AsyncMock(return_value=cached_result)

        component_manager = MagicMock()
        component_manager.get_component.return_value = cache_manager

        result = await _build_image_map(l1_buffer, "group1", component_manager)
        assert "msg123" in result
        assert result["msg123"] == ["一只猫的照片"]

    @pytest.mark.asyncio
    async def test_build_image_map_skips_non_success(self):
        from iris_memory.image import ImageParseStatus

        img_item = MagicMock()
        img_item.status = ImageParseStatus.PENDING
        img_item.message_id = "msg123"
        img_item.image_hash = "hash1"

        l1_buffer = MagicMock()
        l1_buffer.get_images.return_value = [img_item]

        component_manager = MagicMock()
        component_manager.get_component.return_value = None

        result = await _build_image_map(l1_buffer, "group1", component_manager)
        assert result == {}

    @pytest.mark.asyncio
    async def test_build_image_map_fallback_to_timestamp_key(self):
        from iris_memory.image import ImageParseStatus
        from datetime import datetime

        ts = datetime(2025, 1, 1, 10, 30)
        img_item = MagicMock()
        img_item.status = ImageParseStatus.SUCCESS
        img_item.message_id = ""
        img_item.image_hash = "hash1"
        img_item.timestamp = ts
        img_item.user_id = "user1"

        l1_buffer = MagicMock()
        l1_buffer.get_images.return_value = [img_item]

        cached_result = MagicMock()
        cached_result.content = "风景照"

        cache_manager = MagicMock()
        cache_manager.is_available = True
        cache_manager.get_cache = AsyncMock(return_value=cached_result)

        component_manager = MagicMock()
        component_manager.get_component.return_value = cache_manager

        result = await _build_image_map(l1_buffer, "group1", component_manager)
        key = "user1:10:30"
        assert key in result
        assert result[key] == ["风景照"]


class TestGetInlineImageDesc:
    """测试行内图片描述获取"""

    def test_empty_image_map(self):
        msg = _make_msg("user", "看看这个")
        result = _get_inline_image_desc(msg, None, {})
        assert result == ""

    def test_match_by_message_id(self):
        msg = _make_msg("user", "看看这个")
        image_map = {"msg123": ["一只猫的照片"]}
        result = _get_inline_image_desc(msg, "msg123", image_map)
        assert result == " [图片：一只猫的照片]"

    def test_match_by_timestamp_window(self):
        from datetime import datetime

        ts = datetime(2025, 1, 1, 10, 30)
        msg = ContextMessage(
            role="user",
            content="看看这个",
            timestamp=ts,
            token_count=1,
            source="user1",
            metadata={},
        )
        image_map = {"user1:10:30": ["风景照"]}
        result = _get_inline_image_desc(msg, None, image_map)
        assert result == " [图片：风景照]"

    def test_multiple_images_joined(self):
        msg = _make_msg("user", "看看这些")
        image_map = {"msg123": ["图片1", "图片2"]}
        result = _get_inline_image_desc(msg, "msg123", image_map)
        assert result == " [图片：图片1；图片2]"

    def test_no_match(self):
        msg = _make_msg("user", "看看这个")
        image_map = {"other_msg": ["一只猫的照片"]}
        result = _get_inline_image_desc(msg, "msg456", image_map)
        assert result == ""


class TestPreprocessLLMRequest:
    """测试 LLM 对话前处理主函数"""

    @pytest.mark.asyncio
    async def test_preprocess_with_available_buffer(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [
            _make_msg("user", "你好", token_count=2),
            _make_msg("assistant", "你好！", token_count=3),
        ]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert req.prompt == "你好"
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "你好" in req.system_prompt
        assert "你好！" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_with_unavailable_buffer(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = False

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" not in req.system_prompt
        assert req.prompt == "你好"

    @pytest.mark.asyncio
    async def test_preprocess_with_empty_messages(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = []

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" not in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_preserves_existing_system_prompt(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = "你是一个助手"

        buffer = MagicMock()
        buffer.is_available = True

        messages = [_make_msg("user", "问题", token_count=1)]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "你是一个助手" in req.system_prompt
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "问题" in req.system_prompt
        assert req.prompt == "你好"

    @pytest.mark.asyncio
    async def test_preprocess_with_user_name_binding(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [
            _make_msg("user", "你好", metadata={"user_name": "张三"}, token_count=2),
            _make_msg("assistant", "你好！", token_count=3),
        ]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "张三:" in req.system_prompt
        assert "你好" in req.system_prompt
        assert "Bot: 你好！" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_without_user_name(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [_make_msg("user", "你好", token_count=2)]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "你好" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_assistant_message_format(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [
            _make_msg(
                "assistant",
                "你好！",
                metadata={"user_name": "助手"},
                token_count=3,
            )
        ]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "Bot: 你好！" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_info(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [
            _make_msg(
                "user",
                "我也觉得",
                source="user456",
                metadata={
                    "user_name": "李四",
                    "reply_message_id": "6283",
                    "reply_user_name": "张三",
                    "reply_content": "你好啊",
                },
                token_count=4,
            )
        ]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "李四: ↩️回复张三「你好啊」" in req.system_prompt
        assert "我也觉得" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_no_user_name(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [
            _make_msg(
                "user",
                "是的",
                source="user456",
                metadata={
                    "user_name": "李四",
                    "reply_message_id": "6283",
                    "reply_content": "你好啊",
                },
                token_count=2,
            )
        ]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "↩️回复某人「你好啊」" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_no_content(self):
        """测试回复信息无内容时从 L1 上下文回填"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [
            _make_msg(
                "user",
                "你好啊",
                source="user123",
                metadata={"message_id": "6283", "user_name": "张三"},
                token_count=3,
            ),
            _make_msg(
                "user",
                "是的",
                source="user456",
                metadata={
                    "user_name": "李四",
                    "reply_message_id": "6283",
                },
                token_count=2,
            ),
        ]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "李四: ↩️回复张三「你好啊」" in req.system_prompt
        assert "是的" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_no_content_no_match(self):
        """测试回复信息无内容且 L1 上下文中也找不到时显示降级提示"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [
            _make_msg(
                "user",
                "是的",
                source="user456",
                metadata={
                    "user_name": "李四",
                    "reply_message_id": "9999",
                },
                token_count=2,
            ),
        ]
        buffer.get_context.return_value = messages

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "李四: ↩️回复了某条消息" in req.system_prompt


class TestMarkerReplacement:
    """测试标记替换逻辑——防止重复注入"""

    @pytest.mark.asyncio
    async def test_system_prompt_marker_replacement_on_second_call(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = "原始提示词"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = []

        profile_storage = MagicMock()
        profile_storage.is_available = False

        def get_component(name):
            if name == "l1_buffer":
                return buffer
            if name == "profile":
                return profile_storage
            return None

        component_manager = MagicMock()
        component_manager.get_component = get_component

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(
                profile_text="旧画像",
                l2_text="旧记忆",
                l3_text="旧图谱",
                adapter=adapter,
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        first_prompt = req.system_prompt
        assert "<!-- iris:start:profile -->" in first_prompt
        assert "旧画像" in first_prompt
        assert "<!-- iris:start:l2_memory -->" in first_prompt
        assert "旧记忆" in first_prompt
        assert "<!-- iris:start:l3_kg -->" in first_prompt
        assert "旧图谱" in first_prompt

        with ExitStack() as stack:
            for p in _patch_collect_fns(
                profile_text="新画像",
                l2_text="新记忆",
                l3_text="新图谱",
                adapter=adapter,
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        second_prompt = req.system_prompt
        assert "旧画像" not in second_prompt
        assert "新画像" in second_prompt
        assert "旧记忆" not in second_prompt
        assert "新记忆" in second_prompt
        assert "旧图谱" not in second_prompt
        assert "新图谱" in second_prompt
        assert second_prompt.count("<!-- iris:start:profile -->") == 1
        assert second_prompt.count("<!-- iris:start:l2_memory -->") == 1
        assert second_prompt.count("<!-- iris:start:l3_kg -->") == 1

    @pytest.mark.asyncio
    async def test_l1_context_replacement_on_second_call(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        old_messages = [_make_msg("user", "旧消息", token_count=2)]
        new_messages = [
            _make_msg("user", "新消息1", token_count=2),
            _make_msg("assistant", "新消息2", token_count=3),
        ]

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            buffer.get_context.return_value = old_messages
            await preprocess_llm_request(event, req, component_manager)

        assert "旧消息" in req.system_prompt
        assert "<!-- iris:start:l1_context -->" in req.system_prompt

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            buffer.get_context.return_value = new_messages
            await preprocess_llm_request(event, req, component_manager)

        assert "旧消息" not in req.system_prompt
        assert "新消息1" in req.system_prompt
        assert "Bot: 新消息2" in req.system_prompt
        assert req.system_prompt.count("<!-- iris:start:l1_context -->") == 1

    @pytest.mark.asyncio
    async def test_system_prompt_marker_replacement_with_empty_section(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = (
            "原始提示词\n\n"
            "<!-- iris:start:profile -->\n旧画像\n<!-- iris:end:profile -->\n\n"
            "<!-- iris:start:l2_memory -->\n旧记忆\n<!-- iris:end:l2_memory -->"
        )

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = []

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(l2_text="新记忆", adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:profile -->" not in req.system_prompt
        assert "旧画像" not in req.system_prompt
        assert "<!-- iris:start:l2_memory -->" in req.system_prompt
        assert "新记忆" in req.system_prompt
        assert "旧记忆" not in req.system_prompt

    @pytest.mark.asyncio
    async def test_unavailable_buffer_removes_old_l1_section(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = (
            "系统提示\n\n"
            "<!-- iris:start:l1_context -->\n旧L1内容\n<!-- iris:end:l1_context -->"
        )

        buffer = MagicMock()
        buffer.is_available = False

        component_manager = _make_component_manager(buffer)

        with ExitStack() as stack:
            for p in _patch_collect_fns():
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" not in req.system_prompt
        assert "旧L1内容" not in req.system_prompt
        assert "系统提示" in req.system_prompt

    @pytest.mark.asyncio
    async def test_empty_buffer_removes_old_l1_section(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = (
            "系统提示\n\n"
            "<!-- iris:start:l1_context -->\n旧L1内容\n<!-- iris:end:l1_context -->"
        )

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = []

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" not in req.system_prompt
        assert "旧L1内容" not in req.system_prompt
        assert "系统提示" in req.system_prompt

    @pytest.mark.asyncio
    async def test_prompt_not_modified(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "用户当前消息"
        req.system_prompt = "系统提示"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = [_make_msg("user", "你好", token_count=1)]

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(
                profile_text="画像", l2_text="记忆", l3_text="图谱", adapter=adapter
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert req.prompt == "用户当前消息"
        assert "<!-- iris:start:profile -->" in req.system_prompt
        assert "<!-- iris:start:l3_kg -->" in req.system_prompt
        assert "<!-- iris:start:l2_memory -->" in req.system_prompt
        assert "<!-- iris:start:l1_context -->" in req.system_prompt

    @pytest.mark.asyncio
    async def test_contexts_not_modified(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = [{"role": "user", "content": "当前消息"}]
        req.prompt = "你好"
        req.system_prompt = "系统提示"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = [_make_msg("user", "历史", token_count=1)]

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(
                profile_text="画像", l2_text="记忆", l3_text="图谱", adapter=adapter
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert len(req.contexts) == 1
        assert req.contexts[0]["content"] == "当前消息"
        assert "<!-- iris:start:l1_context -->" in req.system_prompt

    @pytest.mark.asyncio
    async def test_all_sections_in_system_prompt(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = "系统提示"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = [_make_msg("user", "历史", token_count=1)]

        component_manager = _make_component_manager(buffer)

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(
                profile_text="画像", l2_text="记忆", l3_text="图谱", adapter=adapter
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "系统提示" in req.system_prompt
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "<!-- iris:start:profile -->" in req.system_prompt
        assert "<!-- iris:start:l3_kg -->" in req.system_prompt
        assert "<!-- iris:start:l2_memory -->" in req.system_prompt
