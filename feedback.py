"""QZone 活动作为真实适配器消息进入核心，再通过同一线程回复。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from typing import Any

from mofox_wire import MessageEnvelope

from src.app.plugin_system.api import adapter_api, send_api, service_api, storage_api, stream_api
from src.app.plugin_system.base import BaseAdapter, BaseChatter
from src.core.components.types import ChatType, PlatformSendResult, Success, Wait
from src.kernel.logger import get_logger

from . import SERVICE_SIGNATURE
from .core.llm.content_service import ContentService
from .feed_parser import extract_reply_candidates
from .poller import PollReport, is_rate_limit_error

ADAPTER_SIGNATURE = "neo-foxzone:adapter:qzone_feedback"
logger = get_logger("neo_foxzone.feedback")
_TERMINAL = {"sent", "ignored", "baseline"}


def event_id(identity: str) -> str:
    """保留平台命名空间，不把评论 ID 当作 QQ 消息 ID。"""
    return "qzone:" + hashlib.sha256(identity.encode()).hexdigest()


def thread_id(event: dict[str, Any]) -> str:
    """每条说说的顶层评论拥有独立会话。"""
    key = f"{event['post_owner_uin']}:{event['post_id']}:{event.get('root_comment_id') or 'post'}"
    return hashlib.sha256(key.encode()).hexdigest()


class ActivityStore:
    """先保存活动，再投递；回复结果不明时保留占用以阻止重复写入。"""

    def __init__(self, maximum: int = 2000) -> None:
        self.maximum = maximum
        self.baselined = False
        self.records: dict[str, dict[str, Any]] = {}
        self.lock = asyncio.Lock()

    async def load(self) -> None:
        payload = await storage_api.load_json("neo-foxzone", "feedback_state")
        if isinstance(payload, dict):
            self.baselined = payload.get("baselined") is True
            records = payload.get("records")
            self.records = {key: dict(value) for key, value in (records.items() if isinstance(records, dict) else [])
                            if isinstance(key, str) and isinstance(value, dict)}

    async def save(self) -> None:
        terminal = [key for key, value in self.records.items() if value.get("status") in _TERMINAL]
        for key in terminal[:max(0, len(self.records) - self.maximum)]:
            del self.records[key]
        await storage_api.save_json("neo-foxzone", "feedback_state",
                                    {"version": 1, "baselined": self.baselined, "records": self.records})

    def pending_count(self) -> int:
        return sum(record.get("status") not in _TERMINAL for record in self.records.values())

    async def observe(self, event: dict[str, Any], *, baseline: bool, pending_limit: int) -> bool:
        key = event_id(event["identity"])
        async with self.lock:
            if key in self.records:
                return False
            if not baseline and self.pending_count() >= pending_limit:
                return False
            self.records[key] = {"status": "baseline" if baseline else "pending",
                                 "event": event, "updated_at": time.time(), "delivered_at": 0.0}
            try:
                await self.save()
            except BaseException:
                self.records.pop(key, None)
                raise
            return not baseline

    async def update(self, key: str, status: str, **extra: Any) -> None:
        record = self.records[key]
        record.update(status=status, updated_at=time.time(), **extra)
        await self.save()


class QzoneFeedbackAdapter(BaseAdapter):
    """进程内适配器，使用核心配置的 Sink；不监听网络端口。"""

    name = "qzone_feedback"
    platform = "qzone"
    adapter_version = "1.0.0"
    description = "QQ 空间新评论和好友动态消息反馈"
    dependencies = [SERVICE_SIGNATURE]

    async def health_check(self) -> bool:
        return self.core_sink is not None and not self._closed

    async def get_bot_info(self) -> dict[str, Any]:
        service = service_api.get_service(SERVICE_SIGNATURE)
        return {"bot_id": str(await service.get_verified_write_account()), "bot_name": "MoFox", "platform": self.platform}

    async def from_platform_message(self, raw: Any) -> MessageEnvelope:
        if not isinstance(raw, dict) or not raw.get("identity") or not raw.get("post_owner_uin"):
            raise ValueError("空间活动缺少经过核验的身份。")
        key = event_id(raw["identity"])
        store = self.plugin.feedback_store
        if key not in store.records or store.records[key].get("event") != raw:
            raise ValueError("活动未先保存到本插件的消息队列。")
        text = "[QQ空间新动态]" if raw["kind"] == "post" else "[QQ空间新评论]"
        # 标签前缀也避免外部正文被核心命令匹配器当成 /命令执行。
        text += "\n" + json.dumps({field: raw.get(field) for field in
                                  ("post_content", "parent_content", "comment_content")}, ensure_ascii=False)
        return {"direction": "incoming", "message_info": {
            "platform": self.platform, "message_id": key, "time": time.time(), "message_type": "message",
            "user_info": {"user_id": str(raw["commenter_uin"]), "user_nickname": raw["commenter_name"]},
            "group_info": {"platform": self.platform, "group_id": thread_id(raw), "group_name": "QQ空间评论线程"},
            "extra": {"qzone_event_id": key, "qzone_activity_type": raw["kind"],
                      "format_info": {"content_format": ["text"], "accept_format": ["text"]}}},
            "message_segment": [{"type": "text", "data": text}]}

    async def _send_platform_message(self, envelope: MessageEnvelope) -> PlatformSendResult:
        segments = envelope.get("message_segment", [])
        if isinstance(segments, dict):
            segments = [segments]
        reply_ids = [str(seg.get("data")) for seg in segments if seg.get("type") == "reply"]
        texts = [str(seg.get("data") or "") for seg in segments if seg.get("type") == "text"]
        if len(reply_ids) != 1 or not texts or any(seg.get("type") not in {"reply", "text"} for seg in segments):
            return PlatformSendResult(False, error="空间回复必须引用一条已保存活动，且仅允许文本。")
        key = reply_ids[0]
        store = self.plugin.feedback_store
        async with store.lock:
            record = store.records.get(key)
            if not record or record.get("status") != "processing":
                return PlatformSendResult(False, error="活动已处理或未获得处理权。")
            event = record["event"]
            group = envelope.get("message_info", {}).get("group_info") or {}
            if group.get("group_id") != thread_id(event):
                return PlatformSendResult(False, error="回复会话与目标评论线程不一致。")
            state = self.plugin.runtime.polling_state
            already_done = state.is_processed(event["identity"])
            if event["kind"] == "post":
                already_done = already_done or self.plugin.runtime.interaction_log.has_commented(str(event["post_owner_uin"]), event["post_id"])
            if already_done:
                await store.update(key, "ignored")
                return PlatformSendResult(False, error="此活动已由其他流程处理，已忽略。")
            if state.is_in_flight(event["identity"]) or state.rate_limit_cooldown_active():
                return PlatformSendResult(False, error="活动已处理、发送结果待确认或处于协议冷却。")
            service = service_api.get_service(SERVICE_SIGNATURE)
            attempted = False
            reserved = False
            try:
                content = "".join(texts).strip()[:self.plugin._config().llm.max_reply_chars]
                if event["kind"] == "post":
                    detail = await service.get_feed_detail(str(event["post_owner_uin"]), event["post_id"])
                    if detail is None:
                        raise ValueError("新动态目标已无法核验。")
                else:
                    detail = await service.get_qzone_msg_detail(tid=event["post_id"], host_uin=event["post_owner_uin"])
                    bot_uin = await service.get_verified_write_account()
                    container = "msglist" if event["source"] == "own_post" else "feeds"
                    post = dict(detail.get("data") or {})
                    if not service.response_succeeded(detail) or str(post.get("tid")) != event["post_id"] or service._post_owner(post) != event["post_owner_uin"]:
                        raise ValueError("评论详情身份不匹配。")
                    verified = extract_reply_candidates(
                        {"data": {container: [post]}}, bot_uin=bot_uin, detail_verified=True,
                        known_bot_comment_ids={post: set(ids) for post, ids in state.bot_comments_by_post.items()},
                        known_bot_comment_roots=state.bot_comment_roots_by_post)
                    if not any(item.identity == event["identity"] and item.commenter_uin == event["commenter_uin"]
                               and item.root_comment_id == event["root_comment_id"] for item in verified):
                        raise ValueError("目标新评论或线程关系已无法核验。")
                if state.is_processed(event["identity"]) or state.is_in_flight(event["identity"]) or state.rate_limit_cooldown_active():
                    raise ValueError("活动已处理、被其他流程占用或正在限流冷却。")
                state.reserve(event["identity"])
                reserved = True
                await store.update(key, "send_inflight")
                await state.save()
                attempted = True
                if event["kind"] == "post":
                    response = await service.comment_qzone(tid=event["post_id"], target_uin=event["post_owner_uin"], content=content)
                else:
                    response = await service.reply_qzone_comment(
                        tid=event["post_id"], host_uin=event["post_owner_uin"],
                        root_comment_id=event["root_comment_id"], target_uin=event["commenter_uin"],
                        target_name=event["commenter_name"], content=content)
                if not service.response_succeeded(response):
                    raise RuntimeError(str(response.get("message") or response.get("wording") or "空间写入失败"))
            except Exception as error:
                if is_rate_limit_error(error):
                    state.record_rate_limit_cooldown(time.time() + self.plugin._config().polling.rate_limit_retry_minutes * 60)
                    await state.save()
                if not attempted:
                    if reserved:
                        state.release(event["identity"])
                        await state.save()
                    await store.update(key, "pending", delivered_at=time.time())
                # 请求可能已到达 QQ，保留占用，禁止重新发送相同活动。
                logger.warning(f"空间消息发送失败，保留占用: {type(error).__name__}")
                return PlatformSendResult(False, error="空间写入失败；结果待核验，已阻止自动重发。")
            state.mark_processed(event["identity"])
            await state.save()
            await store.update(key, "sent")
            if event["kind"] == "post":
                await service.mark_interaction(str(event["post_owner_uin"]), event["post_id"], "comment")
            data = response.get("data") or {}
            remote_id = data.get("commentid") or data.get("comment_id") or data.get("id")
            return PlatformSendResult(True, message_id=str(remote_id) if remote_id else None)


class QzoneActivityChatter(BaseChatter):
    """只处理 qzone 消息，由核心的会话驱动器运行。"""

    name = "qzone_activity"
    description = "QQ空间活动的回复或忽略决策"
    associated_platforms = ["qzone"]
    chat_type = ChatType.GROUP
    allow_message_buffer = False
    dependencies = [SERVICE_SIGNATURE]

    async def execute(self):
        while True:
            stream = await stream_api.get_stream(self.stream_id)
            if stream is None or not stream.context.unread_messages:
                yield Wait()
                continue
            messages = stream.context.flush_unreads_to_history()
            store = self.plugin.feedback_store
            config = self.plugin._config()
            for message in messages:
                key = message.extra.get("qzone_event_id")
                async with store.lock:
                    record = store.records.get(key)
                    if not record or record.get("status") not in {"pending", "processing"}:
                        continue
                    if record.get("status") == "processing" and record.get("updated_at", 0) + config.feedback.decision_timeout_seconds + 30 > time.time():
                        continue
                    await store.update(key, "processing", decision_attempts=int(record.get("decision_attempts", 0)) + 1)
                    event = dict(record["event"])
                scheduler = getattr(self.plugin, "_scheduler", None)
                if scheduler and scheduler.in_dnd():
                    async with store.lock:
                        await store.update(key, "pending", delivered_at=time.time())
                    continue
                try:
                    service = service_api.get_service(SERVICE_SIGNATURE)
                    context = {"content": event["post_content"], "images": event.get("post_images", [])}
                    context.update({field: event.get(field) for field in
                                    ("comment_content", "commenter_name", "parent_content", "kind")})
                    context["conversation_history"] = [str(msg.processed_plain_text or msg.content)[:600]
                                                        for msg in stream.context.history_messages[-8:] if msg is not message]
                    async with asyncio.timeout(config.feedback.decision_timeout_seconds):
                        context = await service.enrich_feed_context(context)
                        content_service = ContentService(config, stream_id=self.stream_id)
                        decisions = await content_service.generate_batch_replies([context])
                    if len(decisions) != 1 or decisions[0].get("index") != 0:
                        raise ValueError(content_service.last_error or "InvalidDecision")
                    reply = decisions[0]["reply"]
                    if not reply:
                        async with store.lock:
                            await store.update(key, "ignored")
                    else:
                        success = await send_api.send_text(reply, self.stream_id, platform="qzone",
                                                           reply_to=key, adapter_signature=ADAPTER_SIGNATURE)
                        if not success and store.records[key]["status"] == "processing":
                            async with store.lock:
                                await store.update(key, "pending")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    async with store.lock:
                        if store.records[key]["status"] == "processing":
                            await store.update(key, "pending", delivered_at=time.time(), last_error=str(error)[:80] if isinstance(error, ValueError) else type(error).__name__)
                    logger.warning(f"空间消息决策失败: {type(error).__name__}")
            yield Success("空间未读活动已处理")


class ActivityBridge:
    """复用严格的评论查询，把新活动交给已注册适配器。"""

    def __init__(self, plugin: Any, poller: Any, service: Any) -> None:
        self.plugin, self.poller, self.service = plugin, poller, service
        self.last_report: dict[str, Any] = {}
        self.lock = asyncio.Lock()

    async def poll_once(self) -> PollReport:
        async with self.lock:
            config = self.plugin._config()
            store = self.plugin.feedback_store
            report = PollReport()
            if self.plugin.runtime.polling_state.rate_limit_cooldown_active():
                self.last_report = {"skipped": "protocol_cooldown"}
                return report
            candidates = await self.poller.collect_candidates(report)
            events = [dict(asdict(candidate), identity=candidate.identity, kind="reply" if candidate.parent_comment_id else "comment")
                      for candidate in candidates if candidate.detail_verified and candidate.root_comment_id and candidate.post_owner_uin]
            if config.feedback.include_friend_posts and not report.query_errors:
                for feed in await self.service.get_monitor_feeds(config.monitor.feed_count):
                    owner = int(feed["target_qq"])
                    if owner == await self.service.get_verified_write_account():
                        continue
                    events.append({"identity": f"feed:{owner}:{feed['tid']}", "kind": "post",
                                   "post_id": feed["tid"], "post_owner_uin": owner, "post_content": feed["content"],
                                   "commenter_uin": owner, "commenter_name": str(feed.get("nickname") or owner),
                                   "root_comment_id": None, "comment_content": "", "parent_content": "",
                                   "post_images": feed.get("images", [])})
            baseline = not store.baselined and not config.feedback.emit_existing_on_first_poll
            for event in events:
                if not self.plugin.runtime.polling_state.is_processed(event["identity"]):
                    await store.observe(event, baseline=baseline, pending_limit=config.feedback.max_pending_events)
            if not report.query_errors:
                async with store.lock:
                    store.baselined = True
                    await store.save()
            adapter = adapter_api.get_adapter(ADAPTER_SIGNATURE)
            if adapter is None:
                await adapter_api.start_adapter(ADAPTER_SIGNATURE)
                adapter = adapter_api.get_adapter(ADAPTER_SIGNATURE)
            delivered = 0
            scheduler = getattr(self.plugin, "_scheduler", None)
            in_dnd = bool(scheduler and scheduler.in_dnd())
            if adapter is not None and not in_dnd:
                for key, record in list(store.records.items()):
                    if delivered >= config.feedback.max_events_per_poll:
                        break
                    if record.get("status") not in {"pending", "processing"}:
                        continue
                    if record.get("delivered_at", 0) + config.feedback.delivery_retry_seconds > time.time():
                        continue
                    await adapter.on_platform_message(record["event"])
                    async with store.lock:
                        record["delivered_at"] = time.time()
                        await store.save()
                    delivered += 1
            report.candidates = len(events)
            self.poller.last_report = report
            self.last_report = {"candidates": len(events), "delivered": delivered, "pending": store.pending_count(),
                                "baseline_ready": store.baselined, "adapter_active": adapter is not None,
                                "dnd_active": in_dnd,
                                "native_unread_supported": False, "activity_types": ["comment", "reply", "post"],
                                "query_errors": len(report.query_errors)}
            return report
