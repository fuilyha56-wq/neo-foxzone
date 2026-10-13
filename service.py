"""基于 OneBot Expand 的 QQ 空间统一 Service。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import re
import socket
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

import aiohttp
from src.app.plugin_system.base import BaseService
from src.kernel.logger import get_logger

from .config import NeoFoxzoneConfig
from .core.llm.content_service import ContentService
from .core.llm.vision import VisionService, image_references
from .image_provider import (
    ImageProviderError,
    generate_images,
    normalize_image_references,
)
from .message_segments import UnsupportedMessageSegment, render_qzone_segments
from .qzone_client import (
    QZoneClientError,
    QZoneDirectClient,
    QZoneRateLimitError,
    fetch_qzone_cookie_string,
    invalidate_qzone_cookie_cache,
)
from .providers import discover_qzone_provider, get_current_login_info

QzoneResponse = dict[str, Any]
VALID_UGC_RIGHTS = frozenset({1, 4, 16, 64, 128})
logger = get_logger("neo_foxzone.service")
_WRITE_RATE_LOCK = asyncio.Lock()
_LAST_WRITE_STARTED = 0.0


class _PublicImageResolver(aiohttp.abc.AbstractResolver):
    """拒绝解析到非公网地址的图片主机，防止协议端代取内网 URL。"""

    def __init__(self) -> None:
        self._resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_UNSPEC,
    ) -> list[dict[str, Any]]:
        records = await self._resolver.resolve(host, port, family)
        if not records:
            raise OSError("图片主机没有公网 DNS 地址。")
        for record in records:
            try:
                address = ipaddress.ip_address(record["host"])
            except (KeyError, ValueError) as error:
                raise OSError("图片主机 DNS 响应无法确认。") from error
            if not address.is_global:
                raise OSError("图片主机解析到了非公网地址。")
        return records

    async def close(self) -> None:
        await self._resolver.close()


class NeoFoxzoneError(RuntimeError):
    """Neo FoxZone 无法执行调用时抛出的业务异常。"""


class NeoFoxzoneService(BaseService):
    """经运行时发现的协议端暴露 QQ 空间说说能力。"""

    service_name = "qzone_service"
    service_description = "自动发现协议端的 QQ 空间说说服务"
    name = "qzone_service"
    description = "自动发现协议端的 QQ 空间说说服务"
    version = "0.1.6"
    # QZone 后端是运行时可选能力；缺失时 Service 仍注册并返回清晰诊断。
    dependencies: list[str] = []

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

    def _backend(self) -> Any:
        """获取当前可用的 QZone Service 或在线 QQ Adapter。"""
        if not self._config().plugin.enabled:
            raise NeoFoxzoneError("Neo FoxZone 当前已在配置中禁用。")

        snapshot = discover_qzone_provider()
        if snapshot.provider is None:
            raise NeoFoxzoneError(
                "当前协议端不可用：" + snapshot.diagnostic
            )
        return snapshot.provider

    @staticmethod
    def _mask_qq(qq: str | int | None) -> str:
        """在日志中遮蔽 QQ 号。"""
        value = str(qq or "").strip()
        if len(value) < 7:
            return "未知"
        return f"{value[:4]}****{value[-4:]}"

    @staticmethod
    def _mask_identifier(value: str | int | None) -> str:
        """遮蔽说说和评论标识。"""
        normalized = str(value or "").strip()
        if len(normalized) < 5:
            return "******"
        return f"{normalized[:2]}***{normalized[-2:]}"

    def _log_write_context(
        self,
        operation: str,
        current_qq: int,
        *,
        target_author_qq: int | None = None,
        tid: str | None = None,
        comment_author_qq: int | None = None,
        root_comment_id: str | None = None,
    ) -> None:
        """记录脱敏后的写操作校验上下文。"""
        logger.info(
            "真实写操作预检通过: "
            f"operation={operation}, current={self._mask_qq(current_qq)}, "
            f"post_author={self._mask_qq(target_author_qq)}, "
            f"tid={self._mask_identifier(tid)}, "
            f"comment_author={self._mask_qq(comment_author_qq)}, "
            f"root_comment_id={self._mask_identifier(root_comment_id)}"
        )

    async def _require_write_identity(self, operation: str) -> int:
        """每次真实写操作都使用当前接口确认账号并比对安全配置。"""
        expected = str(self._config().security.write_account_qq).strip()
        login = await get_current_login_info(expected_qq=expected)
        if login.get("status") != "confirmed":
            reason = str(login.get("message") or "当前登录账号无法确认。")
            logger.warning(
                "已阻止真实写操作: "
                f"operation={operation}, current={self._mask_qq(login.get('qq'))}, "
                f"expected={self._mask_qq(expected)}, "
                "reason=当前账号无法确认或与安全配置不匹配"
            )
            raise NeoFoxzoneError(f"已阻止真实写操作：{reason}")
        try:
            return int(str(login["qq"]))
        except (KeyError, TypeError, ValueError) as error:
            raise NeoFoxzoneError("已阻止真实写操作：当前登录 QQ 无法确认。") from error

    async def _respect_write_rate_limit(self) -> None:
        """在所有手动写操作之间施加共享的最小间隔。"""
        global _LAST_WRITE_STARTED
        interval = max(
            0.0,
            float(self._config().limits.write_min_interval_seconds),
        )
        if interval == 0:
            return
        async with _WRITE_RATE_LOCK:
            now = time.monotonic()
            delay = interval - (now - _LAST_WRITE_STARTED)
            if delay > 0:
                await asyncio.sleep(delay)
            _LAST_WRITE_STARTED = time.monotonic()

    async def get_verified_write_account(self) -> int:
        """供后台自动任务使用；未通过账号校验时抛出异常并跳过任务。"""
        return await self._require_write_identity("automatic task")

    @staticmethod
    def _post_owner(detail: dict[str, Any]) -> int | None:
        """只从说说详情中显式的作者字段读取 QQ，不使用请求目标兜底。"""
        for key in ("uin", "owner_uin", "user_id", "owner_qq", "author_qq"):
            value = detail.get(key)
            try:
                owner = int(value)
            except (TypeError, ValueError):
                continue
            if owner > 0:
                return owner
        return None

    async def _verified_post_detail(self, tid: str, owner_uin: int) -> dict[str, Any]:
        """读取详情并确认 tid 与作者；缺字段或关系不明时拒绝写操作。"""
        response = await self.get_qzone_msg_detail(tid=tid, host_uin=owner_uin)
        if not self.response_succeeded(response):
            raise NeoFoxzoneError(
                "无法确认目标说说详情，已阻止写操作：" + self.response_error(response)
            )
        detail = self._response_data(response)
        actual_tid = str(detail.get("tid") or detail.get("id") or "").strip()
        actual_owner = self._post_owner(detail)
        if actual_tid != tid:
            raise NeoFoxzoneError("详情中的 tid 与目标不一致，已阻止写操作。")
        if actual_owner is None:
            raise NeoFoxzoneError("详情未显式返回说说作者 QQ，已阻止写操作。")
        if actual_owner != owner_uin:
            raise NeoFoxzoneError("详情作者与目标 QQ 不一致，已阻止写操作。")
        return detail

    async def _verify_own_post(self, tid: str, current_qq: int) -> dict[str, Any]:
        """确认说说属于当前账号。"""
        detail = await self._verified_post_detail(tid, current_qq)
        if self._post_owner(detail) != current_qq:
            raise NeoFoxzoneError("目标说说不属于当前登录账号，已阻止写操作。")
        return detail

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

    async def _normalize_images(self, images: list[str] | None) -> list[str] | None:
        """清理图片引用并限制数量。"""
        try:
            normalized = normalize_image_references(images)
        except ImageProviderError as error:
            raise NeoFoxzoneError(str(error)) from error
        if normalized is None:
            return None
        normalized = [
            await self._normalize_image_reference(image) for image in normalized
        ]
        maximum = max(0, int(self._config().limits.max_images))
        if len(normalized) > maximum:
            raise NeoFoxzoneError(f"图片数量不能超过 {maximum} 张。")
        return normalized

    async def _normalize_image_reference(self, image: str) -> str:
        """验证图片引用并转成限长 Base64，避免协议端代取不可信 URL。"""
        self._validate_image_reference(image)
        maximum_bytes = max(1, int(self._config().limits.max_image_bytes))
        if image.startswith(("http://", "https://")):
            return await self._download_remote_image(image, maximum_bytes)
        if image.startswith("file://"):
            parsed = urlsplit(image)
            local_path = unquote(parsed.path)
            if re.match(r"^/[A-Za-z]:/", local_path):
                local_path = local_path[1:]
            try:
                path = Path(local_path).resolve(strict=True)
                if not path.is_file():
                    raise NeoFoxzoneError("file:// 图片必须指向本地普通文件。")
                image_bytes = path.read_bytes()
            except (OSError, RuntimeError, ValueError) as error:
                raise NeoFoxzoneError("无法读取 file:// 图片文件。") from error
            if len(image_bytes) > maximum_bytes:
                raise NeoFoxzoneError(
                    f"单张图片不能超过 {maximum_bytes} 字节。"
                )
            if not self._looks_like_image(image_bytes):
                raise NeoFoxzoneError("本地文件内容不是支持的 PNG、JPEG、GIF、WebP 或 BMP 图片。")
            return "base64://" + base64.b64encode(image_bytes).decode("ascii")

        if image.startswith(("base64://", "data:")):
            encoded = image.split(",", 1)[1] if image.startswith("data:") else image[9:]
            try:
                image_bytes = base64.b64decode("".join(encoded.split()), validate=True)
            except (ValueError, binascii.Error) as error:
                raise NeoFoxzoneError("Base64 图片内容无效。") from error
            if len(image_bytes) > maximum_bytes:
                raise NeoFoxzoneError(f"单张图片不能超过 {maximum_bytes} 字节。")
            if not self._looks_like_image(image_bytes):
                raise NeoFoxzoneError("Base64 内容不是支持的 PNG、JPEG、GIF、WebP 或 BMP 图片。")
            return "base64://" + base64.b64encode(image_bytes).decode("ascii")
        return image

    async def _download_remote_image(self, url: str, maximum_bytes: int) -> str:
        """仅从 DNS 确认为公网的主机读取限长图片；不跟随重定向。"""
        resolver = _PublicImageResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        timeout = aiohttp.ClientTimeout(total=15.0, connect=5.0)
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,
            ) as session:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        raise NeoFoxzoneError(
                            f"外部图片服务器返回 HTTP {response.status}。"
                        )
                    if not response.content_type.lower().startswith("image/"):
                        raise NeoFoxzoneError("外部 URL 返回的内容不是图片。")
                    if (
                        response.content_length is not None
                        and response.content_length > maximum_bytes
                    ):
                        raise NeoFoxzoneError(
                            f"单张图片不能超过 {maximum_bytes} 字节。"
                        )
                    image_bytes = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        image_bytes.extend(chunk)
                        if len(image_bytes) > maximum_bytes:
                            raise NeoFoxzoneError(
                                f"单张图片不能超过 {maximum_bytes} 字节。"
                            )
        except NeoFoxzoneError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as error:
            raise NeoFoxzoneError("无法安全获取外部图片。") from error
        if not self._looks_like_image(bytes(image_bytes)):
            raise NeoFoxzoneError(
                "外部 URL 返回的内容不是支持的 PNG、JPEG、GIF、WebP 或 BMP 图片。"
            )
        return "base64://" + base64.b64encode(image_bytes).decode("ascii")

    @staticmethod
    def _looks_like_image(image_bytes: bytes) -> bool:
        """只接受常见栅格图片签名，拒绝伪装成图片的任意文件。"""
        return (
            image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            or image_bytes.startswith((b"GIF87a", b"GIF89a"))
            or image_bytes.startswith(b"\xff\xd8\xff")
            or (
                len(image_bytes) >= 12
                and image_bytes.startswith(b"RIFF")
                and image_bytes[8:12] == b"WEBP"
            )
            or image_bytes.startswith(b"BM")
        )

    @staticmethod
    def _validate_image_reference(image: str) -> None:
        """拒绝本机/内网 HTTP 地址及非本地 file URL 主机。"""
        if image.startswith(("base64://", "data:")):
            return
        try:
            parsed = urlsplit(image)
            port = parsed.port
        except ValueError as error:
            raise NeoFoxzoneError("图片 URL 格式无效。") from error
        if parsed.scheme == "file":
            if parsed.netloc not in {"", "localhost"}:
                raise NeoFoxzoneError("file:// 图片只能指向本地文件，不能使用网络共享地址。")
            return
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise NeoFoxzoneError("图片引用必须是 HTTP(S)、file:// 或 Base64 格式。")
        expected_port = 443 if parsed.scheme == "https" else 80
        if parsed.username or parsed.password or port not in {None, expected_port}:
            raise NeoFoxzoneError("图片 URL 不允许账号信息或非标准 HTTP(S) 端口。")
        hostname = parsed.hostname.rstrip(".").lower()
        if (
            hostname == "localhost"
            or hostname.endswith((".localhost", ".local", ".internal"))
            or hostname in {"metadata.google.internal", "metadata.azure.internal"}
        ):
            raise NeoFoxzoneError("图片 URL 不能指向本机、内网或云元数据服务。")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise NeoFoxzoneError("图片 URL 不能指向本机、内网或保留 IP 地址。")

    def _normalize_content(self, content: str, label: str) -> str:
        """清理控制字符、HTML 标签边界和 CQ action 标记。"""
        normalized = str(content).replace("\x00", "").strip()
        normalized = re.sub(r"(?i)\[CQ:", "［CQ:", normalized)
        normalized = normalized.replace("<", "&lt;").replace(">", "&gt;")
        maximum = max(1, int(self._config().limits.max_content_chars))
        if len(normalized) > maximum:
            raise NeoFoxzoneError(f"{label}不能超过 {maximum} 个字符。")
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

    async def get_capability_status(self) -> dict[str, Any]:
        """返回当前发现状态和真实登录账号校验状态，不执行写操作。"""
        snapshot = discover_qzone_provider(refresh=True)
        expected = str(self._config().security.write_account_qq).strip()
        login = await get_current_login_info(expected_qq=expected)
        return {
            "provider_available": snapshot.provider is not None,
            "provider": snapshot.source,
            "diagnostic": snapshot.diagnostic,
            "service_signatures": list(snapshot.service_signatures),
            "adapter_signatures": list(snapshot.adapter_signatures),
            "account_status": login.get("status", "unknown"),
            "account_qq": self._mask_qq(login.get("qq")),
            "expected_account_qq": self._mask_qq(expected),
            "write_allowed": (
                login.get("status") == "confirmed"
                and snapshot.provider is not None
            ),
            "unsupported_capabilities": [
                "资料昵称与个性签名修改：当前已检查的 QZone Service 和 action 契约未提供此接口",
                "黑名单查询与逐条屏蔽：当前适配器契约未提供可确认接口",
                "说说权限读取：当前适配器契约未提供可确认接口",
                "点赞状态查询、视频/媒体归一化、转发引用字段：当前兼容层未验证",
                "协议专属 Face ID：当前跨协议契约未验证，不会猜测映射",
            ],
        }

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
            timestamp = comment.get("create_time") or comment.get("created_time") or comment.get("time")
            if timestamp is not None:
                normalized["created_time"] = timestamp
            if image_references(comment):
                normalized["images"] = image_references(comment)
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
            "images": image_references(feed),
            "comments": normalized_comments,
            "commentlist": [
                comment for comment in comments if isinstance(comment, dict)
            ],
            "comment_count": len(normalized_comments),
            "liked": bool(feed.get("liked")),
        }

    async def _load_self_uin(self) -> int | None:
        """从账号 Service 读取当前 Bot QQ，无法确认时返回 ``None``。"""
        login = await get_current_login_info()
        if login.get("status") != "confirmed":
            return None
        try:
            return int(str(login["qq"]))
        except (KeyError, TypeError, ValueError):
            return None

    async def _with_direct_client(self, operation, *, expected_uin: int | None = None):
        """在本地 QZone 直连客户端上执行操作，Cookie 失效时重试一次。

        直连客户端按原版 FoxZone 2.0.2 的浏览器级请求实现
        （``user.qzone.qq.com`` 域 Cookie + aiohttp 会话传输），
        规避协议端兼容层触发 QZone 反爬（subcode=1012）的问题。
        """
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                cookie_string = await fetch_qzone_cookie_string(expected_qq=expected_uin)
            except QZoneClientError as error:
                raise NeoFoxzoneError(str(error)) from error
            client = QZoneDirectClient.create(cookie_string)
            try:
                return await operation(client)
            except QZoneClientError as error:
                last_error = error
                if "-3000" in str(error) and attempt == 0:
                    invalidate_qzone_cookie_cache()
                    continue
                raise NeoFoxzoneError(str(error)) from error
        raise NeoFoxzoneError(str(last_error or "QZone 直连请求失败。"))

    @staticmethod
    def _direct_failure(error: Exception) -> QzoneResponse:
        """把本地直连异常收敛为标准 OneBot 失败响应。"""
        message = str(error) or "QZone 直连请求失败。"
        return {
            "status": "failed",
            "retcode": -1,
            "data": None,
            "msg": message,
            "wording": message,
        }

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
        """获取单条说说详情及其可验证的完整评论树。

        使用本地直连客户端（原版 FoxZone 浏览器级请求）读取
        ``msgdetail_v6``，不再依赖协议端兼容层。
        """

        async def _operation(client: QZoneDirectClient) -> dict[str, Any]:
            return await client.get_msg_detail(
                self._validate_user_id(host_uin, "host_uin"),
                self._validate_tid(tid),
            )

        try:
            detail = await self._with_direct_client(_operation)
        except (NeoFoxzoneError, QZoneRateLimitError) as error:
            return self._direct_failure(error)
        except (TypeError, ValueError) as error:
            return self._direct_failure(error)
        return {"status": "ok", "retcode": 0, "data": detail}

    async def get_qzone_user_feeds(
        self,
        *,
        host_uin: int,
        pos: int = 0,
        num: int = 5,
        self_uin: int | None = None,
    ) -> QzoneResponse:
        """经本地直连客户端读取指定 QQ 可见的说说列表。"""
        self._validate_query(pos, num)
        normalized_self_uin = (
            self._validate_user_id(self_uin, "self_uin")
            if self_uin is not None
            else None
        )
        del normalized_self_uin  # 直连客户端从 Cookie 自身识别 uin

        async def _operation(client: QZoneDirectClient) -> dict[str, Any]:
            return {
                "msglist": await client.get_user_feeds(
                    host_uin=self._validate_user_id(host_uin, "host_uin"),
                    pos=pos,
                    num=num,
                )
            }

        try:
            data = await self._with_direct_client(_operation)
        except (NeoFoxzoneError, QZoneRateLimitError) as error:
            return self._direct_failure(error)
        except (TypeError, ValueError) as error:
            return self._direct_failure(error)
        return {"status": "ok", "retcode": 0, "data": data}

    async def send_qzone_msg(
        self,
        content: str,
        images: list[str] | None = None,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> QzoneResponse:
        """发表说说，可附带图片并在发布时设置查看权限。"""
        current_qq = await self._require_write_identity("publish")
        normalized_images = await self._normalize_images(images)
        normalized_content = self._normalize_content(content, "说说正文")
        if not normalized_content:
            if not normalized_images:
                raise NeoFoxzoneError("说说正文与图片不能同时为空。")
            raise NeoFoxzoneError("当前 OneBot 后端要求说说正文不能为空。")
        normalized_right, normalized_targets = self._validate_right(
            ugc_right,
            target_uins,
        )
        self._log_write_context(
            "publish",
            current_qq,
            target_author_qq=current_qq,
            tid="new",
        )
        await self._respect_write_rate_limit()
        return await self._backend().send_qzone_msg(
            content=normalized_content,
            images=normalized_images,
            ugc_right=normalized_right,
            target_uins=normalized_targets,
        )

    async def send_qzone_segments(
        self,
        segments: Iterable[Any],
        *,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> QzoneResponse:
        """将结构化正文/图片段转换为 QZone 正文和图片字段。"""
        try:
            content, images = render_qzone_segments(segments)
        except UnsupportedMessageSegment as error:
            raise NeoFoxzoneError(f"消息段无法安全发送：{error}") from error
        return await self.send_qzone_msg(
            content=content,
            images=images or None,
            ugc_right=ugc_right,
            target_uins=target_uins,
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
        normalized_content = self._normalize_content(content, "AI 配图说说正文")
        if not normalized_content:
            raise NeoFoxzoneError("AI 配图说说正文不能为空。")
        await self._require_write_identity("publish generated")
        normalized_description = self._normalize_content(
            image_description,
            "图片描述",
        )
        if not normalized_description or len(normalized_description) > 400:
            raise NeoFoxzoneError("图片描述不能为空且不能超过 400 个字符。")
        try:
            images = await generate_images(
                self._config(),
                normalized_description,
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

    async def delete_qzone_msg(
        self,
        tid: str,
        *,
        expected_author_qq: int,
        confirmation: str,
    ) -> QzoneResponse:
        """删除当前账号自己的说说；必须显式重复确认账号和 tid。"""
        normalized_tid = self._validate_tid(tid)
        current_qq = await self._require_write_identity("delete")
        normalized_author = self._validate_user_id(
            expected_author_qq,
            "expected_author_qq",
        )
        expected_confirmation = f"DELETE {normalized_tid} {normalized_author} {current_qq}"
        if normalized_author != current_qq or str(confirmation).strip() != expected_confirmation:
            logger.warning(
                "已阻止真实写操作: "
                f"operation=delete, current={self._mask_qq(current_qq)}, "
                f"target={self._mask_qq(normalized_author)}, tid=******, "
                "reason=confirmation mismatch"
            )
            raise NeoFoxzoneError(
                "删除确认不匹配。请先读取当前账号和作者，再输入 "
                f"{expected_confirmation!r}。"
            )
        await self._verify_own_post(normalized_tid, current_qq)
        self._log_write_context(
            "delete",
            current_qq,
            target_author_qq=normalized_author,
            tid=normalized_tid,
        )
        await self._respect_write_rate_limit()
        return await self._backend().delete_qzone_msg(normalized_tid)

    async def like_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> QzoneResponse:
        """为指定说说点赞。"""
        current_qq = await self._require_write_identity("like")
        normalized_tid = self._validate_tid(tid)
        normalized_target = self._validate_user_id(
            target_uin if target_uin is not None else current_qq,
            "target_uin",
        )
        await self._verified_post_detail(normalized_tid, normalized_target)
        self._log_write_context(
            "like",
            current_qq,
            target_author_qq=normalized_target,
            tid=normalized_tid,
        )
        await self._respect_write_rate_limit()
        return await self._backend().like_qzone(
            normalized_tid,
            normalized_target,
        )

    async def unlike_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> QzoneResponse:
        """取消对指定说说的点赞。"""
        current_qq = await self._require_write_identity("unlike")
        normalized_tid = self._validate_tid(tid)
        normalized_target = self._validate_user_id(
            target_uin if target_uin is not None else current_qq,
            "target_uin",
        )
        await self._verified_post_detail(normalized_tid, normalized_target)
        self._log_write_context(
            "unlike",
            current_qq,
            target_author_qq=normalized_target,
            tid=normalized_tid,
        )
        await self._respect_write_rate_limit()
        return await self._backend().unlike_qzone(
            normalized_tid,
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
        current_qq = await self._require_write_identity("comment")
        normalized_images = await self._normalize_images(images)
        normalized_content = self._normalize_content(content, "评论正文")
        if not normalized_content:
            if not normalized_images:
                raise NeoFoxzoneError("评论正文与图片不能同时为空。")
            raise NeoFoxzoneError("当前 OneBot 后端要求评论正文不能为空。")
        normalized_tid = self._validate_tid(tid)
        normalized_target = self._validate_user_id(
            target_uin if target_uin is not None else current_qq,
            "target_uin",
        )
        await self._verified_post_detail(normalized_tid, normalized_target)
        self._log_write_context(
            "comment",
            current_qq,
            target_author_qq=normalized_target,
            tid=normalized_tid,
        )
        await self._respect_write_rate_limit()
        return await self._backend().comment_qzone(
            tid=normalized_tid,
            content=normalized_content,
            target_uin=normalized_target,
            images=normalized_images,
        )

    async def comment_qzone_segments(
        self,
        *,
        tid: str,
        segments: Iterable[Any],
        target_uin: int | None = None,
    ) -> QzoneResponse:
        """使用文本、Unicode Emoji 和图片段发表评论。"""
        try:
            content, images = render_qzone_segments(segments)
        except UnsupportedMessageSegment as error:
            raise NeoFoxzoneError(f"评论消息段无法安全发送：{error}") from error
        return await self.comment_qzone(
            tid=tid,
            content=content,
            target_uin=target_uin,
            images=images or None,
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
        current_qq = await self._require_write_identity("reply")
        normalized_content = self._normalize_content(content, "楼中楼回复")
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
        del normalized_self_uin  # 直连客户端从 Cookie 自身识别操作者 uin

        normalized_tid = self._validate_tid(tid)
        normalized_host = self._validate_user_id(host_uin, "host_uin")
        normalized_target = self._validate_user_id(target_uin, "target_uin")
        detail = await self._verified_post_detail(normalized_tid, normalized_host)
        comments = detail.get("commentlist")
        if not isinstance(comments, list):
            raise NeoFoxzoneError("说说详情没有结构化顶层评论，已阻止回复。")
        matched_root: dict[str, Any] | None = None
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            comment_id = str(comment.get("comment_id") or "").strip()
            if comment_id == normalized_root_comment_id:
                matched_root = comment
                break
        if matched_root is None:
            raise NeoFoxzoneError("目标 ID 不是详情中的顶层评论 ID，已阻止回复。")
        thread_authors: set[int] = set()

        def collect_authors(comment: dict[str, Any]) -> None:
            for key in ("uin", "user_id", "author_qq"):
                try:
                    author_qq = int(comment.get(key))
                except (TypeError, ValueError):
                    continue
                if author_qq > 0:
                    thread_authors.add(author_qq)
                    break
            children = comment.get("list_3")
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        collect_authors(child)

        collect_authors(matched_root)
        if normalized_target not in thread_authors:
            raise NeoFoxzoneError("无法在目标评论线程中确认被回复 QQ，已阻止回复。")
        self._log_write_context(
            "reply",
            current_qq,
            target_author_qq=normalized_host,
            tid=normalized_tid,
            comment_author_qq=normalized_target,
            root_comment_id=normalized_root_comment_id,
        )
        await self._respect_write_rate_limit()

        async def _operation(client: QZoneDirectClient) -> dict[str, Any]:
            return await client.reply_comment(
                host_uin=normalized_host,
                tid=normalized_tid,
                root_comment_id=normalized_root_comment_id,
                target_uin=normalized_target,
                target_name=normalized_name,
                content=normalized_content,
            )

        try:
            data = await self._with_direct_client(_operation, expected_uin=current_qq)
        except (NeoFoxzoneError, QZoneRateLimitError) as error:
            return self._direct_failure(error)
        except (TypeError, ValueError) as error:
            return self._direct_failure(error)
        return {"status": "ok", "retcode": 0, "data": data}

    async def publish_feed(
        self,
        content: str,
        images: list[bytes] | None = None,
        *,
        ugc_right: int = 1,
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
                    ugc_right=ugc_right,
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
        except (NeoFoxzoneError, ValueError, TypeError) as error:
            await self._record_background_error(error)
            return None
        if not self.response_succeeded(response):
            await self._record_background_error(self.response_error(response))
            return None
        detail = self._response_data(response)
        if not detail:
            return None
        normalized = self._legacy_feed(detail)
        if normalized["tid"] != normalized_feed_id or normalized["uin"] != normalized_host:
            return None
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
        detail_attempts = 0
        for raw_feed in raw_feeds:
            if self._runtime.polling_state.rate_limit_cooldown_active():
                break
            if not isinstance(raw_feed, dict):
                continue
            if str(raw_feed.get("appid") or "311") != "311":
                continue
            feed = self._legacy_feed(raw_feed)
            if not feed["tid"] or not feed["target_qq"]:
                continue
            # SnowLuma timeline 的 html 只是摘要，ID 与作者来自明确字段。
            # 通过详情接口补全正文、图片和评论树，不从 HTML 猜测关系。
            if raw_feed.get("html") and not raw_feed.get("content"):
                if detail_attempts >= self._config().monitor.max_decisions_per_cycle:
                    break
                if detail_attempts:
                    await asyncio.sleep(1.0)
                detail_attempts += 1
                detail = await self.get_feed_detail(feed["target_qq"], feed["tid"])
                if detail is None:
                    continue
                detail["liked"] = feed["liked"]
                feed = detail
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
        except (NeoFoxzoneError, ValueError, TypeError) as error:
            await self._record_background_error(error)
            return False
        if not self.response_succeeded(response):
            await self._record_background_error(self.response_error(response))
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
        except (NeoFoxzoneError, ValueError, TypeError) as error:
            await self._record_background_error(error)
            return False
        if not self.response_succeeded(response):
            await self._record_background_error(self.response_error(response))
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
        except NeoFoxzoneError as error:
            await self._record_background_error(error)
            return False
        if not self.response_succeeded(response):
            await self._record_background_error(self.response_error(response))
        return self.response_succeeded(response)

    async def _record_background_error(self, error: Exception | str) -> None:
        """自治封装返回布尔结果时，仍保留协议限流的共享冷却。"""
        if re.search(r"(?:subcode|code)[=(]\s*(?:1012|-10049)\b", str(error), re.I):
            self._runtime.polling_state.record_rate_limit_cooldown(
                time.time() + self._config().polling.rate_limit_retry_minutes * 60)
            await self._runtime.polling_state.save()

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

    async def describe_images(self, images: list[str]) -> dict[str, str]:
        """理解已验证图片，失败明确传递给调用方。"""
        return await VisionService(self._config(), self._runtime.vision_cache,
                                   self._normalize_image_reference).describe_images(images)

    async def enrich_feed_context(self, feed: dict[str, Any]) -> dict[str, Any]:
        """在文本决策前加入图片描述，或为视觉模型准备安全附件。"""
        context = dict(feed)
        refs = image_references(feed)[:self._config().llm.vision_max_images]
        context["images"] = refs
        if refs and self._config().llm.multimodal_mode:
            context["_image_contents"] = [await self._normalize_image_reference(ref) for ref in refs]
        elif refs and self._config().llm.vision_model_task.strip():
            descriptions = await self.describe_images(refs)
            context["image_descriptions"] = list(descriptions.values())
        return context

    async def generate_topic_content(
        self,
        topic: str = "",
    ) -> dict[str, Any]:
        """按主题生成说说正文；LLM 失败时明确取消发布。

        Args:
            topic: 运营者提供的主题；为空时由 LLM 自行选择。

        Returns:
            原版契约形状 ``{"success": bool, "message": str}``。
        """
        normalized_topic = str(topic).strip()
        try:
            generated = await ContentService(self._config()).generate_story(
                normalized_topic,
                recent_posts=await ContentService(self._config()).get_recent_self_feeds_block(
                    self._runtime.send_history.recent()),
            )
        except Exception as error:
            return {"success": False, "message": f"LLM 生成失败：{error}"}
        text = str(generated or "").strip()
        if not text:
            return {"success": False, "message": "LLM 未返回说说正文，已取消发布。"}
        return {"success": True, "message": text}

    async def generate_topic_decision(self, topic: str = "") -> dict[str, Any]:
        """生成正文以及经 JSON 校验的可选配图决策。"""
        normalized_topic = str(topic).strip()[:400]
        try:
            decision = await ContentService(self._config()).generate_story_decision(
                normalized_topic
            )
        except Exception as error:
            raise NeoFoxzoneError(f"LLM 配图决策失败，已取消发布：{error}") from error
        content = self._normalize_content(
            str(decision.get("content") or ""),
            "LLM 说说正文",
        )
        generate_image = decision.get("generate_image") is True
        image_description = str(decision.get("image_description") or "").strip()[:400]
        if not content:
            generate_image = False
        if not image_description:
            generate_image = False
        image_style = decision.get("image_style")
        if image_style not in {"photo", "drawing"}:
            image_style = self._config().image.default_style
        return {
            "content": content,
            "generate_image": generate_image,
            "image_description": image_description if generate_image else "",
            "image_style": image_style,
        }

    async def set_qzone_ban(
        self,
        user_id: int,
        enable: bool = True,
    ) -> QzoneResponse:
        """将用户加入或移出当前 QQ 空间黑名单。"""
        current_qq = await self._require_write_identity("blacklist")
        normalized_user_id = self._validate_user_id(user_id, "user_id")
        if normalized_user_id == current_qq:
            raise NeoFoxzoneError("不能将当前登录账号加入自己的空间黑名单。")
        self._log_write_context(
            "blacklist_add" if enable else "blacklist_remove",
            current_qq,
            comment_author_qq=normalized_user_id,
        )
        await self._respect_write_rate_limit()
        return await self._backend().set_qzone_ban(
            user_id=normalized_user_id,
            enable=bool(enable),
        )

    async def set_qzone_msg_right(
        self,
        tid: str,
        ugc_right: int,
        target_uins: list[int] | None = None,
    ) -> QzoneResponse:
        """修改已发布说说的查看权限。"""
        current_qq = await self._require_write_identity("visibility")
        normalized_tid = self._validate_tid(tid)
        await self._verify_own_post(normalized_tid, current_qq)
        normalized_right, normalized_targets = self._validate_right(
            ugc_right,
            target_uins,
        )
        self._log_write_context(
            "visibility",
            current_qq,
            target_author_qq=current_qq,
            tid=normalized_tid,
        )
        await self._respect_write_rate_limit()
        return await self._backend().set_qzone_msg_right(
            tid=normalized_tid,
            ugc_right=normalized_right,
            target_uins=normalized_targets,
        )


__all__ = [
    "NeoFoxzoneError",
    "NeoFoxzoneService",
    "QzoneResponse",
    "VALID_UGC_RIGHTS",
]
