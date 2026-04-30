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
    _remove_l1_context_block,
    _find_l1_context_system_message,
    _extract_l1_content_from_system_message,
    _replace_l1_in_system_message,
    _L1_CONTEXT_START_MARKER,
    _L1_CONTEXT_END_MARKER,
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
        patch(_COLLECT_PROFILE_PATCH, new_callable=AsyncMock, return_value=profile_text),
        patch(_COLLECT_L2_PATCH, new_callable=AsyncMock, return_value=(l2_text, l2_results or [])),
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
        prompt = (
            "<!-- iris:start:profile -->\n画像内容\n<!-- iris:end:profile -->"
        )
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
            "<!-- iris:start:profile -->\n"
            "画像内容\n"
            "<!-- iris:end:profile -->"
        )

    def test_wrap_prompt_section_l2_memory(self):
        result = _wrap_prompt_section("l2_memory", "记忆内容")
        assert "<!-- iris:start:l2_memory -->" in result
        assert "<!-- iris:end:l2_memory -->" in result
        assert "记忆内容" in result

    def test_find_l1_context_system_message_found(self):
        contexts = [
            {"role": "system", "content": "系统提示"},
            {"role": "system", "content": f"{_L1_CONTEXT_START_MARKER}\nuser: 你好\n{_L1_CONTEXT_END_MARKER}"},
            {"role": "user", "content": "当前消息"},
        ]
        assert _find_l1_context_system_message(contexts) == 1

    def test_find_l1_context_system_message_not_found(self):
        contexts = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "你好"},
        ]
        assert _find_l1_context_system_message(contexts) is None

    def test_find_l1_context_system_message_empty(self):
        assert _find_l1_context_system_message([]) is None

    def test_extract_l1_content_from_system_message(self):
        content = f"系统提示\n{_L1_CONTEXT_START_MARKER}\nuser: 你好\nassistant: 你好！\n{_L1_CONTEXT_END_MARKER}"
        assert _extract_l1_content_from_system_message(content) == "user: 你好\nassistant: 你好！"

    def test_extract_l1_content_from_system_message_no_markers(self):
        assert _extract_l1_content_from_system_message("系统提示") == ""

    def test_replace_l1_in_system_message_with_content(self):
        content = f"系统提示\n{_L1_CONTEXT_START_MARKER}\n旧内容\n{_L1_CONTEXT_END_MARKER}"
        result = _replace_l1_in_system_message(content, "新内容")
        assert "旧内容" not in result
        assert "新内容" in result
        assert _L1_CONTEXT_START_MARKER in result
        assert _L1_CONTEXT_END_MARKER in result
        assert "系统提示" in result

    def test_replace_l1_in_system_message_with_empty(self):
        content = f"系统提示\n{_L1_CONTEXT_START_MARKER}\n旧内容\n{_L1_CONTEXT_END_MARKER}"
        result = _replace_l1_in_system_message(content, "")
        assert _L1_CONTEXT_START_MARKER not in result
        assert "旧内容" not in result
        assert "系统提示" in result

    def test_replace_l1_in_system_message_no_existing_markers(self):
        content = "系统提示"
        result = _replace_l1_in_system_message(content, "新内容")
        assert result == "系统提示"

    def test_remove_l1_context_block_no_markers(self):
        contexts = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ]
        result = _remove_l1_context_block(contexts)
        assert result == contexts

    def test_remove_l1_context_block_with_markers(self):
        contexts = [
            {"role": "system", "content": f"系统提示\n{_L1_CONTEXT_START_MARKER}\n旧消息\n{_L1_CONTEXT_END_MARKER}"},
            {"role": "user", "content": "当前消息"},
        ]
        result = _remove_l1_context_block(contexts)
        assert len(result) == 2
        assert result[0]["content"] == "系统提示"
        assert result[1]["content"] == "当前消息"

    def test_remove_l1_context_block_only_l1_content(self):
        contexts = [
            {"role": "system", "content": f"{_L1_CONTEXT_START_MARKER}\n旧消息\n{_L1_CONTEXT_END_MARKER}"},
            {"role": "user", "content": "当前消息"},
        ]
        result = _remove_l1_context_block(contexts)
        assert len(result) == 1
        assert result[0]["content"] == "当前消息"

    def test_remove_l1_context_block_empty(self):
        assert _remove_l1_context_block([]) == []


