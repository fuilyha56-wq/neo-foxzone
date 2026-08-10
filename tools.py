"""Neo FoxZone 的 QQ 空间 LLM Tool 组件。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, cast

from src.app.plugin_system.api import service_api
from src.app.plugin_system.base import BaseTool

from . import SERVICE_SIGNATURE
from .service import NeoFoxzoneError, NeoFoxzoneService, QzoneResponse

ToolResult = tuple[bool, str | dict[str, Any]]
ServiceCall = Callable[[NeoFoxzoneService], Awaitable[QzoneResponse]]


def _get_service() -> NeoFoxzoneService:
    """获取 Neo FoxZone Service 实例。"""
    service = service_api.get_service(SERVICE_SIGNATURE)
    if service is None:
        raise NeoFoxzoneError("Neo FoxZone Service 未注册。")
    return cast(NeoFoxzoneService, service)


async def _run_tool(action: str, call: ServiceCall) -> ToolResult:
    """执行 Service 调用并保留完整 OneBot 响应。"""
    try:
        service = _get_service()
        response = await call(service)
    except NeoFoxzoneError as error:
        return False, str(error)
    except Exception as error:
        return False, f"{action} 调用异常: {error}"

    result: dict[str, Any] = {
        "action": action,
        "response": response,
    }
    if service.response_succeeded(response):
        return True, result
    result["error"] = service.response_error(response)
    return False, result


class NeoFoxzoneListPostsTool(BaseTool):
    """获取当前 QQ 的说说列表。"""

    tool_name = "neo_foxzone_list_posts"
    tool_description = "获取当前登录 QQ 的空间说说列表"
    name = "neo_foxzone_list_posts"
    description = "获取当前登录 QQ 的空间说说列表，返回完整 OneBot 响应"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        pos: Annotated[int, "起始位置，从 0 开始"] = 0,
        num: Annotated[int, "获取数量"] = 10,
    ) -> ToolResult:
        """获取当前 QQ 的说说列表。"""
        return await _run_tool(
            "get_qzone_msg_list",
            lambda service: service.get_qzone_msg_list(pos=pos, num=num),
        )


class NeoFoxzoneListFeedsTool(BaseTool):
    """获取 QQ 空间好友动态流。"""

    tool_name = "neo_foxzone_list_feeds"
    tool_description = "获取当前登录 QQ 的好友空间动态"
    name = "neo_foxzone_list_feeds"
    description = "获取当前登录 QQ 的好友空间动态，返回完整 OneBot 响应"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        page_num: Annotated[int, "页码，从 1 开始"] = 1,
        count: Annotated[int, "每页数量"] = 10,
    ) -> ToolResult:
        """获取好友空间动态。"""
        return await _run_tool(
            "get_qzone_feeds",
            lambda service: service.get_qzone_feeds(
                page_num=page_num,
                count=count,
            ),
        )


class NeoFoxzonePublishTool(BaseTool):
    """发表说说，可附带图片。"""

    tool_name = "neo_foxzone_publish"
    tool_description = "发表 QQ 空间说说，可附图并设置查看权限"
    name = "neo_foxzone_publish"
    description = (
        "发表 QQ 空间说说；图片支持 file://、http(s)://、base64://，"
        "查看权限支持 1/4/16/64/128"
    )
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        content: Annotated[str, "说说正文"],
        images: Annotated[
            list[str] | None,
            "图片引用列表，支持 file://、http(s)://、base64://",
        ] = None,
        ugc_right: Annotated[
            int,
            "查看权限：1所有人、4好友、16部分好友、64仅自己、128部分好友不可见",
        ] = 1,
        target_uins: Annotated[
            list[int] | None,
            "权限目标 QQ 列表；ugc_right 为 16 或 128 时必填",
        ] = None,
    ) -> ToolResult:
        """发表说说。"""
        return await _run_tool(
            "send_qzone_msg",
            lambda service: service.send_qzone_msg(
                content=content,
                images=images,
                ugc_right=ugc_right,
                target_uins=target_uins,
            ),
        )


class NeoFoxzonePublishGeneratedTool(BaseTool):
    """等待图片 Service 生成完成后发表图文说说。"""

    tool_name = "neo_foxzone_publish_generated"
    tool_description = "根据画面描述生成图片，并与正文一次性发表 QQ 空间说说"
    name = "neo_foxzone_publish_generated"
    description = (
        "调用 Neo FoxZone 配置的图片 Provider，等待图片完整生成后，"
        "再把正文和图片作为同一条 QQ 空间说说发表"
    )
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        content: Annotated[str, "说说正文"],
        image_description: Annotated[str, "要生成的画面自然语言描述"],
        image_style: Annotated[
            Literal["photo", "drawing"],
            "图片风格：photo 或 drawing",
        ] = "drawing",
        ugc_right: Annotated[
            int,
            "查看权限：1所有人、4好友、16部分好友、64仅自己、128部分好友不可见",
        ] = 1,
        target_uins: Annotated[
            list[int] | None,
            "权限目标 QQ 列表；ugc_right 为 16 或 128 时必填",
        ] = None,
    ) -> ToolResult:
        """生成图片并发表说说。"""
        return await _run_tool(
            "send_generated_qzone_msg",
            lambda service: service.send_generated_qzone_msg(
                content=content,
                image_description=image_description,
                image_style=image_style,
                ugc_right=ugc_right,
                target_uins=target_uins,
            ),
        )


class NeoFoxzoneDeleteTool(BaseTool):
    """删除当前 QQ 发布的说说。"""

    tool_name = "neo_foxzone_delete"
    tool_description = "根据 tid 删除当前 QQ 发布的说说"
    name = "neo_foxzone_delete"
    description = "根据说说 ID tid 删除当前登录 QQ 发布的说说"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        tid: Annotated[str, "说说 ID"],
    ) -> ToolResult:
        """删除说说。"""
        return await _run_tool(
            "delete_qzone_msg",
            lambda service: service.delete_qzone_msg(tid=tid),
        )


class NeoFoxzoneLikeTool(BaseTool):
    """点赞说说。"""

    tool_name = "neo_foxzone_like"
    tool_description = "为指定 QQ 空间说说点赞"
    name = "neo_foxzone_like"
    description = "根据 tid 为说说点赞，可提供发布者 QQ 号 target_uin"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        tid: Annotated[str, "说说 ID"],
        target_uin: Annotated[int, "说说发布者 QQ 号；未知时填 0"] = 0,
    ) -> ToolResult:
        """点赞说说。"""
        return await _run_tool(
            "like_qzone",
            lambda service: service.like_qzone(
                tid=tid,
                target_uin=target_uin or None,
            ),
        )


class NeoFoxzoneUnlikeTool(BaseTool):
    """取消点赞说说。"""

    tool_name = "neo_foxzone_unlike"
    tool_description = "取消对指定 QQ 空间说说的点赞"
    name = "neo_foxzone_unlike"
    description = "根据 tid 取消说说点赞，可提供发布者 QQ 号 target_uin"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        tid: Annotated[str, "说说 ID"],
        target_uin: Annotated[int, "说说发布者 QQ 号；未知时填 0"] = 0,
    ) -> ToolResult:
        """取消点赞说说。"""
        return await _run_tool(
            "unlike_qzone",
            lambda service: service.unlike_qzone(
                tid=tid,
                target_uin=target_uin or None,
            ),
        )


class NeoFoxzoneCommentTool(BaseTool):
    """评论文字或图片说说。"""

    tool_name = "neo_foxzone_comment"
    tool_description = "评论 QQ 空间说说，可附带图片"
    name = "neo_foxzone_comment"
    description = "根据 tid 评论说说，可提供发布者 QQ 号和图片引用列表"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        tid: Annotated[str, "说说 ID"],
        content: Annotated[str, "评论正文"],
        target_uin: Annotated[int, "说说发布者 QQ 号；未知时填 0"] = 0,
        images: Annotated[
            list[str] | None,
            "评论图片引用列表，支持 file://、http(s)://、base64://",
        ] = None,
    ) -> ToolResult:
        """评论说说。"""
        return await _run_tool(
            "comment_qzone",
            lambda service: service.comment_qzone(
                tid=tid,
                content=content,
                target_uin=target_uin or None,
                images=images,
            ),
        )


class NeoFoxzoneSetBlacklistTool(BaseTool):
    """设置当前 QQ 空间黑名单。"""

    tool_name = "neo_foxzone_set_blacklist"
    tool_description = "拉黑或解除拉黑 QQ 空间用户"
    name = "neo_foxzone_set_blacklist"
    description = "把用户加入或移出当前登录 QQ 的空间黑名单"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        user_id: Annotated[int, "目标 QQ 号"],
        enable: Annotated[bool, "true 拉黑，false 解除拉黑"] = True,
    ) -> ToolResult:
        """设置空间黑名单。"""
        return await _run_tool(
            "set_qzone_ban",
            lambda service: service.set_qzone_ban(
                user_id=user_id,
                enable=enable,
            ),
        )


class NeoFoxzoneSetVisibilityTool(BaseTool):
    """修改已发布说说的查看权限。"""

    tool_name = "neo_foxzone_set_visibility"
    tool_description = "修改已发布 QQ 空间说说的查看权限"
    name = "neo_foxzone_set_visibility"
    description = (
        "修改说说查看权限；支持 1所有人、4好友、16部分好友、"
        "64仅自己、128部分好友不可见"
    )
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        tid: Annotated[str, "说说 ID"],
        ugc_right: Annotated[
            int,
            "查看权限：1所有人、4好友、16部分好友、64仅自己、128部分好友不可见",
        ],
        target_uins: Annotated[
            list[int] | None,
            "权限目标 QQ 列表；ugc_right 为 16 或 128 时必填",
        ] = None,
    ) -> ToolResult:
        """修改说说查看权限。"""
        return await _run_tool(
            "set_qzone_msg_right",
            lambda service: service.set_qzone_msg_right(
                tid=tid,
                ugc_right=ugc_right,
                target_uins=target_uins,
            ),
        )


READ_TOOLS: list[type[BaseTool]] = [
    NeoFoxzoneListPostsTool,
    NeoFoxzoneListFeedsTool,
]

WRITE_TOOLS: list[type[BaseTool]] = [
    NeoFoxzonePublishTool,
    NeoFoxzonePublishGeneratedTool,
    NeoFoxzoneDeleteTool,
    NeoFoxzoneLikeTool,
    NeoFoxzoneUnlikeTool,
    NeoFoxzoneCommentTool,
    NeoFoxzoneSetBlacklistTool,
    NeoFoxzoneSetVisibilityTool,
]

ALL_TOOLS: list[type[BaseTool]] = [*READ_TOOLS, *WRITE_TOOLS]

__all__ = [
    "ALL_TOOLS",
    "NeoFoxzoneCommentTool",
    "NeoFoxzoneDeleteTool",
    "NeoFoxzoneLikeTool",
    "NeoFoxzoneListFeedsTool",
    "NeoFoxzoneListPostsTool",
    "NeoFoxzonePublishGeneratedTool",
    "NeoFoxzonePublishTool",
    "NeoFoxzoneSetBlacklistTool",
    "NeoFoxzoneSetVisibilityTool",
    "NeoFoxzoneUnlikeTool",
    "READ_TOOLS",
    "WRITE_TOOLS",
]