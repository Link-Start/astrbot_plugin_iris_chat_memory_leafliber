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
    _inject_images_to_system_prompt,
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


_ADAPTER_PATCH = "iris_memory.platform.get_adapter"
_COLLECT_PROFILE_PATCH = "iris_memory.core.llm_request_hook._collect_user_profile"
_COLLECT_L2_PATCH = "iris_memory.core.llm_request_hook._collect_l2_memory"
_COLLECT_L3_PATCH = "iris_memory.core.llm_request_hook._collect_l3_knowledge_graph"
_PARSE_IMAGES_PATCH = "iris_memory.core.llm_request_hook._parse_images_if_related_mode"
_LOG_CONTEXT_PATCH = "iris_memory.core.llm_request_hook._log_final_context"


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
        patch(_LOG_CONTEXT_PATCH),
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
            "<!-- iris:start:l1_context -->\n对话\n<!-- iris:end:l1_context -->\n\n"
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

    def test_wrap_prompt_section_l1_context(self):
        result = _wrap_prompt_section("l1_context", "对话内容")
        assert "<!-- iris:start:l1_context -->" in result
        assert "<!-- iris:end:l1_context -->" in result
        assert "对话内容" in result


class TestInjectAllToSystemPrompt:
    """测试所有内容注入到 system_prompt"""

    def test_inject_all_to_empty_system_prompt(self):
        req = MagicMock()
        req.system_prompt = ""
        _inject_all_to_system_prompt(req, "对话", "画像", "图谱", "记忆")
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
        _inject_all_to_system_prompt(req, "对话", "画像", "图谱", "记忆")
        l1_idx = req.system_prompt.index("l1_context")
        profile_idx = req.system_prompt.index("profile")
        l3_idx = req.system_prompt.index("l3_kg")
        l2_idx = req.system_prompt.index("l2_memory")
        assert l1_idx < profile_idx < l3_idx < l2_idx


class TestInjectImagesToSystemPrompt:
    """测试图片注入到 system_prompt"""

    def test_inject_images_to_empty_prompt(self):
        req = MagicMock()
        req.system_prompt = ""
        _inject_images_to_system_prompt(req, [{"timestamp": 1, "content": "一只猫"}])
        assert "<!-- iris:start:images -->" in req.system_prompt
        assert "（用户发送的图片内容：一只猫）" in req.system_prompt

    def test_inject_images_preserves_existing(self):
        req = MagicMock()
        req.system_prompt = (
            "系统提示\n\n"
            "<!-- iris:start:l1_context -->\n对话\n<!-- iris:end:l1_context -->"
        )
        _inject_images_to_system_prompt(req, [{"timestamp": 1, "content": "一只猫"}])
        assert "系统提示" in req.system_prompt
        assert "<!-- iris:start:images -->" in req.system_prompt
        assert "（用户发送的图片内容：一只猫）" in req.system_prompt

    def test_inject_images_empty_does_nothing(self):
        req = MagicMock()
        req.system_prompt = "系统提示"
        _inject_images_to_system_prompt(req, [])
        assert req.system_prompt == "系统提示"

    def test_inject_images_replaces_existing(self):
        req = MagicMock()
        req.system_prompt = (
            "系统提示\n\n<!-- iris:start:images -->\n旧图片\n<!-- iris:end:images -->"
        )
        _inject_images_to_system_prompt(req, [{"timestamp": 1, "content": "新图片"}])
        assert "旧图片" not in req.system_prompt
        assert "（用户发送的图片内容：新图片）" in req.system_prompt
        assert req.system_prompt.count("<!-- iris:start:images -->") == 1


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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert req.prompt == "你好"
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "【近期群聊记录】" in req.system_prompt
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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        with ExitStack() as stack:
            for p in _patch_collect_fns():
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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "你是一个助手" in req.system_prompt
        assert "<!-- iris:start:l1_context -->" in req.system_prompt
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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "张三: 你好" in req.system_prompt
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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "↩️回复某人「你好啊」" in req.system_prompt

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_no_content(self):
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
                metadata={"user_name": "李四", "reply_message_id": "6283"},
                token_count=2,
            )
        ]
        buffer.get_context.return_value = messages

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "李四: 是的" in req.system_prompt
        assert "↩️" not in req.system_prompt


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
    async def test_l1_context_marker_replacement_on_second_call(self):
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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            buffer.get_context.return_value = old_messages
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" in req.system_prompt
        assert "旧消息" in req.system_prompt

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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

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
    async def test_unavailable_buffer_removes_old_l1_markers(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = (
            "系统提示\n\n"
            "<!-- iris:start:l1_context -->\n旧L1消息\n<!-- iris:end:l1_context -->"
        )

        buffer = MagicMock()
        buffer.is_available = False

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        with ExitStack() as stack:
            for p in _patch_collect_fns():
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" not in req.system_prompt
        assert "旧L1消息" not in req.system_prompt
        assert "系统提示" in req.system_prompt

    @pytest.mark.asyncio
    async def test_empty_buffer_removes_old_l1_markers(self):
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "你好"
        req.system_prompt = (
            "系统提示\n\n"
            "<!-- iris:start:l1_context -->\n旧L1消息\n<!-- iris:end:l1_context -->"
        )

        buffer = MagicMock()
        buffer.is_available = True
        buffer.get_context.return_value = []

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert "<!-- iris:start:l1_context -->" not in req.system_prompt
        assert "旧L1消息" not in req.system_prompt
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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(
                profile_text="画像", l2_text="记忆", l3_text="图谱", adapter=adapter
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert req.contexts == [{"role": "user", "content": "当前消息"}]

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

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

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
