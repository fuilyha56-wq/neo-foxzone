"""Temporary local probe using the running core's real registered components."""

from __future__ import annotations

import importlib
import hashlib
import re
import time
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.app.plugin_system.api import adapter_api, plugin_api, service_api
from src.app.plugin_system.base import BasePlugin, BaseRouter, register_plugin
from src.core.components.types import EventType
from src.core.config import get_core_config
from src.core.models.stream import ChatStream
from src.core.transport.sink.sink_manager import get_sink_manager
from src.core.utils.security import VerifiedDep
from src.kernel.event import EventDecision, get_event_bus

EXPECTED_QQ = "3693525299"
SERVICE = "neo-foxzone:service:qzone_service"


def safe(value: Any) -> str:
    """Only return short test output with account identifiers masked."""
    text = str(value or "")[:1800]
    text = re.sub(r"\b\d{6,}\b", "******", text)
    text = re.sub(r"\b[0-9a-f]{24,}\b", "<test-id>", text)
    return re.sub(r"(?i)(cookie|token|p_skey|api_key)\s*[:=]\s*[^,\s]+", r"\1=<redacted>", text)


class Input(BaseModel):
    text: str


class PostInput(BaseModel):
    tid: str
    delete: bool = False


class LiveProbeRouter(BaseRouter):
    name = "live_probe"
    custom_route_path = "/_foxzone_live_probe"
    cors_origins = None

    def register_endpoints(self) -> None:
        @self.app.exception_handler(Exception)
        async def probe_error(request: Request, error: Exception) -> JSONResponse:
            return JSONResponse(status_code=502, content={"probe_error": safe(repr(error))})

        def local(request: Request) -> None:
            if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
                raise HTTPException(403, "local verification only")

        @self.app.get("/events", dependencies=[VerifiedDep])
        async def events(request: Request) -> dict[str, Any]:
            local(request)
            return {"events": self.plugin.events, "streams": len(self.plugin.streams)}

        @self.app.get("/flow", dependencies=[VerifiedDep])
        async def flow(request: Request) -> dict[str, Any]:
            local(request)
            from src.core.managers.stream_manager import get_stream_manager
            from src.core.managers.chatter_manager import get_chatter_manager
            from src.core.transport.distribution.stream_loop_manager import get_stream_loop_manager
            manager = get_stream_manager()
            loops = get_stream_loop_manager()
            out = []
            for sid in self.plugin.streams:
                stream = manager._streams.get(sid)
                context = getattr(stream, "context", None)
                task = getattr(context, "stream_loop_task", None)
                chatter = get_chatter_manager()._active_chatters.get(sid)
                waiting = loops._wait_states.get(sid)
                out.append({"stream_exists": stream is not None, "chat_type": getattr(context, "chat_type", None),
                            "unread": len(getattr(context, "unread_messages", [])),
                            "loop_active": task is not None and not task.done(),
                            "chatter": getattr(chatter, "name", None),
                            "wait_type": type(waiting[0]).__name__ if waiting else None})
            return {"core_loops_running": loops.is_running, "flow": out}

        @self.app.get("/status", dependencies=[VerifiedDep])
        async def status(request: Request) -> dict[str, Any]:
            local(request)
            service = service_api.get_service(SERVICE)
            if service is None:
                raise HTTPException(409, "NeoFoxZone service missing")
            info = await service.get_capability_status()
            config = service.plugin.config
            task = service.plugin._poll_task
            return {"provider_available": info["provider_available"], "write_allowed": info["write_allowed"],
                    "account_qq": info["account_qq"], "account_status": info["account_status"],
                    "polling_enabled": config.polling.enabled, "polling_task_running": task is not None and not task.done(),
                    "cooldown_active": service.plugin.runtime.polling_state.rate_limit_cooldown_active(),
                    "image_auto_decision_enabled": config.image.auto_decision_enabled}

        @self.app.post("/refresh-config", dependencies=[VerifiedDep])
        async def refresh_config(request: Request) -> dict[str, Any]:
            local(request)
            from src.core.managers.config_manager import get_config_manager
            plugin = plugin_api.get_plugin("neo-foxzone")
            if plugin is None:
                raise HTTPException(409, "NeoFoxZone plugin missing")
            get_config_manager().reload_config("neo-foxzone", plugin.configs[0])
            success = await plugin_api.reload_plugin("neo-foxzone")
            return {"config_refreshed": success}

        @self.app.post("/wake", dependencies=[VerifiedDep])
        async def wake(request: Request) -> dict[str, Any]:
            local(request)
            from src.core.components.types import WaitResumeEvent
            from src.core.transport.distribution.stream_loop_manager import get_stream_loop_manager
            for sid in self.plugin.streams:
                await get_stream_loop_manager().trigger_external_resume(sid, WaitResumeEvent(source="FZLIVE"))
            return {"test_stream_resume_requested": True}

        @self.app.post("/message", dependencies=[VerifiedDep])
        async def message(body: Input, request: Request) -> dict[str, Any]:
            local(request)
            text = body.text.strip()
            if len(text) > 1600 or not (text.startswith("/neo-foxzone ") or "FZLIVE" in text):
                raise HTTPException(400, "marked NeoFoxZone test messages only")
            module = importlib.import_module("plugins.neo-foxzone.providers")
            login = await module.get_current_login_info(expected_qq=EXPECTED_QQ)
            if login.get("status") != "confirmed" or str(login.get("qq")) != EXPECTED_QQ:
                raise HTTPException(409, "live test account not confirmed")
            snapshot = module.discover_qzone_provider(refresh=True)
            if len(snapshot.adapter_signatures) != 1:
                raise HTTPException(409, "expected one live QQ adapter")
            sign = snapshot.adapter_signatures[0]
            owners = [x.split(":", 1)[1] for x in get_core_config().permissions.owner_list if x.startswith("qq:")]
            if len(owners) != 1:
                raise HTTPException(409, "expected one configured QQ owner")
            owner = owners[0]
            # Send the test prompt to the configured user's private conversation.
            # Its local echo is explicitly an injected test input, never a claim
            # that QQ reported a human-originated message.
            sent = await adapter_api.send_adapter_command(
                adapter_sign=sign, command_name="send_private_msg",
                command_data={"user_id": int(owner), "message": text, "auto_escape": True},
                timeout=20,
            )
            if sent.get("status") != "ok" or not sent.get("data", {}).get("message_id"):
                raise HTTPException(502, safe(sent.get("wording") or "test prompt send failed"))
            message_id = str(sent["data"]["message_id"])
            self.plugin.ids.add(message_id)
            if message_id in self.plugin.received_ids:
                return {"queued": True, "source": "real SnowLuma OneBot message echo", "sequence": len(self.plugin.ids)}
            raw = {
                "time": int(time.time()), "self_id": int(EXPECTED_QQ), "post_type": "message",
                "message_type": "private", "sub_type": "friend", "message_id": message_id,
                "user_id": int(owner), "message": [{"type": "text", "data": {"text": text}}],
                "raw_message": text, "font": 0,
                "sender": {"user_id": int(owner), "nickname": "FZLIVE本机联调"},
            }
            adapter = adapter_api.get_all_adapters()[sign]
            envelope = await adapter.from_platform_message(raw)
            if envelope is None:
                raise HTTPException(409, "adapter filtered test input")
            await get_sink_manager()._receiver.receive_envelope(envelope, sign)
            return {"queued": True, "source": "authorized local OneBot test echo", "sequence": len(self.plugin.ids)}

        @self.app.post("/post", dependencies=[VerifiedDep])
        async def post(body: PostInput, request: Request) -> dict[str, Any]:
            local(request)
            service = service_api.get_service(SERVICE)
            if service is None:
                raise HTTPException(409, "NeoFoxZone service missing")
            owner = await service.get_verified_write_account()
            response = await service.get_qzone_msg_detail(tid=body.tid, host_uin=owner)
            if not service.response_succeeded(response):
                raise HTTPException(502, safe(service.response_error(response)))
            detail = response.get("data", {})
            if service._post_owner(detail) != owner or str(detail.get("tid")) != body.tid:
                raise HTTPException(409, "own post identity mismatch")
            if "FZLIVE" not in str(detail.get("content", "")):
                raise HTTPException(409, "test marker missing; refuse cleanup")
            if body.delete:
                result = await service.delete_qzone_msg(
                    body.tid, expected_author_qq=owner,
                    confirmation=f"DELETE {body.tid} {owner} {owner}",
                )
                return {"success": service.response_succeeded(result), "error": safe(service.response_error(result))}
            return {"success": True, "detail": detail}

        @self.app.post("/finish", dependencies=[VerifiedDep])
        async def finish(request: Request) -> dict[str, Any]:
            local(request)
            import asyncio
            async def remove() -> None:
                await asyncio.sleep(1)
                await plugin_api.unload_plugin("neo-foxzone-live-probe")
            asyncio.create_task(remove())
            return {"unload_scheduled": True}


