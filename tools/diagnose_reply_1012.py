"""QZone 楼中楼回复 1012 反爬问题真实链路诊断脚本。

用途：
    复现 `neo_foxzone` 自动回复失败（QZone 请求失败 subcode=1012）的问题，
    并对同一目标评论逐一对比多种传输方案的效果，定位真正的差异因子。

安全边界：
    1. 只读取自己的最新说说与评论树，只对**自己的评论**发送真实回复
       （回复目标是 Bot 自己，不会骚扰真实用户）。
    2. 每种方案最多发一条回复，全部结束后删除测试评论。
    3. Cookie 只在进程内存中使用，不落盘、不打日志。

用法（在 neo-mofox 根目录）：
    uv run python plugins/neo-foxzone/tools/diagnose_reply_1012.py [filter ...]

    filter 是可选的传输方案名称过滤（如 `urllib aiohttp`）。
"""

from __future__ import annotations

import asyncio
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any

try:
    import aiohttp
except ImportError:  # 理论上不会发生，主项目已依赖 aiohttp
    aiohttp = None  # type: ignore[assignment]

sys.path.insert(0, ".")

from plugins.onebot_expand.qzone_compat import (  # noqa: E402
    QzoneCompatibilityClient,
    build_qzone_comment_reply_request,
    calculate_qzone_gtk,
    parse_qzone_cookie_string,
)

NAPCAT_HTTP = "http://127.0.0.1:3000"
BOT_UIN = 3_693_525_299
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class TransportResult:
    """一次传输方案测试的观测结果。"""

    name: str
    http_ok: bool
    preview: str
    code: Any = None
    subcode: Any = None
    message: str = ""


