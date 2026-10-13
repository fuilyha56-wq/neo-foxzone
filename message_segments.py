"""把结构化消息段转换为 QZone 的正文与图片字段。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import EmojiSegment, FaceSegment, ImageSegment, RawSegment, TextSegment


class UnsupportedMessageSegment(ValueError):
    """当前已发现协议端契约不能表达的消息段。"""


def render_qzone_segments(segments: Iterable[Any]) -> tuple[str, list[str]]:
    """转换文本、Unicode Emoji 和图片段；不猜测协议专属表情 ID。"""
    text_parts: list[str] = []
    images: list[str] = []
    image_seen = False

    def add_text(value: Any) -> None:
        if image_seen:
            raise UnsupportedMessageSegment(
                "当前统一正文/图片契约无法保留图片后的文本顺序"
            )
        text_parts.append(str(value))

    def add_image(value: str) -> None:
        nonlocal image_seen
        images.append(value)
        image_seen = True

    def add_raw(segment_type: str, data: Any) -> None:
        if not isinstance(data, dict):
            raise UnsupportedMessageSegment(f"{segment_type}:data 不是对象")
        if segment_type == "text":
            add_text(data.get("text") or "")
        elif segment_type == "image":
            image = data.get("url") or data.get("file") or data.get("image")
            if not isinstance(image, str) or not image.strip():
                raise UnsupportedMessageSegment("image 段缺少图片引用")
            add_image(image.strip())
        else:
            raise UnsupportedMessageSegment(f"不支持协议专属消息段: {segment_type}")

    for segment in segments:
        if isinstance(segment, TextSegment):
            add_text(segment.text)
        elif isinstance(segment, ImageSegment):
            add_image(segment.image)
        elif isinstance(segment, EmojiSegment):
            if not isinstance(segment.code, str):
                raise UnsupportedMessageSegment("数值 Emoji/face ID 不是跨协议格式")
            add_text(segment.code)
        elif isinstance(segment, FaceSegment):
            raise UnsupportedMessageSegment("协议专属 Face ID 未经当前适配器确认")
        elif isinstance(segment, RawSegment):
            add_raw(segment.type, segment.data)
        elif isinstance(segment, dict):
            add_raw(str(segment.get("type") or ""), segment.get("data"))
        else:
            raise UnsupportedMessageSegment(
                f"无法识别消息段类型: {type(segment).__name__}"
            )

    return "".join(text_parts), images


__all__ = ["UnsupportedMessageSegment", "render_qzone_segments"]
