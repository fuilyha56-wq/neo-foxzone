"""QZone 直连 HTTP 客户端（移植自原版 FoxZone 2.0.2 已验证实现）。

背景：协议端 SnowLuma 的公开摘要 action 会裁剪评论树，其返回的
``get_cookies`` 域名（``qzone.qq.com``）与传输特征也和浏览器会话不一致，
导致楼中楼回复持续触发 QZone 反爬（subcode=1012 / code=-10049）。
本模块按原版 FoxZone 的浏览器级请求实现：

- Cookie 经 ``onebot_adapter`` 适配器透传 ``get_cookies``，域名固定为
  ``user.qzone.qq.com``（与浏览器访问空间时一致）；
- 全部请求使用 aiohttp 会话 Cookie（与浏览器 Cookie jar 行为一致），
  而非 ``urllib`` 的手工 ``Cookie`` 头；
- 楼中楼回复表单字段与浏览器 DevTools 抓包逐字段对齐（详见原版
  ``QZONE_API.md`` §3.5），任何字段偏差都会触发 -10049 伪装限流。

本模块不落盘、不记录 Cookie；实例为短生命周期，由调用方按需创建。
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from src.app.plugin_system.api.adapter_api import send_adapter_command
from src.kernel.logger import get_logger

__all__ = [
    "QZONE_REPLY_URL",
    "QZoneClientError",
    "QZoneDirectClient",
    "QZoneRateLimitError",
    "build_comment_reply_form",
    "build_msg_detail_params",
    "build_user_feeds_params",
    "calculate_gtk",
    "normalize_msg_detail",
    "normalize_user_feeds",
    "parse_cookie_string",
    "parse_qzone_payload",
]

logger = get_logger("neo_foxzone.qzone_client")

#: 单条说说详情（msgdetail_v6，含 list_3 楼中楼完整评论树）。
QZONE_DETAIL_URL = (
    "https://h5.qzone.qq.com/proxy/domain/taotao.qq.com/"
    "cgi-bin/emotion_cgi_msgdetail_v6"
)
#: 任意 QQ 可见说说列表（msglist_v6）。
QZONE_USER_FEEDS_URL = (
    "https://user.qzone.qq.com/proxy/domain/taotao.qq.com/"
    "cgi-bin/emotion_cgi_msglist_v6"
)
#: 评论与楼中楼回复共用端点（emotion_cgi_re_feeds）。
QZONE_REPLY_URL = (
    "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/"
    "cgi-bin/emotion_cgi_re_feeds"
)

#: 与浏览器一致的 Cookie 请求域名（原版 FoxZone 固定值）。
QZONE_COOKIE_DOMAIN = "user.qzone.qq.com"

#: OneBot 适配器签名（与 onebot_expand.api_defs 一致）。
ADAPTER_SIGNATURE = "onebot_adapter:adapter:onebot_adapter"

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

#: 请求超时（秒）。
REQUEST_TIMEOUT_SECONDS = 20.0


class QZoneClientError(RuntimeError):
    """QZone 直连请求无法安全完成时抛出。"""


class QZoneRateLimitError(QZoneClientError):
    """QZone 反爬限流（code=-10049 / subcode=1012），重试亦无效。"""


def parse_cookie_string(cookie_string: str) -> dict[str, str]:
    """把适配器返回的 Cookie 字符串解析为键值字典。"""
    cookies: dict[str, str] = {}
    for segment in str(cookie_string or "").split(";"):
        key, separator, value = segment.strip().partition("=")
        if separator and key and value:
            cookies[key] = value
    return cookies


def calculate_gtk(p_skey: str) -> str:
    """按 QZone 规则从 ``p_skey`` 计算 ``g_tk``。"""
    if not p_skey:
        raise QZoneClientError("QZone Cookie 缺少 p_skey。")
    value = 5381
    for character in p_skey:
        value += (value << 5) + ord(character)
    return str(value & 0x7FFFFFFF)


def _as_int(value: Any) -> int:
    """把协议中的数字或数字字符串安全转换为整数。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_text(value: Any) -> str:
    """把协议字段收敛为去除首尾空白的字符串。"""
    return str(value).strip() if value is not None else ""


