"""基于 OneBot Expand 的 QQ 空间统一 Service。"""

from __future__ import annotations

from typing import Any, cast

from src.app.plugin_system.api import service_api
from src.app.plugin_system.base import BaseService

from . import BACKEND_SERVICE_SIGNATURE, SERVICE_NAME
from .config import NeoFoxzoneConfig
from .contracts import OneBotQzoneService

QzoneResponse = dict[str, Any]
VALID_UGC_RIGHTS = frozenset({1, 4, 16, 64, 128})


class NeoFoxzoneError(RuntimeError):
    """Neo FoxZone 无法执行调用时抛出的业务异常。"""


class NeoFoxzoneService(BaseService):
    """通过 OneBot Expand 暴露全部 QQ 空间说说能力。"""

    service_name = "neo_foxzone_service"
    service_description = "基于 OneBot Expand 的 QQ 空间说说全功能服务"
    name = SERVICE_NAME
    description = "基于 OneBot Expand 的 QQ 空间说说全功能服务"
    version = "1.0.0"
    dependencies = [BACKEND_SERVICE_SIGNATURE]

    def _config(self) -> NeoFoxzoneConfig:
        """返回当前插件配置，测试或异常装配时使用默认值。"""
        config = self.plugin.config
        if isinstance(config, NeoFoxzoneConfig):
            return config
        return NeoFoxzoneConfig()

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

    def _validate_query(self, offset: int, count: int) -> None:
        """校验分页参数。"""
        if offset < 0:
            raise NeoFoxzoneError("分页位置或页码不能小于 0。")
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
        page_num: int = 0,
        count: int = 10,
    ) -> QzoneResponse:
        """获取当前登录 QQ 的好友动态。"""
        self._validate_query(page_num, count)
        return await self._backend().get_qzone_feeds(
            page_num=page_num,
            count=count,
        )

    async def send_qzone_msg(
        self,
        content: str,
        images: list[str] | None = None,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> QzoneResponse:
        """发表文字或图片说说，并可在发布时设置查看权限。"""
        normalized_images = self._normalize_images(images)
        if not str(content).strip() and not normalized_images:
            raise NeoFoxzoneError("说说正文与图片不能同时为空。")
        normalized_right, normalized_targets = self._validate_right(
            ugc_right,
            target_uins,
        )
        return await self._backend().send_qzone_msg(
            content=content,
            images=normalized_images,
            ugc_right=normalized_right,
            target_uins=normalized_targets,
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
        if not str(content).strip() and not normalized_images:
            raise NeoFoxzoneError("评论正文与图片不能同时为空。")
        normalized_target = (
            self._validate_user_id(target_uin, "target_uin")
            if target_uin is not None
            else None
        )
        return await self._backend().comment_qzone(
            tid=self._validate_tid(tid),
            content=content,
            target_uin=normalized_target,
            images=normalized_images,
        )

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