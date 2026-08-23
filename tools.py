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


class QzoneReadFeedTool(BaseTool):
    """按原版契约读取指定 QQ 的说说与完整评论。"""

    tool_name = "qzone_read_feed"
    tool_description = "读取指定 QQ 用户最近的 QQ 空间说说，包含正文、评论等完整内容"
    name = "qzone_read_feed"
    description = "读取指定 QQ 用户最近的 QQ 空间说说，包含正文、评论等完整内容"
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        target_qq: Annotated[str, "要查看其说说的 QQ 号（纯数字字符串）"],
        num: Annotated[int, "读取几条说说，默认 5 条，最多 20 条"] = 5,
    ) -> tuple[bool, str]:
        """读取指定 QQ 的说说列表及评论。"""
        try:
            service = _get_service()
            feeds = await service.list_feeds(
                target_qq=target_qq,
                num=num,
                skip_commented=False,
            )
        except NeoFoxzoneError as error:
            return False, str(error)
        except Exception as error:
            return False, f"读取说说失败: {error}"

        normalized_qq = str(target_qq).strip()
        if not feeds:
            return True, f"QQ {normalized_qq} 的空间暂无说说或无法访问。"

        lines = [f"=== QQ {normalized_qq} 最近 {len(feeds)} 条说说 ===\n"]
        for index, feed in enumerate(feeds, start=1):
            lines.append(_format_legacy_feed(index, feed))
        return True, "\n".join(lines)


def _format_legacy_feed(index: int, feed: dict[str, Any]) -> str:
    """按原版 ReadFeedTool 的文本形状格式化单条说说。"""
    tid = str(feed.get("tid", ""))
    content = str(
        feed.get("content") or feed.get("rt_con") or "（无正文）"
    ).strip()
    created_time = str(feed.get("created_time", "")).strip()
    images = [str(url) for url in feed.get("images", []) if url]
    comments = list(feed.get("comments", []))

    parts: list[str] = [f"【说说 {index}】"]
    if created_time:
        parts[0] += f"  {created_time}"
    if tid:
        parts[0] += f"  (tid={tid})"
    parts.append(f"内容：{content}")
    for image_index, url in enumerate(images, start=1):
        cached = ""
        parts.append(f"图片{image_index}：{cached or '（内容未识别）'} ({url})")
    if comments:
        parts.append(f"评论（共 {len(comments)} 条）：")
        for comment in comments:
            nickname = str(comment.get("nickname", "")).strip() or "匿名"
            qq = str(comment.get("qq_account", "")).strip()
            comment_tid = str(comment.get("comment_tid", "")).strip()
            line = f"  · [{nickname}"
            if qq:
                line += f"({qq})"
            line += "]"
            if comment_tid:
                line += f" (ctid={comment_tid})"
            line += f"：{str(comment.get('content', '')).strip()}"
            parts.append(line)
    else:
        parts.append("评论：暂无")
    parts.append("")
    return "\n".join(parts)


class QzonePostCommentTool(BaseTool):
    """按原版契约在指定说说下发表评论并记录互动。"""

    tool_name = "qzone_post_comment"
    tool_description = (
        "在指定 QQ 用户的某条说说下发表一条评论。"
        "需要先通过 qzone_read_feed 读取说说获得 tid，再用此工具评论。"
    )
    name = "qzone_post_comment"
    description = (
        "在指定 QQ 用户的某条说说下发表一条评论。"
        "需要先通过 qzone_read_feed 读取说说获得 tid，再用此工具评论。"
    )
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        target_qq: Annotated[str, "说说主人的 QQ 号（纯数字）"],
        feed_id: Annotated[str, "说说的 tid（由 qzone_read_feed 返回）"],
        comment_text: Annotated[str, "评论正文"],
    ) -> tuple[bool, str]:
        """发表评论并记录互动状态。"""
        normalized_qq = str(target_qq).strip()
        normalized_feed_id = str(feed_id).strip()
        text = str(comment_text).strip()
        if not normalized_qq.isdigit():
            return False, f"'{target_qq}' 不是有效的 QQ 号"
        if not normalized_feed_id:
            return False, "feed_id 不能为空"
        if not text:
            return False, "评论内容不能为空"

        try:
            service = _get_service()
            succeeded = await service.comment(
                normalized_qq,
                normalized_feed_id,
                text,
            )
        except NeoFoxzoneError as error:
            return False, str(error)
        except Exception as error:
            return False, f"评论失败: {error}"

        if not succeeded:
            return False, f"评论失败（tid={normalized_feed_id}）"
        await service.mark_interaction(
            normalized_qq,
            normalized_feed_id,
            "commented",
            "agent",
        )
        return True, f"已成功评论（tid={normalized_feed_id}）：{text}"


class QzoneLikeFeedTool(BaseTool):
    """按原版契约为指定说说点赞并记录互动。"""

    tool_name = "qzone_like_feed"
    tool_description = (
        "为指定 QQ 用户的某条说说点赞。"
        "需要先通过 qzone_read_feed 读取说说获得 tid，再用此工具点赞。"
    )
    name = "qzone_like_feed"
    description = (
        "为指定 QQ 用户的某条说说点赞。"
        "需要先通过 qzone_read_feed 读取说说获得 tid，再用此工具点赞。"
    )
    dependencies = [SERVICE_SIGNATURE]

    async def execute(
        self,
        target_qq: Annotated[str, "说说主人的 QQ 号（纯数字）"],
        feed_id: Annotated[str, "说说的 tid（由 qzone_read_feed 返回）"],
    ) -> tuple[bool, str]:
        """点赞并记录互动状态。"""
        normalized_qq = str(target_qq).strip()
        normalized_feed_id = str(feed_id).strip()
        if not normalized_qq.isdigit():
            return False, f"'{target_qq}' 不是有效的 QQ 号"
        if not normalized_feed_id:
            return False, "feed_id 不能为空"

        try:
            service = _get_service()
            succeeded = await service.like(
                normalized_qq,
                normalized_feed_id,
            )
        except NeoFoxzoneError as error:
            return False, str(error)
        except Exception as error:
            return False, f"点赞失败: {error}"

        if not succeeded:
            return False, f"点赞失败（tid={normalized_feed_id}）"
        await service.mark_interaction(
            normalized_qq,
            normalized_feed_id,
            "liked",
            "agent",
        )
        return True, f"已为说说 {normalized_feed_id} 点赞"


READ_TOOLS: list[type[BaseTool]] = [
    NeoFoxzoneListPostsTool,
    NeoFoxzoneListFeedsTool,
    QzoneReadFeedTool,
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
    QzonePostCommentTool,
    QzoneLikeFeedTool,
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
    "QzoneLikeFeedTool",
    "QzonePostCommentTool",
    "QzoneReadFeedTool",
    "READ_TOOLS",
    "WRITE_TOOLS",
]