"""
Iris Chat Memory - 图片解析器

使用 LLM Vision 模型解析图片内容。
优先通过 message_recorder 插件获取本地图片，避免链接过期。
"""

from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from iris_memory.core import get_logger
from .models import ImageInfo, ParseResult
from .recorder_bridge import MessageRecorderBridge

if TYPE_CHECKING:
    from iris_memory.llm.manager import LLMManager

logger = get_logger("image")


class ImageParser:
    """图片解析器

    使用支持 Vision 能力的 LLM 模型解析图片内容。
    优先通过 MessageRecorderBridge 获取本地图片文件，
    转为 base64 data URL 传给 LLM，避免网络链接过期。

    Attributes:
        _llm_manager: LLM 调用管理器
        _provider: Provider ID（可选）
        _recorder_bridge: MessageRecorder 桥接器（可选）

    Examples:
        >>> parser = ImageParser(llm_manager, recorder_bridge=bridge)
        >>> result = await parser.parse(image_info)
        >>> print(result.content)
    """

    def __init__(
        self,
        llm_manager: "LLMManager",
        provider: str = "",
        recorder_bridge: Optional[MessageRecorderBridge] = None,
    ):
        """初始化图片解析器

        Args:
            llm_manager: LLM 调用管理器
            provider: Provider ID（留空使用配置或默认）
            recorder_bridge: MessageRecorder 桥接器（可选）
        """
        self._llm_manager = llm_manager
        self._provider = provider
        self._recorder_bridge = recorder_bridge

    async def _resolve_image_url(self, image_info: ImageInfo) -> Optional[str]:
        """解析图片 URL，优先使用本地文件

        优先级：
        1. 通过 MessageRecorderBridge 获取本地图片 → data URL
        2. 使用 ImageInfo 中的 file_path → data URL
        3. 回退到网络 URL

        Args:
            image_info: 图片信息

        Returns:
            可用的图片 URL（HTTP URL 或 data URL），不可用返回 None
        """
        if self._recorder_bridge and image_info.message_id:
            local_path = await self._recorder_bridge.get_local_image_path(
                message_id=image_info.message_id,
                image_url=image_info.url,
            )
            if local_path:
                data_url = MessageRecorderBridge.image_to_data_url(local_path)
                if data_url:
                    logger.debug(
                        f"使用 MessageRecorder 本地图片：{local_path.name}"
                    )
                    return data_url

        if image_info.has_file_path and image_info.file_path:
            file_path = Path(image_info.file_path)
            data_url = MessageRecorderBridge.image_to_data_url(file_path)
            if data_url:
                logger.debug(f"使用本地文件图片：{file_path.name}")
                return data_url
            logger.warning(f"本地图片文件无法读取：{image_info.file_path}")

        if image_info.has_url:
            return image_info.url

        return None

    async def parse(self, image_info: ImageInfo) -> ParseResult:
        """解析单张图片

        优先使用本地图片（避免链接过期），回退到网络 URL。

        Args:
            image_info: 图片信息

        Returns:
            解析结果
        """
        image_url = await self._resolve_image_url(image_info)

        if not image_url:
            return ParseResult(
                image_info=image_info, success=False, error_message="图片信息无效"
            )

        prompt = self._build_parse_prompt()

        try:
            response = await self._llm_manager.generate_with_images(
                prompt=prompt,
                image_urls=[image_url],
                module="image_parsing",
                provider_id=self._provider if self._provider else None,
            )

            return ParseResult(image_info=image_info, content=response, success=True)

        except Exception as e:
            logger.error(f"图片解析失败：{e}")
            return ParseResult(
                image_info=image_info, success=False, error_message=str(e)
            )

    async def parse_batch(self, images: List[ImageInfo]) -> List[ParseResult]:
        """批量解析图片

        Args:
            images: 图片信息列表

        Returns:
            解析结果列表
        """
        results = []
        for image in images:
            result = await self.parse(image)
            results.append(result)

        return results

    def _build_parse_prompt(self) -> str:
        """构建图片解析提示词

        Returns:
            解析提示词
        """
        return "简要描述图片内容，重点写文字和关键物体，不超过80字。"