def _first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """返回字段别名中的第一个非空值。"""
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    """从未知值中提取字典列表。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_comment(
    comment: dict[str, Any],
    parent_comment_id: str | None = None,
) -> dict[str, Any]:
    """归一化一条 QZone 评论及其楼中楼子评论。

    子评论的 ``parent_comment_id`` 即所属顶层一级评论的 tid，
    可直接作为楼中楼回复接口的 ``commentId``（原版实证结论）。
    """
    comment_id = _as_text(
        _first_value(comment, ("tid", "commentid", "comment_id", "commentId"))
    )
    normalized: dict[str, Any] = {
        "comment_id": comment_id,
        "uin": _as_int(_first_value(comment, ("uin", "user_id", "userId"))),
        "nickname": _as_text(_first_value(comment, ("name", "nickname", "nick"))),
        "content": _as_text(_first_value(comment, ("content", "text", "comment"))),
        "list_3": [],
    }
    if parent_comment_id:
        normalized["parent_comment_id"] = parent_comment_id
    normalized["list_3"] = [
        _normalize_comment(child, comment_id or parent_comment_id)
        for child in _dict_list(
            _first_value(comment, ("list_3", "reply_list", "sub_comments"))
        )
    ]
    return normalized


def _extract_detail_record(payload: dict[str, Any]) -> dict[str, Any]:
    """从根对象、data 包装或 msglist 包装中抽取单条说说详情。"""
    data = payload.get("data")
    container = data if isinstance(data, dict) else payload
    msglist = _dict_list(container.get("msglist"))
    if msglist:
        return msglist[0]
    return container


def _normalize_record(
    record: dict[str, Any],
    *,
    fallback_uin: int = 0,
) -> dict[str, Any]:
    """归一化单条 QZone 说说及其结构化评论树。"""
    tid = _as_text(_first_value(record, ("tid", "id", "key")))
    if not tid:
        raise QZoneClientError("QZone 说说响应缺少 tid。")

    images: list[str] = []
    for picture in _dict_list(_first_value(record, ("pic", "pictotal"))):
        image_url = _as_text(
            _first_value(picture, ("url3", "url2", "url1", "smallurl"))
        )
        if image_url:
            images.append(image_url)

    comments = [
        _normalize_comment(comment)
        for comment in _dict_list(
            _first_value(record, ("commentlist", "comment_list", "comments"))
        )
    ]
    return {
        "tid": tid,
        "uin": _as_int(_first_value(record, ("uin", "user_id", "owner_uin")))
        or fallback_uin,
        "content": _as_text(_first_value(record, ("content", "text", "summary"))),
        "created_time": _as_int(
            _first_value(record, ("created_time", "time", "abstime"))
        ),
        "comment_num": _as_int(
            _first_value(
                record,
                ("commentnum", "cmtnum", "comment_num", "comment_count"),
            )
        ),
        "images": images,
        "commentlist": comments,
    }


def normalize_msg_detail(payload: dict[str, Any]) -> dict[str, Any]:
    """校验并归一化 ``msgdetail_v6`` 响应为完整评论树详情。"""
    record = _extract_detail_record(payload)
    normalized = _normalize_record(record)
    if normalized["uin"] <= 0:
        normalized["uin"] = _as_int(payload.get("owner_uin"))
    return normalized


def normalize_user_feeds(
    payload: dict[str, Any],
    *,
    host_uin: int,
) -> list[dict[str, Any]]:
    """校验并归一化 ``msglist_v6`` 响应为说说列表。"""
    if host_uin <= 0:
        raise QZoneClientError("QZone 说说列表请求缺少有效目标 QQ。")
    data = payload.get("data")
    container = data if isinstance(data, dict) else payload
    feeds: list[dict[str, Any]] = []
    for record in _dict_list(container.get("msglist")):
        try:
            feeds.append(_normalize_record(record, fallback_uin=host_uin))
        except QZoneClientError:
            continue
    return feeds


def _balanced_objects(text: str) -> list[str]:
    """提取文本中的平衡 JSON 对象候选（跳过字符串字面量内部）。"""
    candidates: list[str] = []
    in_string = False
    escaped = False
    depth = 0
    start = -1

    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            continue
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if character != "}" or depth == 0:
            continue
        depth -= 1
        if depth == 0 and start >= 0:
            candidates.append(text[start : index + 1])
            start = -1
    return candidates


def _frame_callback_objects(text: str) -> list[str]:
    """提取 ``frameElement.callback({...})`` 中的对象文本。"""
    candidates: list[str] = []
    marker = re.compile(r"frameElement\.callback\s*\(")
    for match in marker.finditer(text):
        brace = text.find("{", match.end())
        if brace < 0:
            continue
        nested = _balanced_objects(text[brace:])
        if nested:
            candidates.append(nested[0])
    return candidates


def parse_qzone_payload(text: str) -> dict[str, Any]:
    """解析 QZone 的纯 JSON / JSONP / frame 桥接 HTML 响应。

    兼容 ``undefined`` 等非法 JSON 值；无法解析出对象时抛出
    :class:`QZoneClientError`。
    """
    normalized_text = str(text or "").lstrip("\ufeff").strip()
    if not normalized_text:
        raise QZoneClientError("QZone 响应为空。")

    candidates = _frame_callback_objects(normalized_text)
    candidates.extend(_balanced_objects(normalized_text))

    import orjson

    for candidate in candidates:
        sanitized = re.sub(r"\bundefined\b", "null", candidate)
        try:
            payload = orjson.loads(sanitized)
        except orjson.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    # JSONP 外壳 ``_Callback({...})``
    stripped = normalized_text
    for prefix in ("_Callback(", "callback("):
        if stripped.startswith(prefix) and stripped.endswith(")"):
            inner = stripped[len(prefix) : -1]
            try:
                payload = orjson.loads(
                    re.sub(r"\bundefined\b", "null", inner)
                )
                if isinstance(payload, dict):
                    return payload
            except orjson.JSONDecodeError:
                break

    preview = " ".join(normalized_text.split())[:160]
    raise QZoneClientError(f"QZone 响应 JSON 解析失败（响应摘要={preview!r}）。")


def _raise_for_code(payload: dict[str, Any]) -> None:
    """按 QZone CGI 状态码抛出对应异常（不暴露 Cookie）。"""
    subcode = _as_int(payload.get("subcode"))
    code = _as_int(payload.get("code"))
    if subcode == 0 and code == 0:
        return
    message = _as_text(
        _first_value(payload, ("message", "msg", "wording"))
    )
    if code == -10049 or subcode in (1012, -10049):
        raise QZoneRateLimitError(
            f"QZone 请求失败（subcode={subcode or code}）: {message or '使用人数过多'}"
        )
    raise QZoneClientError(
        f"QZone 请求失败（subcode={subcode or code}）{f': {message}' if message else ''}"
    )


def build_msg_detail_params(host_uin: int, tid: str, gtk: str) -> dict[str, str]:
    """构造 ``msgdetail_v6`` 查询参数（仅 4 个必传字段，多了会被拒）。"""
    return {
        "uin": str(host_uin),
        "tid": _as_text(tid),
        "format": "jsonp",
        "g_tk": gtk,
    }


def build_user_feeds_params(
    *,
    host_uin: int,
    pos: int,
    num: int,
    gtk: str,
) -> dict[str, str]:
    """构造 ``msglist_v6`` 查询参数。"""
    return {
        "g_tk": gtk,
        "uin": str(host_uin),
        "ftype": "0",
        "sort": "0",
        "pos": str(pos),
        "num": str(num),
        "replynum": "999",
        "code_version": "1",
        "format": "json",
        "need_comment": "1",
    }


def build_comment_reply_form(
    *,
    self_uin: int,
    host_uin: int,
    tid: str,
    root_comment_id: str,
    target_uin: int,
    target_name: str,
    content: str,
) -> dict[str, str]:
    """构造楼中楼回复表单（字段与浏览器抓包逐一对齐）。

    关键语义（原版 ``QZONE_API.md`` §3.5 实证）：
    - ``commentId`` 是顶层一级评论 tid；
    - ``commentUin`` 是操作者 uin（Bot 自己），不是评论作者；
    - ``content`` 必须带 ``@{uin:...,nick:...,auto:1}`` 提及前缀。
    """
    normalized_content = _as_text(content)
    if not normalized_content:
        raise QZoneClientError("楼中楼回复正文不能为空。")
    mention = f"@{{uin:{target_uin},nick:{_as_text(target_name)},auto:1}}"
    return {
        "topicId": f"{host_uin}_{_as_text(tid)}__1",
        "feedsType": "100",
        "inCharset": "utf-8",
        "outCharset": "utf-8",
        "plat": "qzone",
        "source": "ic",
        "hostUin": str(host_uin),
        "isSignIn": "",
        "platformid": "52",
        "uin": str(self_uin),
        "format": "fs",
        "ref": "feeds",
        "content": f"{mention} {normalized_content}",
        "commentId": _as_text(root_comment_id),
        "commentUin": str(self_uin),
        "richval": "",
        "richtype": "",
        "private": "0",
        "paramstr": "1",
        "qzreferrer": f"https://user.qzone.qq.com/{self_uin}",
    }


@dataclass(slots=True)
class QZoneDirectClient:
    """基于浏览器级请求特征的 QZone 直连客户端。

    与原版 FoxZone 2.0.2 的 :class:`QZoneAPIClient` 同源：
    aiohttp 会话 Cookie + Chrome UA + 正确的 Referer/Origin。
    """

    cookies: dict[str, str]
    gtk: str
    self_uin: str

    @classmethod
    def create(cls, cookie_string: str) -> "QZoneDirectClient":
        """从适配器返回的 Cookie 字符串构建客户端。"""
        cookies = parse_cookie_string(cookie_string)
        p_skey = cookies.get("p_skey") or cookies.get("P_SKEY", "")
        if not p_skey:
            raise QZoneClientError("QZone Cookie 缺少 p_skey。")
        uin = _as_text(cookies.get("uin")).lstrip("o")
        if not uin:
            raise QZoneClientError("QZone Cookie 缺少 uin。")
        return cls(cookies=cookies, gtk=calculate_gtk(p_skey), self_uin=uin)

    def _base_headers(self) -> dict[str, str]:
        """与浏览器一致的通用请求头。"""
        return {
            "User-Agent": CHROME_UA,
            "Referer": f"https://user.qzone.qq.com/{self.self_uin}",
            "Origin": "https://user.qzone.qq.com",
            "Connection": "keep-alive",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """发送请求并返回响应文本（会话 Cookie，浏览器级行为）。"""
        final_headers = self._base_headers()
        if headers:
            final_headers.update(headers)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(cookies=self.cookies) as session:
            async with session.request(
                method,
                url,
                params=params,
                data=data,
                headers=final_headers,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                text = await response.text()
                if text.startswith("\ufeff"):
                    text = text.lstrip("\ufeff")
                return text

    async def get_msg_detail(self, host_uin: int, tid: str) -> dict[str, Any]:
        """读取一条说说详情并返回完整评论树。"""
        payload = parse_qzone_payload(
            await self._request(
                "GET",
                QZONE_DETAIL_URL,
                params=build_msg_detail_params(host_uin, tid, self.gtk),
                headers={
                    "Referer": (
                        "https://h5.qzone.qq.com/mqzone/index?_proxy=1"
                        f"&hostuin={host_uin}"
                    ),
                },
            )
        )
        _raise_for_code(payload)
        detail = normalize_msg_detail(payload)
        if detail["uin"] <= 0:
            detail["uin"] = host_uin
        return detail

    async def get_user_feeds(
        self,
        *,
        host_uin: int,
        pos: int = 0,
        num: int = 5,
    ) -> list[dict[str, Any]]:
        """读取指定 QQ 可见的说说列表。"""
        payload = parse_qzone_payload(
            await self._request(
                "GET",
                QZONE_USER_FEEDS_URL,
                params=build_user_feeds_params(
                    host_uin=host_uin,
                    pos=pos,
                    num=num,
                    gtk=self.gtk,
                ),
            )
        )
        _raise_for_code(payload)
        return normalize_user_feeds(payload, host_uin=host_uin)

    async def reply_comment(
        self,
        *,
        host_uin: int,
        tid: str,
        root_comment_id: str,
        target_uin: int,
        target_name: str,
        content: str,
    ) -> dict[str, Any]:
        """发送楼中楼回复；限流时抛 :class:`QZoneRateLimitError`。"""
        form = build_comment_reply_form(
            self_uin=int(self.self_uin),
            host_uin=host_uin,
            tid=tid,
            root_comment_id=root_comment_id,
            target_uin=target_uin,
            target_name=target_name,
            content=content,
        )
        payload = parse_qzone_payload(
            await self._request(
                "POST",
                QZONE_REPLY_URL,
                params={"g_tk": self.gtk},
                data=form,
                headers={
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Content-Type": (
                        "application/x-www-form-urlencoded;charset=UTF-8"
                    ),
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-CH-UA": (
                        '"Chromium";v="138", "Not(A:Brand";v="99", '
                        '"Google Chrome";v="138"'
                    ),
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"Windows"',
                },
            )
        )
        _raise_for_code(payload)
        return payload


#: Cookie 获取的并发去重锁（模块级，Service 每次构造新实例）。
_COOKIE_FETCH_LOCK = asyncio.Lock()
#: 类级共享 Cookie 缓存 ``(cookie 字符串, 到期时间戳)``。
_SHARED_COOKIE_CACHE: tuple[str, float] | None = None
_COOKIE_CACHE_TTL_SECONDS = 300.0


async def fetch_qzone_cookie_string() -> str:
    """经 onebot_adapter 透传 ``get_cookies`` 获取 QZone Cookie。

    使用 ``user.qzone.qq.com`` 域名（与浏览器一致）；带 TTL 共享缓存
    与并发去重，避免一轮轮询内重复触发协议端风控。
    """
    global _SHARED_COOKIE_CACHE
    async with _COOKIE_FETCH_LOCK:
        now = time.monotonic()
        if _SHARED_COOKIE_CACHE is not None:
            cookie_string, expires_at = _SHARED_COOKIE_CACHE
            if now < expires_at:
                return cookie_string
        response = await send_adapter_command(
            adapter_sign=ADAPTER_SIGNATURE,
            command_name="get_cookies",
            command_data={"domain": QZONE_COOKIE_DOMAIN},
            timeout=15.0,
        )
        if str(response.get("status", "")).lower() != "ok":
            message = str(
                response.get("msg")
                or response.get("wording")
                or "协议端未返回 QZone Cookie。"
            )
            raise QZoneClientError(message)
        data = response.get("data")
        cookies = data.get("cookies") if isinstance(data, dict) else None
        if not isinstance(cookies, str) or not cookies.strip():
            raise QZoneClientError("协议端返回的 QZone Cookie 为空。")
        _SHARED_COOKIE_CACHE = (cookies, now + _COOKIE_CACHE_TTL_SECONDS)
        return cookies


def invalidate_qzone_cookie_cache() -> None:
    """清除共享 Cookie 缓存（Cookie 失效时调用）。"""
    global _SHARED_COOKIE_CACHE
    _SHARED_COOKIE_CACHE = None
