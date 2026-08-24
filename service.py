"""基于 OneBot Expand 的 QQ 空间统一 Service。"""

from __future__ import annotations

import base64
from typing import Any, Literal, cast

from src.app.plugin_system.api import service_api
from src.app.plugin_system.base import BaseService

from . import ACCOUNT_SERVICE_SIGNATURE, BACKEND_SERVICE_SIGNATURE
from .config import NeoFoxzoneConfig
from .contracts import OneBotQzoneService
from .core.llm.content_service import ContentService
from .image_provider import ImageProviderError, generate_images

QzoneResponse = dict[str, Any]
VALID_UGC_RIGHTS = frozenset({1, 4, 16, 64, 128})


class NeoFoxzoneError(RuntimeError):
    """Neo FoxZone 无法执行调用时抛出的业务异常。"""


class NeoFoxzoneService(BaseService):
    """通过 OneBot Expand 暴露全部 QQ 空间说说能力。"""

    service_name = "qzone_service"
    service_description = "基于 OneBot Expand 的 QQ 空间说说全功能服务"
    name = "qzone_service"
    description = "基于 OneBot Expand 的 QQ 空间说说全功能服务"
    version = "0.1.4"
    dependencies = [BACKEND_SERVICE_SIGNATURE]

    def _config(self) -> NeoFoxzoneConfig:
        """返回当前插件配置，测试或异常装配时使用默认值。"""
        config = self.plugin.config
        if isinstance(config, NeoFoxzoneConfig):
            return config
        return NeoFoxzoneConfig()

    @property
    def _runtime(self) -> Any:
        """获取插件级共享运行时，拒绝未完成生命周期初始化的调用。"""
        runtime = getattr(self.plugin, "runtime", None)
        if runtime is None:
            raise NeoFoxzoneError("FoxZone 共享运行时尚未初始化。")
        return runtime

    def _backend(self) -> OneBotQzoneService:
        """获取 OneBot Expand QQ 空间 Service。"""
        if not self._config().plugin.enabled:
            raise NeoFoxzoneError("Neo FoxZone 当前已在配置中禁用。")

        backend = service_api.get_service(BACKEND_SERVICE_SIGNATURE)
        if backend is None:
            raise NeoFoxzoneError(
                "前置服务 onebot_expand:service:qzone_service 未注册，"
                "请确认 OneBot Expand 已安装并启用。"
            )
        return cast(OneBotQzoneService, backend)

    def _validate_query(
        self,
        offset: int,
        count: int,
        *,
        minimum: int = 0,
    ) -> None:
        """校验分页参数。"""
        if offset < minimum:
            raise NeoFoxzoneError(f"分页位置或页码不能小于 {minimum}。")
        maximum = max(1, int(self._config().limits.max_query_count))
        if count < 1 or count > maximum:
            raise NeoFoxzoneError(f"查询数量必须在 1 到 {maximum} 之间。")

    def _validate_tid(self, tid: str) -> str:
        """校验并清理说说 ID。"""
        normalized = str(tid).strip()
        if not normalized:
            raise NeoFoxzoneError("说说 ID tid 不能为空。")
        return normalized

    def _validate_user_id(self, user_id: int, field_name: str) -> int:
        """校验 QQ 号。"""
        normalized = int(user_id)
        if normalized <= 0:
            raise NeoFoxzoneError(f"{field_name} 必须是正整数 QQ 号。")
        return normalized

    def _normalize_images(self, images: list[str] | None) -> list[str] | None:
        """清理图片引用并限制数量。"""
        if images is None:
            return None
        normalized = [str(image).strip() for image in images if str(image).strip()]
        maximum = max(0, int(self._config().limits.max_images))
        if len(normalized) > maximum:
            raise NeoFoxzoneError(f"图片数量不能超过 {maximum} 张。")
        return normalized

    def _normalize_targets(
        self,
        target_uins: list[int] | None,
    ) -> list[int] | None:
        """校验并去重权限目标 QQ 号。"""
        if target_uins is None:
            return None
        normalized: list[int] = []
        for target_uin in target_uins:
            user_id = self._validate_user_id(target_uin, "target_uins")
            if user_id not in normalized:
                normalized.append(user_id)
        return normalized

    def _validate_right(
        self,
        ugc_right: int,
        target_uins: list[int] | None,
    ) -> tuple[int, list[int] | None]:
        """校验 QQ 空间可见权限及目标名单。"""
        normalized_right = int(ugc_right)
        if normalized_right not in VALID_UGC_RIGHTS:
            allowed = ", ".join(str(value) for value in sorted(VALID_UGC_RIGHTS))
            raise NeoFoxzoneError(f"ugc_right 仅支持: {allowed}。")
        normalized_targets = self._normalize_targets(target_uins)
        if normalized_right in {16, 128} and not normalized_targets:
            raise NeoFoxzoneError(
                "ugc_right 为 16 或 128 时必须提供 target_uins。"
            )
        return normalized_right, normalized_targets

    @staticmethod
    def response_succeeded(response: QzoneResponse) -> bool:
        """判断 OneBot 响应是否成功。"""
        status = response.get("status")
        if status is not None:
            return str(status).lower() == "ok"
        return response.get("retcode") == 0

    @staticmethod
    def response_error(response: QzoneResponse) -> str:
        """从不同 OneBot 实现的响应字段中提取错误信息。"""
        for key in ("msg", "wording", "message"):
            value = response.get(key)
            if value:
                return str(value)
        retcode = response.get("retcode")
        return f"协议端调用失败（retcode={retcode!r}）"

    @staticmethod
    def _response_data(response: QzoneResponse) -> dict[str, Any]:
        """提取兼容 OneBot 响应中的 data 字典。"""
        data = response.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _flatten_comments(
        comments: list[dict[str, Any]],
        *,
        parent_tid: str = "",
    ) -> list[dict[str, Any]]:
        """将 QZone 嵌套评论树转换为原版 Service 的平铺评论列表。"""
        flattened: list[dict[str, Any]] = []
        for comment in comments:
            comment_tid = str(
                comment.get("comment_id")
                or comment.get("comment_tid")
                or comment.get("tid")
                or ""
            ).strip()
            if not comment_tid:
                continue
            normalized_parent = str(
                comment.get("parent_comment_id")
                or comment.get("parent_tid")
                or parent_tid
                or ""
            ).strip()
            normalized = {
                "comment_tid": comment_tid,
                "parent_tid": normalized_parent,
                "qq_account": str(comment.get("uin") or comment.get("qq_account") or "").strip(),
                "nickname": str(comment.get("nickname") or comment.get("name") or "").strip(),
                "content": str(comment.get("content") or "").strip(),
            }
            flattened.append(normalized)
            children = comment.get("list_3")
            if isinstance(children, list):
                flattened.extend(
                    NeoFoxzoneService._flatten_comments(
                        [child for child in children if isinstance(child, dict)],
                        parent_tid=comment_tid,
                    )
                )
        return flattened

    @classmethod
    def _legacy_feed(cls, feed: dict[str, Any]) -> dict[str, Any]:
        """将内部兼容层说说收敛为原版 Service 的稳定字段。"""
        comments = feed.get("commentlist") or feed.get("comments") or []
        normalized_comments = cls._flatten_comments(
            [comment for comment in comments if isinstance(comment, dict)]
        )
        return {
            "tid": str(feed.get("tid") or feed.get("key") or feed.get("id") or "").strip(),
            "target_qq": str(
                feed.get("uin") or feed.get("target_qq") or feed.get("host_uin") or ""
            ).strip(),
            "uin": str(feed.get("uin") or feed.get("target_qq") or feed.get("host_uin") or "").strip(),
            "content": str(feed.get("content") or feed.get("rt_con") or "").strip(),
            "created_time": str(feed.get("created_time") or "").strip(),
            "images": [
                str(image)
                for image in feed.get("images", [])
                if str(image).strip()
            ],
            "comments": normalized_comments,
            "commentlist": [
                comment for comment in comments if isinstance(comment, dict)
            ],
            "comment_count": len(normalized_comments),
            "liked": bool(feed.get("liked")),
        }

    async def _load_self_uin(self) -> int | None:
        """从账号 Service 读取当前 Bot QQ，无法确认时返回 ``None``。"""
        account_service = service_api.get_service(ACCOUNT_SERVICE_SIGNATURE)
        get_login_info = getattr(account_service, "get_login_info", None)
        if get_login_info is None or not callable(get_login_info):
            return None
        try:
            response = await get_login_info()
        except Exception:
            return None
        if not isinstance(response, dict) or not self.response_succeeded(response):
            return None
        payload = self._response_data(response)
        raw_uin = payload.get("user_id") or payload.get("self_id") or payload.get("uin")
        try:
            uin = int(raw_uin)
        except (TypeError, ValueError):
            return None
        return uin if uin > 0 else None

    async def get_qzone_msg_list(
        self,
        pos: int = 0,
        num: int = 10,
    ) -> QzoneResponse:
        """获取当前登录 QQ 的说说列表。"""
        self._validate_query(pos, num)
        return await self._backend().get_qzone_msg_list(pos=pos, num=num)

    async def get_qzone_feeds(
        self,
        page_num: int = 1,
        count: int = 10,
    ) -> QzoneResponse:
        """获取当前登录 QQ 的好友动态。"""
        self._validate_query(page_num, count, minimum=1)
        return await self._backend().get_qzone_feeds(
            page_num=page_num,
            count=count,
        )

    async def get_qzone_msg_detail(
        self,
        tid: str,
        host_uin: int,
    ) -> QzoneResponse:
        """获取单条说说详情及其可验证的完整评论树。"""
        return await self._backend().get_qzone_msg_detail(
            tid=self._validate_tid(tid),
            host_uin=self._validate_user_id(host_uin, "host_uin"),
        )

    async def get_qzone_user_feeds(
        self,
        *,
        host_uin: int,
        pos: int = 0,
        num: int = 5,
        self_uin: int | None = None,
    ) -> QzoneResponse:
        """经 OneBot Expand 内部兼容层读取指定 QQ 可见的说说列表。"""
        self._validate_query(pos, num)
        normalized_self_uin = (
            self._validate_user_id(self_uin, "self_uin")
            if self_uin is not None
            else None
        )
        return await self._backend().get_qzone_user_feeds(
            host_uin=self._validate_user_id(host_uin, "host_uin"),
            pos=pos,
            num=num,
            self_uin=normalized_self_uin,
        )

    async def send_qzone_msg(
        self,
        content: str,
        images: list[str] | None = None,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> QzoneResponse:
        """发表说说，可附带图片并在发布时设置查看权限。"""
        normalized_images = self._normalize_images(images)
        normalized_content = str(content).strip()
        if not normalized_content:
            if not normalized_images:
                raise NeoFoxzoneError("说说正文与图片不能同时为空。")
            raise NeoFoxzoneError("当前 OneBot 后端要求说说正文不能为空。")
        normalized_right, normalized_targets = self._validate_right(
            ugc_right,
            target_uins,
        )
        return await self._backend().send_qzone_msg(
            content=normalized_content,
            images=normalized_images,
            ugc_right=normalized_right,
            target_uins=normalized_targets,
        )

    async def send_generated_qzone_msg(
        self,
        content: str,
        image_description: str,
        image_style: Literal["photo", "drawing"] | None = None,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> QzoneResponse:
        """等待配置的图片 Service 生成完成，再把正文与图片一次性发表。"""
        normalized_content = str(content).strip()
        if not normalized_content:
            raise NeoFoxzoneError("AI 配图说说正文不能为空。")
        try:
            images = await generate_images(
                self._config(),
                image_description,
                image_style,
            )
        except ImageProviderError as error:
            raise NeoFoxzoneError(str(error)) from error
        if not images:
            raise NeoFoxzoneError("图片 Provider 未返回任何图片，已取消发布。")
        return await self.send_qzone_msg(
            content=normalized_content,
            images=images,
            ugc_right=ugc_right,
            target_uins=target_uins,
        )

    async def delete_qzone_msg(self, tid: str) -> QzoneResponse:
        """删除当前登录 QQ 发布的指定说说。"""
        return await self._backend().delete_qzone_msg(self._validate_tid(tid))

    async def like_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> QzoneResponse:
        """为指定说说点赞。"""
        normalized_target = (
            self._validate_user_id(target_uin, "target_uin")
            if target_uin is not None
            else None
        )
        return await self._backend().like_qzone(
            self._validate_tid(tid),
            normalized_target,
        )

    async def unlike_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> QzoneResponse:
        """取消对指定说说的点赞。"""
        normalized_target = (
            self._validate_user_id(target_uin, "target_uin")
            if target_uin is not None
            else None
        )
        return await self._backend().unlike_qzone(
            self._validate_tid(tid),
            normalized_target,
        )

    async def comment_qzone(
        self,
        tid: str,
        content: str,
        target_uin: int | None = None,
        images: list[str] | None = None,
    ) -> QzoneResponse:
        """对指定说说发表评论，可附带图片。"""
        normalized_images = self._normalize_images(images)
        normalized_content = str(content).strip()
        if not normalized_content:
            if not normalized_images:
                raise NeoFoxzoneError("评论正文与图片不能同时为空。")
            raise NeoFoxzoneError("当前 OneBot 后端要求评论正文不能为空。")
        normalized_target = (
            self._validate_user_id(target_uin, "target_uin")
            if target_uin is not None
            else None
        )
        return await self._backend().comment_qzone(
            tid=self._validate_tid(tid),
            content=normalized_content,
            target_uin=normalized_target,
            images=normalized_images,
        )

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
    ) -> QzoneResponse:
        """在详情确认的顶层评论下发送一条真正的楼中楼回复。"""
        normalized_content = str(content).strip()
        if not normalized_content:
            raise NeoFoxzoneError("楼中楼回复正文不能为空。")
        normalized_root_comment_id = str(root_comment_id).strip()
        if not normalized_root_comment_id:
            raise NeoFoxzoneError("楼中楼回复缺少顶层评论 ID。")
        normalized_name = str(target_name).strip()
        if not normalized_name:
            raise NeoFoxzoneError("楼中楼回复缺少被回复者昵称。")
        normalized_self_uin = (
            self._validate_user_id(self_uin, "self_uin")
            if self_uin is not None
            else None
        )
        return await self._backend().reply_qzone_comment(
            tid=self._validate_tid(tid),
            host_uin=self._validate_user_id(host_uin, "host_uin"),
            root_comment_id=normalized_root_comment_id,
            target_uin=self._validate_user_id(target_uin, "target_uin"),
            target_name=normalized_name,
            content=normalized_content,
            self_uin=normalized_self_uin,
        )

    async def publish_feed(
        self,
        content: str,
        images: list[bytes] | None = None,
    ) -> bool:
        """按原版契约发布说说，并在成功后记录发布历史。"""
        image_references = (
            [f"base64://{base64.b64encode(image).decode('ascii')}" for image in images]
            if images
            else None
        )
        try:
            async with self._runtime.reply_send_lock:
                response = await self.send_qzone_msg(
                    content=content,
                    images=image_references,
                )
        except (NeoFoxzoneError, ValueError, TypeError):
            return False
        if not self.response_succeeded(response):
            return False
        await self._runtime.send_history.record(str(content).strip())
        return True

    async def list_feeds(
        self,
        target_qq: str,
        num: int = 5,
        skip_commented: bool = True,
        paginate_comments: bool = True,
    ) -> list[dict[str, Any]]:
        """按原版契约读取任意 QQ 的说说及完整可见评论树。"""
        del paginate_comments
        normalized_target = str(target_qq).strip()
        if not normalized_target.isdigit() or int(normalized_target) <= 0:
            return []
        try:
            response = await self.get_qzone_user_feeds(
                host_uin=int(normalized_target),
                pos=0,
                num=max(1, int(num)),
            )
        except (NeoFoxzoneError, ValueError, TypeError):
            return []
        if not self.response_succeeded(response):
            return []
        raw_feeds = self._response_data(response).get("msglist")
        if not isinstance(raw_feeds, list):
            return []
        feeds: list[dict[str, Any]] = []
        for raw_feed in raw_feeds:
            if not isinstance(raw_feed, dict):
                continue
            feed = self._legacy_feed(raw_feed)
            if not feed["tid"]:
                continue
            feed["target_qq"] = normalized_target
            feed["uin"] = normalized_target
            if skip_commented and self._runtime.interaction_log.has_commented(
                normalized_target,
                feed["tid"],
            ):
                continue
            feeds.append(feed)
        return feeds

    async def list_own_feeds_with_comments(
        self,
        num: int = 5,
    ) -> list[dict[str, Any]]:
        """读取当前 Bot 的说说；账号可确认时使用完整详情兼容层。"""
        self_uin = await self._load_self_uin()
        if self_uin is not None:
            return await self.list_feeds(
                target_qq=str(self_uin),
                num=num,
                skip_commented=False,
            )
        try:
            response = await self.get_qzone_msg_list(pos=0, num=max(1, int(num)))
        except (NeoFoxzoneError, ValueError, TypeError):
            return []
        if not self.response_succeeded(response):
            return []
        raw_feeds = self._response_data(response).get("msglist")
        return [
            self._legacy_feed(feed)
            for feed in raw_feeds if isinstance(raw_feeds, list) and isinstance(feed, dict)
        ]

    async def get_feed_detail(
        self,
        host_qq: str,
        feed_id: str,
    ) -> dict[str, Any] | None:
        """按原版契约读取一条说说及其完整评论树。"""
        normalized_host = str(host_qq).strip()
        normalized_feed_id = str(feed_id).strip()
        if not normalized_host.isdigit() or not normalized_feed_id:
            return None
        try:
            response = await self.get_qzone_msg_detail(
                tid=normalized_feed_id,
                host_uin=int(normalized_host),
            )
        except (NeoFoxzoneError, ValueError, TypeError):
            return None
        if not self.response_succeeded(response):
            return None
        detail = self._response_data(response)
        if not detail:
            return None
        normalized = self._legacy_feed(detail)
        normalized["tid"] = normalized["tid"] or normalized_feed_id
        normalized["target_qq"] = normalized_host
        normalized["uin"] = normalized_host
        return normalized

    async def get_feed_comments(
        self,
        host_qq: str,
        feed_id: str,
    ) -> list[dict[str, Any]]:
        """按原版契约返回指定说说的平铺评论与楼中楼评论。"""
        detail = await self.get_feed_detail(host_qq, feed_id)
        return list(detail.get("comments", [])) if detail else []

    async def get_monitor_feeds(self, num: int = 10) -> list[dict[str, Any]]:
        """读取结构化好友动态，不从预渲染 HTML 猜测评论关系。"""
        try:
            response = await self.get_qzone_feeds(page_num=1, count=max(1, int(num)))
        except (NeoFoxzoneError, ValueError, TypeError):
            return []
        if not self.response_succeeded(response):
            return []
        raw_feeds = self._response_data(response).get("feeds")
        if not isinstance(raw_feeds, list):
            return []
        feeds: list[dict[str, Any]] = []
        for raw_feed in raw_feeds:
            if not isinstance(raw_feed, dict):
                continue
            feed = self._legacy_feed(raw_feed)
            if not feed["tid"] or not feed["target_qq"]:
                continue
            self._runtime.interaction_log.sync_like_state(
                feed["target_qq"],
                feed["tid"],
                feed["liked"],
            )
            if not self._runtime.interaction_log.has_seen(
                feed["target_qq"],
                feed["tid"],
            ):
                feeds.append(feed)
        await self._runtime.interaction_log.save()
        return feeds

    async def comment(self, target_qq: str, feed_id: str, text: str) -> bool:
        """按原版契约评论指定说说。"""
        normalized_target = str(target_qq).strip()
        if not normalized_target.isdigit() or not str(text).strip():
            return False
        try:
            async with self._runtime.reply_send_lock:
                response = await self.comment_qzone(
                    tid=feed_id,
                    content=text,
                    target_uin=int(normalized_target),
                )
        except (NeoFoxzoneError, ValueError, TypeError):
            return False
        return self.response_succeeded(response)

    async def like(self, target_qq: str, feed_id: str) -> bool:
        """按原版契约点赞指定说说。"""
        normalized_target = str(target_qq).strip()
        if not normalized_target.isdigit():
            return False
        try:
            async with self._runtime.reply_send_lock:
                response = await self.like_qzone(
                    tid=feed_id,
                    target_uin=int(normalized_target),
                )
        except (NeoFoxzoneError, ValueError, TypeError):
            return False
        return self.response_succeeded(response)

    async def reply_comment(
        self,
        feed_id: str,
        host_qq: str,
        target_name: str,
        reply_text: str,
        comment_tid: str,
        commenter_qq: str = "",
    ) -> bool:
        """按原版契约发送已验证顶层评论下的楼中楼回复。"""
        normalized_host = str(host_qq).strip()
        normalized_commenter = str(commenter_qq).strip()
        if not normalized_host.isdigit() or not normalized_commenter.isdigit():
            return False
        try:
            async with self._runtime.reply_send_lock:
                response = await self.reply_qzone_comment(
                    tid=feed_id,
                    host_uin=int(normalized_host),
                    root_comment_id=comment_tid,
                    target_uin=int(normalized_commenter),
                    target_name=target_name,
                    content=reply_text,
                )
        except NeoFoxzoneError:
            return False
        return self.response_succeeded(response)

    async def has_replied_comment(self, feed_id: str, comment_tid: str) -> bool:
        """查询插件级已回复评论状态。"""
        return self._runtime.reply_tracker.has_replied(feed_id, comment_tid)

    async def mark_comment_replied(self, feed_id: str, comment_tid: str) -> None:
        """持久化已回复评论状态。"""
        await self._runtime.reply_tracker.mark_as_replied(feed_id, comment_tid)

    def has_interacted(self, target_qq: str, feed_id: str) -> bool:
        """查询插件级互动状态。"""
        return self._runtime.interaction_log.has_interacted(target_qq, feed_id)

    async def mark_interaction(
        self,
        target_qq: str,
        feed_id: str,
        action: str,
        source: str = "agent",
    ) -> None:
        """记录并保存一次原版互动状态。"""
        self._runtime.interaction_log.mark(target_qq, feed_id, action, source)
        await self._runtime.interaction_log.save()

    async def mark_followup_checked(self, target_qq: str, feed_id: str) -> None:
        """记录并保存外部空间回查时间。"""
        self._runtime.interaction_log.mark_followup_checked(target_qq, feed_id)
        await self._runtime.interaction_log.save()

    async def iter_followup_feeds(
        self,
        exclude_qq: str = "",
        limit: int = 0,
        max_feed_age_hours: float = 0.0,
        only_target_qq: str = "",
    ) -> list[tuple[str, str]]:
        """返回按最久未回查排序的已评论外部说说。"""
        return self._runtime.interaction_log.iter_followup_feeds(
            exclude_target_qq=exclude_qq,
            limit=limit,
            max_feed_age_hours=max_feed_age_hours,
            only_target_qq=only_target_qq,
        )

    async def self_qq(self) -> str:
        """返回当前登录 QQ 号，无法确认时返回空字符串。"""
        uin = await self._load_self_uin()
        return str(uin) if uin else ""

    async def generate_topic_content(
        self,
        topic: str = "",
    ) -> dict[str, Any]:
        """按主题生成说说正文；LLM 不可用时退回主题本身。

        Args:
            topic: 运营者提供的主题；为空时由 LLM 自行选择。

        Returns:
            原版契约形状 ``{"success": bool, "message": str}``。
        """
        normalized_topic = str(topic).strip()
        try:
            generated = await ContentService(self._config()).generate_story(
                normalized_topic
            )
        except Exception:
            return {"success": True, "message": normalized_topic or "（无主题）"}
        text = str(generated or "").strip()
        if not text:
            return {"success": True, "message": normalized_topic or "（无主题）"}
        return {"success": True, "message": text}

    async def set_qzone_ban(
        self,
        user_id: int,
        enable: bool = True,
    ) -> QzoneResponse:
        """将用户加入或移出当前 QQ 空间黑名单。"""
        return await self._backend().set_qzone_ban(
            user_id=self._validate_user_id(user_id, "user_id"),
            enable=bool(enable),
        )

    async def set_qzone_msg_right(
        self,
        tid: str,
        ugc_right: int,
        target_uins: list[int] | None = None,
    ) -> QzoneResponse:
        """修改已发布说说的查看权限。"""
        normalized_right, normalized_targets = self._validate_right(
            ugc_right,
            target_uins,
        )
        return await self._backend().set_qzone_msg_right(
            tid=self._validate_tid(tid),
            ugc_right=normalized_right,
            target_uins=normalized_targets,
        )


__all__ = [
    "NeoFoxzoneError",
    "NeoFoxzoneService",
    "QzoneResponse",
    "VALID_UGC_RIGHTS",
]