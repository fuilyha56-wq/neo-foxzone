"""Neo FoxZone 使用的跨插件类型契约。"""

from __future__ import annotations

from typing import Any, Literal, Protocol


class OneBotQzoneService(Protocol):
    """OneBot Expand QQ 空间 Service 的最小稳定接口。"""

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


__all__ = ["ExternalImageService", "OneBotQzoneService"]