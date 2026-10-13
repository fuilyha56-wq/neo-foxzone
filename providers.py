"""动态发现 QQ 空间协议能力，不在导入时依赖可选插件。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from src.app.plugin_system.api import adapter_api, service_api

from . import ACCOUNT_SERVICE_SIGNATURE, BACKEND_SERVICE_SIGNATURE

QZONE_ACTIONS = {
    "get_qzone_msg_list": ("get_qzone_msg_list", ("pos", "num")),
    "get_qzone_feeds": ("get_qzone_feeds", ("page_num", "count")),
    "send_qzone_msg": (
        "send_qzone_msg",
        ("content", "images", "ugc_right", "target_uins"),
    ),
    "delete_qzone_msg": ("delete_qzone_msg", ("tid",)),
    "like_qzone": ("like_qzone", ("tid", "target_uin")),
    "unlike_qzone": ("unlike_qzone", ("tid", "target_uin")),
    "comment_qzone": (
        "comment_qzone",
        ("tid", "content", "target_uin", "images"),
    ),
    "set_qzone_ban": ("set_qzone_ban", ("user_id", "enable")),
    "set_qzone_msg_right": (
        "set_qzone_msg_right",
        ("tid", "ugc_right", "target_uins"),
    ),
}

PROVIDER_CACHE_SECONDS = 10.0
ADAPTER_ACTION_TIMEOUT_SECONDS = 15.0
LOGIN_ACTION_TIMEOUT_SECONDS = 8.0


def response_succeeded(response: Any) -> bool:
    """兼容 OneBot status/retcode 和常见 service 响应。"""
    if not isinstance(response, dict):
        return False
    status = response.get("status")
    if status is not None:
        return str(status).lower() == "ok"
    return response.get("retcode") == 0


def response_login_qq(response: Any) -> str | None:
    """只从当前登录接口的结构化字段读取账号。"""
    if not response_succeeded(response):
        return None
    payload = response.get("data")
    if not isinstance(payload, dict):
        payload = response
    for key in ("user_id", "self_id", "self_uin", "bot_uin", "uin"):
        raw = payload.get(key)
        if raw is None or not str(raw).strip().isdigit():
            continue
        normalized = str(raw).strip()
        if int(normalized) > 0:
            return normalized
    return None


def _failed_response(message: str, *, code: int = -404) -> dict[str, Any]:
    return {
        "status": "failed",
        "retcode": code,
        "data": None,
        "msg": message,
        "wording": message,
    }


class AdapterQzoneProvider:
    """通过核心 Adapter API 调用标准 OneBot/NapCat QZone action。"""

    def __init__(self, adapter_signature: str) -> None:
        self.adapter_signature = adapter_signature
        self.provider_name = f"OneBot Adapter ({adapter_signature})"

    def __getattr__(self, method_name: str) -> Any:
        action_spec = QZONE_ACTIONS.get(method_name)
        if action_spec is None:
            raise AttributeError(method_name)
        action, parameter_order = action_spec

        async def invoke(*args: Any, **kwargs: Any) -> dict[str, Any]:
            if len(args) > len(parameter_order):
                raise TypeError(f"{method_name} 收到过多位置参数。")
            params = dict(zip(parameter_order, args, strict=False))
            params.update(kwargs)
            params = {key: value for key, value in params.items() if value is not None}
            try:
                response = await adapter_api.send_adapter_command(
                    adapter_sign=self.adapter_signature,
                    command_name=action,
                    command_data=params,
                    timeout=ADAPTER_ACTION_TIMEOUT_SECONDS,
                )
            except Exception as error:
                message = f"{self.provider_name} 调用 {action} 失败: {error}"
                return _failed_response(message, code=-1)
            if not isinstance(response, dict):
                return _failed_response(
                    f"{self.provider_name} 的 {action} 返回了非对象响应。",
                    code=-1,
                )
            return response

        return invoke


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    provider: Any | None
    source: str | None
    service_signatures: tuple[str, ...]
    adapter_signatures: tuple[str, ...]
    diagnostic: str


_provider_cache: tuple[float, ProviderSnapshot] | None = None


def _active_qq_adapters() -> list[tuple[str, Any]]:
    """从核心运行时注册表读取已启动并标记为 QQ 的 Adapter。"""
    try:
        adapters = adapter_api.get_all_adapters()
    except Exception:
        return []
    found: list[tuple[str, Any]] = []
    for signature, adapter in adapters.items():
        platform = str(getattr(adapter, "platform", "") or "").strip().lower()
        if platform != "qq":
            continue
        is_connected = getattr(adapter, "is_connected", None)
        try:
            if callable(is_connected) and not bool(is_connected()):
                continue
        except Exception:
            continue
        found.append((str(signature), adapter))
    return found


def discover_qzone_provider(*, refresh: bool = False) -> ProviderSnapshot:
    """按已注册 Service、其他 QZone Service、在線 QQ Adapter 的顺序发现能力。"""
    global _provider_cache
    now = time.monotonic()
    if not refresh and _provider_cache and now < _provider_cache[0]:
        return _provider_cache[1]

    try:
        service_classes = service_api.get_all_services()
    except Exception:
        service_classes = {}
    signatures = tuple(sorted(service_classes))

    try:
        preferred = service_api.get_service(BACKEND_SERVICE_SIGNATURE)
    except Exception:
        preferred = None
    if preferred is not None:
        snapshot = ProviderSnapshot(
            preferred,
            BACKEND_SERVICE_SIGNATURE,
            signatures,
            tuple(signature for signature, _ in _active_qq_adapters()),
            "已发现 OneBot Expand QZone Service。",
        )
        _provider_cache = (now + PROVIDER_CACHE_SECONDS, snapshot)
        return snapshot

    for signature in signatures:
        if not signature.endswith(":service:qzone_service"):
            continue
        if signature.split(":", 1)[0] == "neo-foxzone":
            continue
        try:
            candidate = service_api.get_service(signature)
        except Exception:
            continue
        if candidate is None:
            continue
        if any(callable(getattr(candidate, name, None)) for name in QZONE_ACTIONS):
            snapshot = ProviderSnapshot(
                candidate,
                signature,
                signatures,
                tuple(signature for signature, _ in _active_qq_adapters()),
                f"已发现兼容 QZone Service: {signature}。",
            )
            _provider_cache = (now + PROVIDER_CACHE_SECONDS, snapshot)
            return snapshot

    adapters = _active_qq_adapters()
    if len(adapters) == 1:
        signature, _ = adapters[0]
        snapshot = ProviderSnapshot(
            AdapterQzoneProvider(signature),
            signature,
            signatures,
            tuple(item[0] for item in adapters),
            f"未发现 QZone Service；将尝试 QQ Adapter {signature} 的标准 action。",
        )
        _provider_cache = (now + PROVIDER_CACHE_SECONDS, snapshot)
        return snapshot

    if len(adapters) > 1:
        snapshot = ProviderSnapshot(
            None,
            None,
            signatures,
            tuple(item[0] for item in adapters),
            "发现多个已连接的 QQ Adapter，无法安全确认应使用哪个账号。",
        )
        _provider_cache = (now + PROVIDER_CACHE_SECONDS, snapshot)
        return snapshot

    snapshot = ProviderSnapshot(
        None,
        None,
        signatures,
        (),
        "未发现 OneBot Expand、兼容 QZone Service 或已连接的 QQ Adapter。",
    )
    _provider_cache = (now + PROVIDER_CACHE_SECONDS, snapshot)
    return snapshot


async def get_current_login_info(*, expected_qq: str | None = None) -> dict[str, Any]:
    """通过当前账号接口确认登录身份；配置值、文件名和昵称不作为证据。"""
    observed: list[tuple[str, str]] = []
    errors: list[str] = []

    try:
        account_service = service_api.get_service(ACCOUNT_SERVICE_SIGNATURE)
    except Exception as error:
        account_service = None
        errors.append(f"账号 Service 查询失败: {error}")
    login_method = getattr(account_service, "get_login_info", None)
    if callable(login_method):
        try:
            response = await asyncio.wait_for(
                login_method(), timeout=LOGIN_ACTION_TIMEOUT_SECONDS
            )
            account_qq = response_login_qq(response)
            if account_qq:
                observed.append((ACCOUNT_SERVICE_SIGNATURE, account_qq))
            else:
                errors.append("账号 Service 未返回可确认的登录 QQ。")
        except Exception as error:
            errors.append(f"账号 Service 查询失败: {error}")

    adapters = _active_qq_adapters()
    for signature, _ in adapters:
        try:
            response = await asyncio.wait_for(
                adapter_api.send_adapter_command(
                    adapter_sign=signature,
                    command_name="get_login_info",
                    command_data={},
                    timeout=LOGIN_ACTION_TIMEOUT_SECONDS,
                ),
                timeout=LOGIN_ACTION_TIMEOUT_SECONDS + 1.0,
            )
            account_qq = response_login_qq(response)
            if account_qq:
                observed.append((signature, account_qq))
            else:
                errors.append(f"{signature} 未返回可确认的登录 QQ。")
        except Exception as error:
            errors.append(f"{signature} 登录查询失败: {error}")

    unique = {account_qq for _, account_qq in observed}
    if len(unique) > 1:
        return {
            "status": "ambiguous",
            "qq": None,
            "sources": observed,
            "message": "当前账号接口返回多个不同 QQ，拒绝选择其中一个。",
        }
    if not unique:
        return {
            "status": "unknown",
            "qq": None,
            "sources": observed,
            "message": "；".join(errors) or "没有可用于确认账号的实时接口。",
        }

    current_qq = next(iter(unique))
    if expected_qq and current_qq != str(expected_qq).strip():
        return {
            "status": "mismatch",
            "qq": current_qq,
            "sources": observed,
            "message": f"当前登录 QQ 与要求账号 {expected_qq} 不一致。",
        }
    return {
        "status": "confirmed",
        "qq": current_qq,
        "sources": observed,
        "message": "当前登录 QQ 已由实时接口确认。",
    }


async def get_adapter_cookie_string(
    *, domain: str, expected_qq: str | None = None
) -> str:
    """从账号已核验的在线 Adapter 获取 Cookie，不输出或持久化其内容。"""
    adapters = _active_qq_adapters()
    if not adapters:
        raise RuntimeError("没有已连接的 QQ Adapter 可读取 Cookie。")

    matches: list[str] = []
    for signature, _ in adapters:
        try:
            response = await asyncio.wait_for(
                adapter_api.send_adapter_command(
                    adapter_sign=signature,
                    command_name="get_login_info",
                    command_data={},
                    timeout=LOGIN_ACTION_TIMEOUT_SECONDS,
                ),
                timeout=LOGIN_ACTION_TIMEOUT_SECONDS + 1.0,
            )
        except Exception:
            continue
        qq = response_login_qq(response)
        if qq and (expected_qq is None or qq == str(expected_qq)):
            matches.append(signature)

    if len(matches) != 1:
        if not matches:
            raise RuntimeError("没有 Adapter 的实时登录账号与目标账号匹配。")
        raise RuntimeError("多个 Adapter 登录到同一目标账号，Cookie 来源不明确。")

    signature = matches[0]
    response = await adapter_api.send_adapter_command(
        adapter_sign=signature,
        command_name="get_cookies",
        command_data={"domain": domain},
        timeout=LOGIN_ACTION_TIMEOUT_SECONDS,
    )
    if not response_succeeded(response):
        message = str(
            response.get("msg") or response.get("wording") or response.get("message")
            or "Adapter 未返回 Cookie。"
        )
        raise RuntimeError(message)
    payload = response.get("data")
    cookie_string = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(cookie_string, str) or not cookie_string.strip():
        raise RuntimeError("Adapter 返回的 Cookie 为空。")
    return cookie_string


__all__ = [
    "AdapterQzoneProvider",
    "ProviderSnapshot",
    "discover_qzone_provider",
    "get_adapter_cookie_string",
    "get_current_login_info",
    "response_login_qq",
    "response_succeeded",
]
