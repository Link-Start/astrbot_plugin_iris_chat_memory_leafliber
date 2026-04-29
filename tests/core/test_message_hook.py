"""测试消息钩子处理模块"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from iris_memory.core.message_hook import handle_user_message, update_l1_buffer
from iris_memory.platform.base import ReplyInfo


class TestHandleUserMessage:
    """测试用户消息处理主函数"""
    
    @pytest.mark.asyncio
    async def test_handle_with_available_buffer(self):
        """测试 L1 Buffer 可用时的消息处理"""
        event = MagicMock()
        event.message_str = "你好"
        
        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "测试用户"
        adapter.get_group_name.return_value = ""
        adapter.get_reply_info.return_value = ReplyInfo()
        
        with patch('iris_memory.core.message_hook.get_adapter', return_value=adapter):
            await handle_user_message(event, component_manager)
        
        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["group_id"] == "group123"
        assert call_kwargs["role"] == "user"
        assert call_kwargs["content"] == "你好"
        assert call_kwargs["source"] == "user456"
        assert call_kwargs["metadata"]["user_name"] == "测试用户"
        assert "reply_message_id" not in call_kwargs["metadata"]
    
    @pytest.mark.asyncio
    async def test_handle_with_reply_info(self):
        """测试带回复信息的消息处理"""
        event = MagicMock()
        event.message_str = "我也觉得"
        
        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "李四"
        adapter.get_group_name.return_value = ""
        adapter.get_reply_info.return_value = ReplyInfo(
            message_id="6283",
            user_id="1234567",
            user_name="张三",
            content="你好啊"
        )
        
        with patch('iris_memory.core.message_hook.get_adapter', return_value=adapter):
            await handle_user_message(event, component_manager)
        
        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_message_id"] == "6283"
        assert call_kwargs["metadata"]["reply_user_id"] == "1234567"
        assert call_kwargs["metadata"]["reply_user_name"] == "张三"
        assert call_kwargs["metadata"]["reply_content"] == "你好啊"
    
    @pytest.mark.asyncio
    async def test_handle_with_reply_no_content(self):
        """测试回复信息无内容时只记录 message_id"""
        event = MagicMock()
        event.message_str = "是的"
        
        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = ""
        adapter.get_group_name.return_value = ""
        adapter.get_reply_info.return_value = ReplyInfo(message_id="6283")
        
        with patch('iris_memory.core.message_hook.get_adapter', return_value=adapter):
            await handle_user_message(event, component_manager)
        
        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_message_id"] == "6283"
        assert "reply_user_id" not in call_kwargs["metadata"]
        assert "reply_user_name" not in call_kwargs["metadata"]
        assert "reply_content" not in call_kwargs["metadata"]
    
    @pytest.mark.asyncio
    async def test_handle_with_unavailable_buffer(self):
        """测试 L1 Buffer 不可用时的消息处理"""
        event = MagicMock()
        event.message_str = "你好"
        
        buffer = MagicMock()
        buffer.is_available = False
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        await handle_user_message(event, component_manager)
        
        buffer.add_message.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_with_empty_content(self):
        """测试消息内容为空时的处理"""
        event = MagicMock()
        event.message_str = ""
        
        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        await handle_user_message(event, component_manager)
        
        buffer.add_message.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_with_none_content(self):
        """测试消息内容为 None 时的处理"""
        event = MagicMock()
        event.message_str = None
        
        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        await handle_user_message(event, component_manager)
        
        buffer.add_message.assert_not_called()


class TestUpdateL1Buffer:
    """测试 L1 Buffer 更新函数"""
    
    @pytest.mark.asyncio
    async def test_update_with_user_message(self):
        """测试添加用户消息"""
        event = MagicMock()
        
        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        
        with patch('iris_memory.core.message_hook.get_adapter', return_value=adapter):
            await update_l1_buffer(event, component_manager, "user", "你好")
        
        # 验证调用了 add_message
        buffer.add_message.assert_called_once_with(
            group_id="group123",
            role="user",
            content="你好",
            source="user456"
        )
    
    @pytest.mark.asyncio
    async def test_update_with_assistant_message(self):
        """测试添加助手消息"""
        event = MagicMock()
        
        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        
        with patch('iris_memory.core.message_hook.get_adapter', return_value=adapter):
            await update_l1_buffer(event, component_manager, "assistant", "你好！")
        
        # 验证调用了 add_message
        buffer.add_message.assert_called_once_with(
            group_id="group123",
            role="assistant",
            content="你好！",
            source="assistant"
        )
    
    @pytest.mark.asyncio
    async def test_update_with_unavailable_buffer(self):
        """测试 L1 Buffer 不可用时不添加消息"""
        event = MagicMock()
        
        buffer = MagicMock()
        buffer.is_available = False
        buffer.add_message = AsyncMock()
        
        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        
        # 不应该调用 add_message
        await update_l1_buffer(event, component_manager, "user", "你好")
        
        buffer.add_message.assert_not_called()
