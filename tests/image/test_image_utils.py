"""图片工具的内存放大防护测试（解压炸弹缓解）"""

import io

import pytest
from PIL import Image

from iris_memory.image import image_utils


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gradient_image(size: int = 100) -> Image.Image:
    """生成有灰度变化的图片（非纯色）"""
    img = Image.new("L", (size, size))
    for y in range(size):
        for x in range(size):
            img.putpixel((x, y), (x + y) % 256)
    return img


class TestCheckInvalidImage:
    """check_invalid_image：常规判定 + 内存防护"""

    @pytest.mark.asyncio
    async def test_solid_image_detected(self):
        data = _png_bytes(Image.new("L", (64, 64), color=128))
        is_invalid, reason = await image_utils.check_invalid_image(data)
        assert is_invalid
        assert "纯色" in reason

    @pytest.mark.asyncio
    async def test_gradient_image_valid(self):
        data = _png_bytes(_gradient_image())
        is_invalid, reason = await image_utils.check_invalid_image(data)
        assert not is_invalid
        assert reason == ""

    @pytest.mark.asyncio
    async def test_pixel_budget_guard_skips_huge_images(self, monkeypatch):
        """像素数超过上限时跳过检测（不展开大数组）"""
        monkeypatch.setattr(image_utils, "_MAX_IMAGE_PIXELS", 1000)
        data = _png_bytes(_gradient_image(64))  # 4096 像素 > 1000
        is_invalid, reason = await image_utils.check_invalid_image(data)
        assert not is_invalid
        assert reason == ""

    @pytest.mark.asyncio
    async def test_downscale_before_convert_keeps_detection(self, monkeypatch):
        """超过分析边长的图片先缩放，纯色检测仍然成立"""
        monkeypatch.setattr(image_utils, "_ANALYSIS_MAX_DIMENSION", 32)
        data = _png_bytes(Image.new("L", (200, 200), color=128))
        is_invalid, reason = await image_utils.check_invalid_image(data)
        assert is_invalid
        assert "纯色" in reason

    @pytest.mark.asyncio
    async def test_gradient_downscale_still_valid(self, monkeypatch):
        monkeypatch.setattr(image_utils, "_ANALYSIS_MAX_DIMENSION", 32)
        data = _png_bytes(_gradient_image(200))
        is_invalid, _ = await image_utils.check_invalid_image(data)
        assert not is_invalid


class TestComputePhash:
    """compute_phash：常规输出 + 像素上限防护"""

    @pytest.mark.asyncio
    async def test_returns_hex_hash(self):
        data = _png_bytes(_gradient_image())
        result = await image_utils.compute_phash(data)
        assert isinstance(result, str)
        assert len(result) == 16  # hash_size=8 → 64bit → 16 个十六进制字符

    @pytest.mark.asyncio
    async def test_pixel_budget_guard_returns_none(self, monkeypatch):
        monkeypatch.setattr(image_utils, "_MAX_IMAGE_PIXELS", 1000)
        data = _png_bytes(_gradient_image(64))
        assert await image_utils.compute_phash(data) is None
