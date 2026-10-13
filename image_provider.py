"""Neo FoxZone 可替换图片生成 Provider。"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from src.app.plugin_system.api import service_api

from .config import NeoFoxzoneConfig

ImageStyle = Literal["photo", "drawing"]
ImageResult = str | list[str] | dict[str, Any] | None
ImageGenerator = Callable[[str, ImageStyle], Awaitable[list[str]]]

NAI_ARTIST_SERVICE_SIGNATURE = "nai_artist:service:nai_artist"
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/\r\n]+={0,2}$")


class ImageProviderError(RuntimeError):
    """图片 Provider 无法生成可用于 QQ 空间的图片时抛出。"""


def _normalize_single_image(value: str, *, assume_base64: bool = False) -> str:
    """把常见图片结果统一为 OneBot QZone 可接受的引用。"""
    image = value.strip()
    if not image:
        raise ImageProviderError("图片 Provider 返回了空字符串。")
    if image.startswith("base64|"):
        return f"base64://{image[7:]}"
    if image.startswith("data:"):
        marker = ";base64,"
        if marker not in image:
            raise ImageProviderError("图片 data URI 不是 Base64 编码。")
        return f"base64://{image.split(marker, 1)[1]}"
    if image.startswith(("base64://", "file://", "http://", "https://")):
        return image
    compact = "".join(image.split())
    if assume_base64 or (len(compact) >= 64 and _BASE64_PATTERN.fullmatch(compact)):
        return f"base64://{compact}"
    raise ImageProviderError(
        "图片 Provider 返回值不是 URL、file://、base64:// 或可识别的裸 Base64。"
    )


def normalize_image_result(
    result: ImageResult,
    *,
    assume_base64: bool = False,
) -> list[str]:
    """把不同图片 Service 的常见返回结构归一化为图片引用列表。"""
    if result is None:
        raise ImageProviderError("图片生成失败，Provider 未返回结果。")
    if isinstance(result, str):
        return [_normalize_single_image(result, assume_base64=assume_base64)]
    if isinstance(result, list):
        images = [
            _normalize_single_image(str(item), assume_base64=assume_base64)
            for item in result
            if str(item).strip()
        ]
        if not images:
            raise ImageProviderError("图片 Provider 未返回任何图片。")
        return images
    if isinstance(result, dict):
        for key in ("images", "image_refs", "urls"):
            value = result.get(key)
            if isinstance(value, list):
                return normalize_image_result(value, assume_base64=assume_base64)
        for key in ("image", "image_ref", "base64", "url", "path"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return normalize_image_result(value, assume_base64=assume_base64)
    raise ImageProviderError("图片 Provider 返回了无法识别的结果结构。")


async def _generate_with_standard_service(
    config: NeoFoxzoneConfig,
    description: str,
    style: ImageStyle,
) -> list[str]:
    """调用实现 Neo FoxZone 通用图片契约的任意 Service。"""
    signature = config.image.service_signature.strip()
    if not signature:
        raise ImageProviderError("provider=service 时必须配置 image.service_signature。")
    raw_service = service_api.get_service(signature)
    if raw_service is None:
        raise ImageProviderError(f"图片 Service 未注册: {signature}")
    method_name = config.image.service_method.strip() or "generate_image_for_external"
    method = getattr(raw_service, method_name, None)
    if method is None or not callable(method):
        raise ImageProviderError(
            f"图片 Service {signature} 未实现方法 {method_name}(description, style)。"
        )
    result = await method(
        description=description,
        style=style,
    )
    images = normalize_image_result(result)
    if not images:
        raise ImageProviderError("图片 Service 未返回任何图片。")
    return images


async def _generate_with_nai_artist(
    description: str,
    style: ImageStyle,
) -> list[str]:
    """通过 NAI Artist 注册的外部生图 Service 契约生成图片。"""
    raw_service = service_api.get_service(NAI_ARTIST_SERVICE_SIGNATURE)
    if raw_service is None:
        raise ImageProviderError(
            "NAI Artist Service 未注册，请安装并启用 nai_artist，或切换图片 provider。"
        )
    generate = getattr(raw_service, "generate_image_for_external", None)
    if not callable(generate):
        raise ImageProviderError(
            "NAI Artist Service 未实现 generate_image_for_external；请更新 nai_artist。"
        )
    result = await generate(description=description, style=style)
    return normalize_image_result(result, assume_base64=True)


async def generate_images(
    config: NeoFoxzoneConfig,
    description: str,
    style: ImageStyle | None = None,
) -> list[str]:
    """根据配置选择 Provider，等待生图完成并返回 QZone 图片引用。"""
    normalized_description = description.strip()
    if not normalized_description:
        raise ImageProviderError("生图描述不能为空。")
    selected_style: ImageStyle = style or config.image.default_style
    provider = config.image.provider
    if provider == "disabled":
        raise ImageProviderError("Neo FoxZone 图片生成功能已禁用。")
    generation: Awaitable[list[str]]
    if provider == "nai_artist":
        generation = _generate_with_nai_artist(
            normalized_description,
            selected_style,
        )
    elif provider == "service":
        generation = _generate_with_standard_service(
            config,
            normalized_description,
            selected_style,
        )
    else:
        raise ImageProviderError(f"未知图片 Provider: {provider}")
    timeout = max(0.1, float(config.image.timeout_seconds))
    try:
        images = await asyncio.wait_for(generation, timeout=timeout)
    except TimeoutError as error:
        raise ImageProviderError(
            f"图片 Provider 在 {timeout:g} 秒内未完成，生成已超时。"
        ) from error
    if not images:
        raise ImageProviderError("图片 Provider 未返回任何图片。")
    return images


def normalize_image_references(images: list[str] | None) -> list[str] | None:
    """归一化手动提供的图片 URL、文件引用和 Base64 引用。"""
    if images is None:
        return None
    non_empty = [str(image).strip() for image in images if str(image).strip()]
    if not non_empty:
        return []
    try:
        return normalize_image_result(non_empty)
    except ImageProviderError:
        raise


__all__ = [
    "ImageProviderError",
    "ImageResult",
    "ImageStyle",
    "generate_images",
    "normalize_image_references",
    "normalize_image_result",
]