@register_plugin
class LiveProbePlugin(BasePlugin):
    plugin_name = "neo-foxzone-live-probe"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self.events: list[dict[str, Any]] = []
        self.ids: set[str] = set()
        self.received_ids: set[str] = set()
        owners = [x.split(":", 1)[1] for x in get_core_config().permissions.owner_list if x.startswith("qq:")]
        self.streams: set[str] = {ChatStream.generate_stream_id("qq", user_id=x) for x in owners}
        self.unsubscribers: list[Any] = []

    def get_components(self) -> list[type]:
        return [LiveProbeRouter]

    async def observe(self, event: str, params: dict[str, Any]) -> tuple[Any, Any]:
        event_name = getattr(event, "value", str(event))
        message = params.get("message")
        mid = str(getattr(message, "message_id", ""))
        stream = str(params.get("stream_id") or getattr(message, "stream_id", ""))
        if mid in self.ids and stream:
            self.streams.add(stream)
        if mid not in self.ids and (not stream or stream not in self.streams):
            return EventDecision.PASS, params
        if event_name == EventType.ON_MESSAGE_RECEIVED.value:
            self.received_ids.add(mid)
        record = {"event": event_name, "at": time.time(), "keys": list(params)}
        if mid:
            record["message_hash"] = hashlib.sha256(mid.encode()).hexdigest()[:8]
        for key in ("signature", "tool_name", "command_path", "success", "execution_time"):
            if key in params:
                record[key] = params[key]
        if event_name in {EventType.AFTER_COMMAND_EXECUTE.value, EventType.ON_COMMAND_EXECUTE_FAILED.value}:
            record["result"] = safe(params.get("result") or params.get("error"))
        if event_name in {EventType.ON_MESSAGE_SENT.value, EventType.AFTER_MESSAGE_SENT.value}:
            record["text"] = safe(getattr(message, "processed_plain_text", None) or getattr(message, "content", ""))
        self.events.append(record)
        self.events = self.events[-250:]
        return EventDecision.PASS, params

    async def on_plugin_loaded(self) -> None:
        from src.core.managers.router_manager import get_router_manager
        await get_router_manager().mount_plugin_routers(self)
        bus = get_event_bus()
        for event in (EventType.ON_MESSAGE_RECEIVED, EventType.AFTER_COMMAND_EXECUTE,
                      EventType.ON_COMMAND_EXECUTE_FAILED, EventType.AFTER_TOOL_CALL,
                      EventType.ON_TOOL_CALL_FAILED, EventType.ON_MESSAGE_SENT, EventType.AFTER_MESSAGE_SENT):
            self.unsubscribers.append(bus.subscribe(event, self.observe, priority=1000))

    async def on_plugin_unloaded(self) -> None:
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        from src.core.managers.router_manager import get_router_manager
        await get_router_manager().unmount_plugin_routers(self.plugin_name)