class TestPreprocessLLMRequest:
    """测试 LLM 对话前处理主函数"""

    @pytest.mark.asyncio
    async def test_preprocess_with_available_buffer(self):
        """测试 L1 Buffer 可用时的对话前处理"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        buffer.get_context.assert_called_once_with("group123", 20)

        assert len(req.contexts) == 1
        assert req.contexts[0]["role"] == "system"
        assert _L1_CONTEXT_START_MARKER in req.contexts[0]["content"]
        assert _L1_CONTEXT_END_MARKER in req.contexts[0]["content"]
        assert "user: 你好" in req.contexts[0]["content"]
        assert "assistant: 你好！" in req.contexts[0]["content"]

    @pytest.mark.asyncio
    async def test_preprocess_with_unavailable_buffer(self):
        """测试 L1 Buffer 不可用时的对话前处理"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

        buffer = MagicMock()
        buffer.is_available = False

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        with ExitStack() as stack:
            for p in _patch_collect_fns():
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert req.contexts == []

    @pytest.mark.asyncio
    async def test_preprocess_with_empty_messages(self):
        """测试 L1 Buffer 消息为空时的对话前处理"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert req.contexts == []

    @pytest.mark.asyncio
    async def test_preprocess_appends_to_existing_contexts(self):
        """测试已有上下文时 L1 消息追加到 system 消息中"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = [{"role": "system", "content": "你是助手"}]
        req.prompt = ""

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

        assert len(req.contexts) == 2
        assert req.contexts[0]["role"] == "system"
        assert _L1_CONTEXT_START_MARKER in req.contexts[0]["content"]
        assert "user: 问题" in req.contexts[0]["content"]
        assert _L1_CONTEXT_END_MARKER in req.contexts[0]["content"]
        assert req.contexts[1]["role"] == "system"
        assert req.contexts[1]["content"] == "你是助手"

    @pytest.mark.asyncio
    async def test_preprocess_with_user_name_binding(self):
        """测试用户消息绑定用户名"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert len(req.contexts) == 1
        l1_content = req.contexts[0]["content"]
        assert "user: [张三]: 你好" in l1_content
        assert "assistant: 你好！" in l1_content

    @pytest.mark.asyncio
    async def test_preprocess_without_user_name(self):
        """测试没有用户名时不绑定"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert len(req.contexts) == 1
        assert "user: 你好" in req.contexts[0]["content"]

    @pytest.mark.asyncio
    async def test_preprocess_assistant_message_no_user_name(self):
        """测试助手消息不绑定用户名"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert len(req.contexts) == 1
        assert "assistant: 你好！" in req.contexts[0]["content"]

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_info(self):
        """测试回复消息的上下文注入"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert len(req.contexts) == 1
        l1_content = req.contexts[0]["content"]
        assert "回复[张三]「你好啊」" in l1_content
        assert "[李四]: 我也觉得" in l1_content

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_no_user_name(self):
        """测试回复消息无发送者名称时的上下文注入"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert len(req.contexts) == 1
        assert "回复「你好啊」" in req.contexts[0]["content"]

    @pytest.mark.asyncio
    async def test_preprocess_with_reply_no_content(self):
        """测试回复消息无内容时不注入回复前缀"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert len(req.contexts) == 1
        assert "user: [李四]: 是的" in req.contexts[0]["content"]
        assert "回复" not in req.contexts[0]["content"]


