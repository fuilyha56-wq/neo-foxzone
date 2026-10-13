"""Neo FoxZone 使用的跨插件类型契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class TextSegment:
    text: str


@dataclass(frozen=True, slots=True)
class ImageSegment:
    image: str


@dataclass(frozen=True, slots=True)
class EmojiSegment:
    """Unicode Emoji text; numeric protocol-specific IDs are not portable."""

    code: str | int


@dataclass(frozen=True, slots=True)
class FaceSegment:
    face_id: str | int


@dataclass(frozen=True, slots=True)
class RawSegment:
    type: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NormalizedComment:
    comment_id: str
    root_comment_id: str | None
    parent_comment_id: str | None
    author_qq: str | None
    author_name: str
    content: str
    children: list["NormalizedComment"] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NormalizedPost:
    post_id: str
    owner_qq: str
    content: str
    images: list[str] = field(default_factory=list)
    comments: list[NormalizedComment] = field(default_factory=list)
    liked: bool | None = None
    visibility: int | None = None


class OneBotQzoneService(Protocol):
    """运行时发现的 QZone Service 最小接口，不要求特定插件实现。"""

    async def get_qzone_msg_list(
        self,
        pos: int = 0,
        num: int = 10,
    ) -> dict[str, Any]:
        """获取当前账号的说说列表。"""
        ...

    async def get_qzone_feeds(
        self,
        page_num: int = 1,
        count: int = 10,
    ) -> dict[str, Any]:
        """获取好友动态。"""
        ...

    async def get_qzone_msg_detail(
        self,
        tid: str,
        host_uin: int,
    ) -> dict[str, Any]:
        """获取单条说说及其完整评论树。"""
        ...

    async def get_qzone_user_feeds(
        self,
        *,
        host_uin: int,
        pos: int = 0,
        num: int = 5,
        self_uin: int | None = None,
    ) -> dict[str, Any]:
        """读取指定 QQ 可见的说说列表。"""
        ...

    async def send_qzone_msg(
        self,
        content: str,
        images: list[str] | None = None,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> dict[str, Any]:
        """发表说说。"""
        ...

    async def delete_qzone_msg(self, tid: str) -> dict[str, Any]:
        """删除说说。"""
        ...

    async def like_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> dict[str, Any]:
        """点赞说说。"""
        ...

    async def unlike_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> dict[str, Any]:
        """取消点赞。"""
        ...

    async def comment_qzone(
        self,
        tid: str,
        content: str,
        target_uin: int | None = None,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """评论说说。"""
        ...

    async def reply_qzone_comment(
        self,
        *,
        tid: str,
        host_uin: int,
        root_comment_id: str,
        target_uin: int,
        target_name: str,
        content: str,
        self_uin: int | None = None,
    ) -> dict[str, Any]:
        """在指定顶层评论下发送一条楼中楼回复。"""
        ...

    async def set_qzone_ban(
        self,
        user_id: int,
        enable: bool = True,
    ) -> dict[str, Any]:
        """设置 QQ 空间黑名单。"""
        ...

    async def set_qzone_msg_right(
        self,
        tid: str,
        ugc_right: int,
        target_uins: list[int] | None = None,
    ) -> dict[str, Any]:
        """修改说说查看权限。"""
        ...


class ExternalImageService(Protocol):
    """其他插件可实现的通用图片生成接口。"""

    async def generate_image_for_external(
        self,
        *,
        description: str,
        style: Literal["photo", "drawing"],
    ) -> str | list[str] | dict[str, Any] | None:
        """生成图片并返回图片引用、裸 Base64 或结构化结果。"""
        ...


__all__ = [
    "EmojiSegment",
    "ExternalImageService",
    "FaceSegment",
    "ImageSegment",
    "NormalizedComment",
    "NormalizedPost",
    "OneBotQzoneService",
    "RawSegment",
    "TextSegment",
]