async def napcat(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用 SnowLuma HTTP API。"""
    import json as _json

    body = _json.dumps(params or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{NAPCAT_HTTP}/{action}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return _json.loads(response.read().decode("utf-8"))


def build_reply_request(
    cookies: dict[str, str],
    gtk: str,
    tid: str,
    root_comment_id: str,
) -> Any:
    """构造对测试评论的楼中楼回复请求（回复目标为 Bot 自己）。"""
    import time as _time

    unique_content = f"传输层诊断测试 {_time.strftime('%H:%M:%S')}，请忽略"
    return build_qzone_comment_reply_request(
        self_uin=BOT_UIN,
        host_uin=BOT_UIN,
        tid=tid,
        root_comment_id=root_comment_id,
        target_uin=BOT_UIN,
        target_name="Navinatte",
        content=unique_content,
        gtk=gtk,
    )


async def root_comment_of_latest_post(
    client: QzoneCompatibilityClient,
) -> tuple[str, str, str] | None:
    """找到最新说说中 Bot 自己发布的顶层评论（没有则现场发一条）。

    返回 ``(tid, root_comment_id, test_comment_created)``。
    """
    feeds = await client.get_user_feeds(
        self_uin=BOT_UIN,
        host_uin=BOT_UIN,
        pos=0,
        num=3,
        paginate_comments=False,
    )
    for feed in feeds:
        tid = str(feed.get("tid") or "").strip()
        if not tid:
            continue
        detail = await client.get_msg_detail(BOT_UIN, tid)
        for comment in detail.get("commentlist") or []:
            if int(comment.get("uin") or 0) == BOT_UIN:
                root = str(comment.get("comment_id") or "").strip()
                if root:
                    return tid, root, ""
        # 该说说评论区可用：发一条 Bot 评论作为测试目标
        response = await napcat(
            "comment_qzone",
            {"tid": tid, "content": "诊断脚本测试评论，稍后删除"},
        )
        if str(response.get("status", "")).lower() == "ok":
            comment_id = str(
                (response.get("data") or {}).get("comment_id")
                or (response.get("data") or {}).get("commentid")
                or ""
            )
            if comment_id:
                return tid, comment_id, "created"
            return tid, "", "created-no-id"
    return None


def parse_outcome(raw: str) -> tuple[Any, Any, str]:
    """从 QZone 响应提取 (code, subcode, message)。"""
    from plugins.onebot_expand.qzone_compat import parse_qzone_json

    try:
        payload = parse_qzone_json(raw)
    except Exception as error:  # noqa: BLE001
        return None, None, f"parse-error: {error}"
    return (
        payload.get("code"),
        payload.get("subcode"),
        str(payload.get("message") or payload.get("msg") or ""),
    )


async def transport_urllib(
    request: Any,
    cookie_header: str,
) -> str:
    """方案 A：现状 —— urllib + Accept-Encoding: identity。"""
    data = request.body.encode("utf-8") if request.method == "POST" else None
    raw = urllib.request.Request(
        request.url,
        data=data,
        headers={
            "User-Agent": UA,
            "Accept-Encoding": "identity",
            "Cookie": cookie_header,
            **request.headers,
        },
        method=request.method,
    )
    with urllib.request.urlopen(raw, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


async def make_aiohttp_transport(compression: str, connection: str):
    """构造 aiohttp 传输方案。

    compression: ``identity`` / ``gzip`` / ``default``（不显式声明）。
    connection: ``close`` / ``keep-alive``。
    cookie_mode: ``header``（显式 Cookie 头）/ ``session``（会话 Cookie，
        与原版 FoxZone 一致）。
    """
    if aiohttp is None:
        return None

    async def transport(request: Any, cookie_header: str) -> str:
        headers = {
            "User-Agent": UA,
            **request.headers,
        }
        if compression == "identity":
            headers["Accept-Encoding"] = "identity"
        elif compression == "gzip":
            headers["Accept-Encoding"] = "gzip, deflate, br"
        elif compression == "default":
            headers.pop("Accept-Encoding", None)
        if connection == "close":
            headers["Connection"] = "close"
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(
            cookies=parse_qzone_cookie_string(cookie_header),
        ) as session:
            async with session.request(
                request.method,
                request.url,
                data=request.body.encode("utf-8") if request.method == "POST" else None,
                headers=headers,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                text = await response.text()
                return text.lstrip("\ufeff")

    return transport


async def main() -> int:
    """执行诊断主流程。"""
    filters = [item for item in sys.argv[1:] if not item.startswith("-")]

    cookie_response = await napcat("get_cookies", {"domain": "qzone.qq.com"})
    cookie_string = str((cookie_response.get("data") or {}).get("cookies") or "")
    cookies = parse_qzone_cookie_string(cookie_string)
    gtk = calculate_qzone_gtk(cookies.get("p_skey", ""))

    client = QzoneCompatibilityClient(cookie_string)
    prepared = await root_comment_of_latest_post(client)
    if prepared is None:
        print("未找到可用的测试说说与评论，退出。")
        return 1
    tid, root_comment_id, created = prepared
    print(f"测试目标: tid={tid} root_comment_id={root_comment_id} ({created or 'existing'})")
    if not root_comment_id:
        print("测试评论未返回 comment id，退出。")
        return 1

    transports: list[tuple[str, Any]] = [
        ("urllib-identity", transport_urllib),
    ]
    for name, compression, connection in (
        ("aiohttp-identity-close", "identity", "close"),
        ("aiohttp-gzip-keepalive", "gzip", "keep-alive"),
        ("aiohttp-default", "default", "keep-alive"),
    ):
        transport = await make_aiohttp_transport(compression, connection)
        if transport is not None:
            transports.append((name, transport))

    results: list[TransportResult] = []
    for name, transport in transports:
        if filters and name not in filters:
            continue
        request = build_reply_request(cookies, gtk, tid, root_comment_id)
        try:
            raw = await transport(request, cookie_string)
            code, subcode, message = parse_outcome(raw)
            results.append(
                TransportResult(
                    name=name,
                    http_ok=True,
                    preview=" ".join(raw.split())[:110],
                    code=code,
                    subcode=subcode,
                    message=message,
                )
            )
        except Exception as error:  # noqa: BLE001
            results.append(
                TransportResult(
                    name=name,
                    http_ok=False,
                    preview=f"exception: {error}",
                )
            )
        await asyncio.sleep(3)

    print("\n===== 诊断结果 =====")
    for result in results:
        print(
            f"[{result.name}] http_ok={result.http_ok} "
            f"code={result.code} subcode={result.subcode} msg={result.message!r}\n"
            f"  preview: {result.preview}"
        )

    # 清理：删除测试评论（若为本脚本创建）
    if created.startswith("created"):
        delete = await napcat("delete_qzone_comment", {"tid": tid, "comment_id": root_comment_id})
        print(f"清理测试评论: status={delete.get('status')} msg={delete.get('msg')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
