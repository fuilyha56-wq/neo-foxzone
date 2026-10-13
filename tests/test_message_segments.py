"""Tests for safe cross protocol QZone message segment conversion."""

from __future__ import annotations

import importlib

import pytest

module = importlib.import_module("plugins.neo-foxzone.message_segments")
contracts = importlib.import_module("plugins.neo-foxzone.contracts")


def test_text_unicode_emoji_and_images_are_preserved() -> None:
    """Portable text, Unicode emoji, and image references keep their order."""
    text, images = module.render_qzone_segments(
        [
            contracts.TextSegment("hello "),
            contracts.EmojiSegment("🐺"),
            contracts.ImageSegment("https://example.test/a.png"),
        ]
    )

    assert text == "hello 🐺"
    assert images == ["https://example.test/a.png"]


def test_unknown_protocol_segments_fail_closed() -> None:
    """Unknown and protocol-specific face IDs are never silently discarded."""
    with pytest.raises(module.UnsupportedMessageSegment, match="Face ID"):
        module.render_qzone_segments([contracts.FaceSegment(12)])
    with pytest.raises(module.UnsupportedMessageSegment, match="不支持协议专属"):
        module.render_qzone_segments([{"type": "video", "data": {"file": "x"}}])


def test_raw_text_and_image_segments_are_supported() -> None:
    """Compatible OneBot-style text and image objects are converted."""
    text, images = module.render_qzone_segments(
        [
            {"type": "text", "data": {"text": "caption"}},
            {"type": "image", "data": {"url": "file:///tmp/a.png"}},
        ]
    )

    assert text == "caption"
    assert images == ["file:///tmp/a.png"]


def test_text_after_image_is_rejected_when_order_cannot_be_preserved() -> None:
    """A flattened body plus image list must not silently reorder mixed content."""
    with pytest.raises(module.UnsupportedMessageSegment, match="无法保留图片后的文本顺序"):
        module.render_qzone_segments(
            [
                contracts.TextSegment("before"),
                contracts.ImageSegment("https://example.test/a.png"),
                contracts.TextSegment("after"),
            ]
        )
