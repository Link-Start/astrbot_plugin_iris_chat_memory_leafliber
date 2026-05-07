"""
对话清理模块

在 Agent 运行完成后，删除 AstrBot 内置对话管理器中的当前对话，
确保上下文完全由本插件的 L1/L2/L3 记忆系统控制，避免 AstrBot
内置对话历史与插件记忆系统产生冲突或重复。

清理策略：
- 通过 on_agent_done 钩子触发，在 Agent 运行完成后执行
- 调用 conversationManager.delete_conversation 删除当前对话
- 删除后 AstrBot 会在下次消息时自动创建新对话
- 受 context_control.enable_conversation_cleanup 配置控制
"""

from typing import TYPE_CHECKING

from iris_memory.core import get_logger

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import LLMResponse
    from astrbot.api.star import Context
    from iris_memory.core.components import ComponentManager

logger = get_logger("conversation_cleanup")


async def handle_agent_done(
    event: "AstrMessageEvent",
    resp: "LLMResponse",
    context: "Context",
    component_manager: "ComponentManager",
) -> None:
    """Agent 运行完成后的对话清理处理

    在 Agent 运行完成后，检查配置并删除 AstrBot 内置对话管理器中的
    当前对话，确保上下文完全由本插件控制。

    Args:
        event: AstrBot 消息事件对象
        resp: LLM 响应对象
        context: AstrBot 插件上下文
        component_manager: 组件管理器实例
    """
    from iris_memory.config import get_config

    config = get_config()

    if not config.get("context_control.enable_conversation_cleanup"):
        return

    conv_mgr = getattr(context, "conversationManager", None)
    if conv_mgr is None:
        logger.debug("对话管理器不可用，跳过对话清理")
        return

    umo = event.unified_msg_origin
    if not umo:
        logger.debug("无法获取 unified_msg_origin，跳过对话清理")
        return

    try:
        curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        if not curr_cid:
            logger.debug("当前无活跃对话，跳过对话清理")
            return

        await conv_mgr.delete_conversation(umo, None)
        logger.debug(f"已清理会话 {umo} 的内置对话历史 (cid={curr_cid})")
    except Exception as e:
        logger.warning(f"清理内置对话历史失败: {e}")
