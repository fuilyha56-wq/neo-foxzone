"""Neo FoxZone 管理命令。"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from typing import Literal, cast

from src.app.plugin_system.api import service_api
from src.app.plugin_system.base import BaseCommand, cmd_route
from src.app.plugin_system.types import PermissionLevel

from . import (
    ACCOUNT_SERVICE_SIGNATURE,
    BACKEND_SERVICE_SIGNATURE,
    SERVICE_SIGNATURE,
)
from .config import NeoFoxzoneConfig
from .service import NeoFoxzoneError, NeoFoxzoneService, QzoneResponse


def _parse_string_list(value: str) -> list[str] | None:
    """把逗号分隔字符串转换为非空字符串列表。"""
    result = [item.strip() for item in value.split(",") if item.strip()]
    return result or None


def _parse_int_list(value: str) -> list[int] | None:
    """把逗号分隔字符串转换为整数列表。"""
    if not value.strip():
        return None
    try:
        return [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise NeoFoxzoneError("QQ 号列表必须由逗号分隔的整数构成。") from error


class NeoFoxzoneCommand(BaseCommand):
    """提供全部 QQ 空间说说能力的运营者命令。"""

    command_name = "neo-foxzone"
    command_description = "Neo FoxZone QQ 空间说说管理命令"
    name = "neo-foxzone"
    description = "查询、发布、删除、互动和管理 QQ 空间说说"
    permission_level = PermissionLevel.OPERATOR
    command_prefix = "/"
    dependencies = [SERVICE_SIGNATURE]

    def _service(self) -> NeoFoxzoneService:
        """获取 Neo FoxZone Service。"""
        service = service_api.get_service(SERVICE_SIGNATURE)
        if service is None:
            raise NeoFoxzoneError("Neo FoxZone Service 未注册。")
        return cast(NeoFoxzoneService, service)

    def _output_limit(self, service: NeoFoxzoneService) -> int:
        """获取命令输出字符限制。"""
        config = service.plugin.config
        if isinstance(config, NeoFoxzoneConfig):
            return max(500, int(config.limits.max_command_output_chars))
        return 12000

    def _format_response(
        self,
        service: NeoFoxzoneService,
        response: QzoneResponse,
    ) -> str:
        """格式化并截断 OneBot 原始响应。"""
        rendered = json.dumps(
            response,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        limit = self._output_limit(service)
        if len(rendered) > limit:
            return f"{rendered[:limit]}\n...（输出已截断，共 {len(rendered)} 字符）"
        return rendered

    async def _run(
        self,
        operation: Awaitable[QzoneResponse],
        success_message: str,
    ) -> tuple[bool, str]:
        """执行命令调用并展示完整协议响应。"""
        try:
            service = self._service()
            response = await operation
        except NeoFoxzoneError as error:
            return False, str(error)
        except Exception as error:
            return False, f"QQ 空间调用异常: {error}"

        rendered = self._format_response(service, response)
        if service.response_succeeded(response):
            return True, f"{success_message}\n{rendered}"
        return False, f"{service.response_error(response)}\n{rendered}"

    @cmd_route()
    async def handle_help(self) -> tuple[bool, str]:
        """显示完整命令帮助。"""
        return True, (
            "用法：/neo-foxzone send [主题]\n"
            "Neo FoxZone 命令：\n"
            "/neo-foxzone status\n"
            "/neo-foxzone posts [pos] [num]\n"
            "/neo-foxzone feeds [page_num] [count]\n"
            "/neo-foxzone send [主题片段(最多6个)]\n"
            "/neo-foxzone publish \"正文\" [图片逗号列表] [权限] [QQ逗号列表]\n"
            "/neo-foxzone publish-ai \"正文\" \"画面描述\" [photo|drawing] [权限] [QQ逗号列表]\n"
            "/neo-foxzone poll-now\n"
            "/neo-foxzone poll-status\n"
            "/neo-foxzone delete <tid>\n"
            "/neo-foxzone like <tid> [发布者QQ]\n"
            "/neo-foxzone unlike <tid> [发布者QQ]\n"
            "/neo-foxzone comment <tid> \"正文\" [发布者QQ] [图片逗号列表]\n"
            "/neo-foxzone ban <QQ号> [true|false]\n"
            "/neo-foxzone visibility <tid> <权限> [QQ逗号列表]\n"
            "权限：1=所有人，4=好友，16=部分好友，64=仅自己，128=部分好友不可见。"
        )

    @cmd_route("send")
    async def handle_send(
        self,
        w0: str = "",
        w1: str = "",
        w2: str = "",
        w3: str = "",
        w4: str = "",
        w5: str = "",
    ) -> tuple[bool, str]:
        """以合并主题发表说说，保持原版 FoxZone 的 send 语义。"""
        try:
            service = self._service()
        except NeoFoxzoneError as error:
            return False, str(error)

        config = service.plugin.config
        if not getattr(config, "plugin", None) or not config.plugin.enabled:
            return False, "FoxZone 插件当前已禁用。"

        topic = " ".join(
            part for part in (w0, w1, w2, w3, w4, w5) if part
        ).strip()

        try:
            generated = await service.generate_topic_content(topic=topic)
        except NeoFoxzoneError as error:
            return False, f"发布说说失败：{error}"
        except Exception as error:
            return False, f"发布说说失败：{error}"

        if not generated.get("success"):
            return False, f"发布说说失败：{generated.get('message', '未知错误')}"

        content = str(generated.get("message", "")).strip()
        succeeded = await service.publish_feed(content)
        if not succeeded:
            return False, f"发布说说失败：{content}"
        return True, f"说说已发布！内容：{content}"

    @cmd_route("status")
    async def handle_status(self) -> tuple[bool, str]:
        """检查 Neo FoxZone 与前置 Service 是否已注册。"""
        own_service = service_api.get_service(SERVICE_SIGNATURE)
        backend_service = service_api.get_service(BACKEND_SERVICE_SIGNATURE)
        account_service = service_api.get_service(ACCOUNT_SERVICE_SIGNATURE)
        ready = (
            own_service is not None
            and backend_service is not None
            and account_service is not None
        )
        return ready, (
            f"Neo FoxZone Service: {'已就绪' if own_service else '未注册'}\n"
            f"OneBot Expand QZone Service: {'已就绪' if backend_service else '未注册'}\n"
            f"OneBot Expand Account Service: {'已就绪' if account_service else '未注册'}"
        )

    @cmd_route("posts")
    async def handle_posts(
        self,
        pos: int = 0,
        num: int = 10,
    ) -> tuple[bool, str]:
        """获取当前 QQ 的说说列表。"""
        service = self._service()
        return await self._run(
            service.get_qzone_msg_list(pos=pos, num=num),
            "说说列表获取成功。",
        )

    @cmd_route("feeds")
    async def handle_feeds(
        self,
        page_num: int = 1,
        count: int = 10,
    ) -> tuple[bool, str]:
        """获取好友空间动态。"""
        service = self._service()
        return await self._run(
            service.get_qzone_feeds(page_num=page_num, count=count),
            "好友动态获取成功。",
        )

    @cmd_route("publish")
    async def handle_publish(
        self,
        content: str,
        images: str = "",
        ugc_right: int = 1,
        target_uins: str = "",
    ) -> tuple[bool, str]:
        """发表说说，带空格的正文和 URL 列表请使用引号包裹。"""
        service = self._service()
        return await self._run(
            service.send_qzone_msg(
                content=content,
                images=_parse_string_list(images),
                ugc_right=ugc_right,
                target_uins=_parse_int_list(target_uins),
            ),
            "说说发表成功。",
        )

    @cmd_route("publish-ai")
    async def handle_publish_ai(
        self,
        content: str,
        image_description: str,
        image_style: str = "drawing",
        ugc_right: int = 1,
        target_uins: str = "",
    ) -> tuple[bool, str]:
        """等待配置的图片 Provider 完成生图后发表图文说说。"""
        raw_style = image_style.strip().lower()
        if raw_style not in {"photo", "drawing"}:
            return False, "图片风格仅支持 photo 或 drawing。"
        normalized_style = cast(Literal["photo", "drawing"], raw_style)
        service = self._service()
        return await self._run(
            service.send_generated_qzone_msg(
                content=content,
                image_description=image_description,
                image_style=normalized_style,
                ugc_right=ugc_right,
                target_uins=_parse_int_list(target_uins),
            ),
            "AI 配图说说发表成功。",
        )

    @staticmethod
    def _format_poll_report(report: object) -> str:
        """把自动回复轮询报告格式化为运营者可读文本。"""
        query_errors = list(getattr(report, "query_errors", []) or [])
        reply_errors = list(getattr(report, "reply_errors", []) or [])
        lines = [
            "说说评论检查完成。",
            (
                f"候选={int(getattr(report, 'candidates', 0))}，"
                f"已跳过={int(getattr(report, 'skipped_processed', 0))}，"
                f"处理中={int(getattr(report, 'skipped_in_flight', 0))}，"
                f"退避={int(getattr(report, 'skipped_backoff', 0))}，"
                f"回复={int(getattr(report, 'replied', 0))}，"
                f"失败={int(getattr(report, 'failed', 0))}"
            ),
        ]
        if query_errors:
            lines.append("查询错误：" + "；".join(str(item) for item in query_errors))
        if reply_errors:
            lines.append("回复错误：" + "；".join(str(item) for item in reply_errors))
        state_errors = list(getattr(report, "state_errors", []) or [])
        if state_errors:
            lines.append("状态错误：" + "；".join(str(item) for item in state_errors))
        return "\n".join(lines)

    @cmd_route("poll-now")
    async def handle_poll_now(self) -> tuple[bool, str]:
        """立即复用当前轮询器检查一次未回复评论。"""
        poll_now = getattr(self.plugin, "poll_now", None)
        if poll_now is None or not callable(poll_now):
            return False, "当前插件实例不支持手动轮询。"
        try:
            report = await poll_now()
        except Exception as error:
            return False, f"说说评论检查失败: {error}"
        success = (
            not getattr(report, "query_errors", [])
            and not getattr(report, "state_errors", [])
            and int(getattr(report, "failed", 0)) == 0
        )
        return success, self._format_poll_report(report)

    @cmd_route("poll-status")
    async def handle_poll_status(self) -> tuple[bool, str]:
        """查看最近一次自动或手动轮询报告。"""
        get_report = getattr(self.plugin, "get_poll_report", None)
        if get_report is None or not callable(get_report):
            return False, "当前插件实例不支持轮询状态查询。"
        report = get_report()
        if report is None:
            return False, "尚无轮询报告，或自动回复轮询未启用。"
        return True, self._format_poll_report(report)

    @cmd_route("delete")
    async def handle_delete(self, tid: str) -> tuple[bool, str]:
        """删除指定说说。"""
        service = self._service()
        return await self._run(
            service.delete_qzone_msg(tid=tid),
            "说说删除成功。",
        )

    @cmd_route("like")
    async def handle_like(
        self,
        tid: str,
        target_uin: int = 0,
    ) -> tuple[bool, str]:
        """点赞指定说说。"""
        service = self._service()
        return await self._run(
            service.like_qzone(tid=tid, target_uin=target_uin or None),
            "点赞成功。",
        )

    @cmd_route("unlike")
    async def handle_unlike(
        self,
        tid: str,
        target_uin: int = 0,
    ) -> tuple[bool, str]:
        """取消点赞指定说说。"""
        service = self._service()
        return await self._run(
            service.unlike_qzone(tid=tid, target_uin=target_uin or None),
            "已取消点赞。",
        )

    @cmd_route("comment")
    async def handle_comment(
        self,
        tid: str,
        content: str,
        target_uin: int = 0,
        images: str = "",
    ) -> tuple[bool, str]:
        """评论指定说说。"""
        service = self._service()
        return await self._run(
            service.comment_qzone(
                tid=tid,
                content=content,
                target_uin=target_uin or None,
                images=_parse_string_list(images),
            ),
            "评论发送成功。",
        )

    @cmd_route("ban")
    async def handle_ban(
        self,
        user_id: int,
        enable: bool = True,
    ) -> tuple[bool, str]:
        """拉黑或解除拉黑空间用户。"""
        service = self._service()
        return await self._run(
            service.set_qzone_ban(user_id=user_id, enable=enable),
            "空间黑名单设置成功。",
        )

    @cmd_route("visibility")
    async def handle_visibility(
        self,
        tid: str,
        ugc_right: int,
        target_uins: str = "",
    ) -> tuple[bool, str]:
        """修改已发布说说的查看权限。"""
        service = self._service()
        return await self._run(
            service.set_qzone_msg_right(
                tid=tid,
                ugc_right=ugc_right,
                target_uins=_parse_int_list(target_uins),
            ),
            "说说查看权限修改成功。",
        )


__all__ = ["NeoFoxzoneCommand"]