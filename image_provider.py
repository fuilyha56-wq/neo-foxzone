"""Neo FoxZone 可替换图片生成 Provider。"""

from __future__ import annotations

import asyncio
import importlib
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

from src.app.plugin_system.api import service_api

from .config import NeoFoxzoneConfig
from .contracts import ExternalImageService

ImageStyle = Literal["photo", "drawing"]
ImageResult = str | list[str] | dict[str, Any] | None
ImageGenerator = Callable[[str, ImageStyle], Awaitable[list[str]]]

NAI_ARTIST_SERVICE_SIGNATURE = "nai_artist:service:nai_artist"
NAI_WARDROBE_SERVICE_SIGNATURE = "nai_artist:service:wardrobe"
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
    service = cast(ExternalImageService, raw_service)
    result = await getattr(service, method_name)(
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
    """适配 NAI Artist 的翻译、衣柜和裸 Base64 返回契约。"""
    raw_service = service_api.get_service(NAI_ARTIST_SERVICE_SIGNATURE)
    if raw_service is None:
        raise ImageProviderError(
            "NAI Artist Service 未注册，请安装并启用 nai_artist，或切换图片 provider。"
        )
    artist_config = getattr(getattr(raw_service, "plugin", None), "config", None)
    if artist_config is None:
        raise ImageProviderError("NAI Artist Service 没有可用配置。")

    outfit_context = ""
    wardrobe_config = getattr(artist_config, "wardrobe", None)
    if style == "photo" and bool(getattr(wardrobe_config, "enabled", False)):
        wardrobe = service_api.get_service(NAI_WARDROBE_SERVICE_SIGNATURE)
        if wardrobe is not None:
            if bool(getattr(wardrobe_config, "auto_daily", False)):
                apply_daily_rotation = getattr(wardrobe, "apply_daily_rotation", None)
                if callable(apply_daily_rotation):
                    apply_daily_rotation()
            get_outfit_tags = getattr(wardrobe, "get_outfit_tags", None)
            if callable(get_outfit_tags):
                outfit_context = str(get_outfit_tags() or "")

    prompt_builder = importlib.import_module("plugins.nai_artist.prompt_builder")
    action_module = importlib.import_module("plugins.nai_artist.action")
    translate = getattr(prompt_builder, "translate_to_nai_tags")
    get_style_hint = getattr(action_module, "get_style_hint")
    api_config = getattr(artist_config, "api", None)
    character_config = getattr(artist_config, "character", None)
    translate_model = ""
    get_translate_model = getattr(api_config, "get_translate_model", None)
    if callable(get_translate_model):
        translate_model = str(get_translate_model() or "")
    prompt_tags = await translate(
        description=description,
        style_hint=get_style_hint(style),
        translate_model=translate_model,
        character_profile=(
            str(getattr(character_config, "base_tags", ""))
            if style == "photo"
            else ""
        ),
        mode=style,
        outfit_context=outfit_context,
    )
    if not str(prompt_tags).strip():
        raise ImageProviderError("NAI Artist 未能把画面描述转换为提示词。")

    generate_image = getattr(raw_service, "generate_image", None)
    if generate_image is None or not callable(generate_image):
        raise ImageProviderError("NAI Artist Service 未实现 generate_image。")
    result = await generate_image(
        prompt_tags=str(prompt_tags),
        style_type=style,
        config=artist_config,
    )
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


__all__ = [
    "ImageProviderError",
    "ImageResult",
    "ImageStyle",
    "generate_images",
    "normalize_image_result",
]