class TestMarkerReplacement:
    """测试标记替换逻辑——防止重复注入"""

    @pytest.mark.asyncio
    async def test_prompt_marker_replacement_on_second_call(self):
        """测试第二次调用时 prompt 标记内容被替换而非追加"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = "原始提示词"

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
                profile_text="旧画像", l2_text="旧记忆", l3_text="旧图谱", adapter=adapter
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        first_prompt = req.prompt
        assert "<!-- iris:start:profile -->" in first_prompt
        assert "旧画像" in first_prompt
        assert "<!-- iris:start:l2_memory -->" in first_prompt
        assert "旧记忆" in first_prompt
        assert "<!-- iris:start:l3_kg -->" in first_prompt
        assert "旧图谱" in first_prompt

        with ExitStack() as stack:
            for p in _patch_collect_fns(
                profile_text="新画像", l2_text="新记忆", l3_text="新图谱", adapter=adapter
            ):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        second_prompt = req.prompt
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
    async def test_contexts_marker_replacement_on_second_call(self):
        """测试第二次调用时 L1 上下文被替换而非重复前插"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        assert len(req.contexts) == 1
        assert req.contexts[0]["role"] == "system"
        assert _L1_CONTEXT_START_MARKER in req.contexts[0]["content"]
        assert "user: 旧消息" in req.contexts[0]["content"]
        assert _L1_CONTEXT_END_MARKER in req.contexts[0]["content"]

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            buffer.get_context.return_value = new_messages
            await preprocess_llm_request(event, req, component_manager)

        assert len(req.contexts) == 1
        l1_content = req.contexts[0]["content"]
        assert _L1_CONTEXT_START_MARKER in l1_content
        assert "user: 新消息1" in l1_content
        assert "assistant: 新消息2" in l1_content
        assert _L1_CONTEXT_END_MARKER in l1_content
        assert "旧消息" not in l1_content

    @pytest.mark.asyncio
    async def test_contexts_marker_replacement_preserves_existing(self):
        """测试替换 L1 上下文时保留非 L1 的已有上下文"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "当前用户消息"},
        ]
        req.prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [_make_msg("user", "历史消息", token_count=2)]
        buffer.get_context.return_value = messages

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert len(req.contexts) == 3
        l1_msg = req.contexts[0]
        assert l1_msg["role"] == "system"
        assert _L1_CONTEXT_START_MARKER in l1_msg["content"]
        assert "user: 历史消息" in l1_msg["content"]

        non_l1_contents = [
            c["content"]
            for c in req.contexts
            if _L1_CONTEXT_START_MARKER not in c.get("content", "")
        ]
        assert "系统提示" in non_l1_contents
        assert "当前用户消息" in non_l1_contents

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        l1_msg = req.contexts[0]
        assert _L1_CONTEXT_START_MARKER in l1_msg["content"]
        l1_inner = _extract_l1_content_from_system_message(l1_msg["content"])
        assert l1_inner.count("历史消息") == 1

        non_l1_contents = [
            c["content"]
            for c in req.contexts
            if _L1_CONTEXT_START_MARKER not in c.get("content", "")
        ]
        assert "系统提示" in non_l1_contents
        assert "当前用户消息" in non_l1_contents

    @pytest.mark.asyncio
    async def test_prompt_marker_replacement_with_empty_section(self):
        """测试某个 section 内容为空时，标记被移除而非保留空壳"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = (
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

        assert "<!-- iris:start:profile -->" not in req.prompt
        assert "旧画像" not in req.prompt
        assert "<!-- iris:start:l2_memory -->" in req.prompt
        assert "新记忆" in req.prompt
        assert "旧记忆" not in req.prompt

    @pytest.mark.asyncio
    async def test_unavailable_buffer_removes_old_l1_markers(self):
        """测试 L1 Buffer 不可用时，旧的 L1 标记块被清除"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = [
            {"role": "system", "content": f"系统提示\n{_L1_CONTEXT_START_MARKER}\nuser: 旧L1消息\n{_L1_CONTEXT_END_MARKER}"},
            {"role": "user", "content": "当前消息"},
        ]
        req.prompt = ""

        buffer = MagicMock()
        buffer.is_available = False

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        with ExitStack() as stack:
            for p in _patch_collect_fns():
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        assert len(req.contexts) == 2
        assert req.contexts[0]["content"] == "系统提示"
        assert req.contexts[1]["content"] == "当前消息"

    @pytest.mark.asyncio
    async def test_empty_buffer_removes_old_l1_markers(self):
        """测试 L1 Buffer 返回空消息时，旧的 L1 标记块被清除"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = [
            {"role": "system", "content": f"系统提示\n{_L1_CONTEXT_START_MARKER}\nuser: 旧L1消息\n{_L1_CONTEXT_END_MARKER}"},
            {"role": "user", "content": "当前消息"},
        ]
        req.prompt = ""

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

        assert len(req.contexts) == 2
        assert req.contexts[0]["content"] == "系统提示"
        assert req.contexts[1]["content"] == "当前消息"

    @pytest.mark.asyncio
    async def test_l1_context_in_single_system_message(self):
        """测试 L1 上下文合并到单个 system 消息中（兼容 OpenAI API）"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = []
        req.prompt = ""

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

        system_roles = [c for c in req.contexts if c["role"] == "system"]
        assert len(system_roles) == 1
        content = system_roles[0]["content"]
        assert _L1_CONTEXT_START_MARKER in content
        assert "user: 你好" in content
        assert "assistant: 你好！" in content
        assert _L1_CONTEXT_END_MARKER in content

    @pytest.mark.asyncio
    async def test_l1_context_replaces_within_existing_system_message(self):
        """测试已有 system 消息含 L1 标记时，替换标记内容而非新增 system 消息"""
        event = MagicMock()
        req = MagicMock()
        req.contexts = [
            {"role": "system", "content": f"系统提示\n{_L1_CONTEXT_START_MARKER}\nuser: 旧消息\n{_L1_CONTEXT_END_MARKER}"},
            {"role": "user", "content": "当前消息"},
        ]
        req.prompt = ""

        buffer = MagicMock()
        buffer.is_available = True

        messages = [_make_msg("user", "新消息", token_count=1)]
        buffer.get_context.return_value = messages

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"

        with ExitStack() as stack:
            for p in _patch_collect_fns(adapter=adapter):
                stack.enter_context(p)
            await preprocess_llm_request(event, req, component_manager)

        system_roles = [c for c in req.contexts if c["role"] == "system"]
        assert len(system_roles) == 1
        content = system_roles[0]["content"]
        assert "旧消息" not in content
        assert "user: 新消息" in content
        assert "系统提示" in content
