"""三条自治流程共享批量决策、持久去重、限流退避和结果报告。"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from src.kernel.logger import get_logger

from ..config import NeoFoxzoneConfig
from ..core.llm.content_service import ContentService
from ..runtime import ACTION_COMMENT, ACTION_LIKE, ACTION_READ, NeoFoxzoneRuntime

logger = get_logger("neo_foxzone.autopilot")
DecisionGenerator = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _comments(feed: dict[str, Any]) -> list[dict[str, Any]]:
    value = feed.get("comments") or feed.get("commentlist")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class AutonomousEngine:
    """每轮写入有上限，只有成功结果才提交完成状态。"""

    def __init__(self, service: Any, runtime: NeoFoxzoneRuntime,
                 config: NeoFoxzoneConfig, decision_generator: DecisionGenerator | None = None) -> None:
        self.service, self.runtime, self.config = service, runtime, config
        self._decision_generator = decision_generator
        self._content_service = ContentService(config)
        self._report: dict[str, Any] = {}

    async def _cycle(self, name: str, operation: Callable[[], Awaitable[int]]) -> int:
        async with self.runtime.autonomous_lock:
            started = time.time()
            self._report = dict(started_at=started, candidates=0, llm_requests=0,
                                sent=0, attempted=0, failed=0, skipped=0, errors=[])
            try:
                if self.runtime.polling_state.rate_limit_cooldown_active():
                    self._report["cooldown"] = True
                    return 0
                return await operation()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._report["failed"] += 1
                self._report["errors"].append(type(error).__name__)
                logger.warning(f"自治流程 {name} 失败: {type(error).__name__}")
                return self._report["sent"]
            finally:
                self._report["duration_seconds"] = round(time.time() - started, 3)
                self.runtime.autonomous_reports[name] = dict(self._report)

    def _eligible(self, identity: str) -> bool:
        state = self.runtime.polling_state
        return not (state.is_processed(identity) or state.is_in_flight(identity)
                    or state.retry_after(identity) > time.time())

    def _recent(self, comment: dict[str, Any]) -> bool:
        maximum = self.config.monitor.max_comment_age_hours
        value = comment.get("created_time") or comment.get("create_time") or comment.get("time")
        if not maximum or value in (None, ""):
            return True
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            try:
                timestamp = datetime.fromisoformat(str(value)).timestamp()
            except ValueError:
                return True
        return time.time() - timestamp <= maximum * 3600

    async def _context(self, feed: dict[str, Any], comment: dict[str, Any] | None = None) -> dict[str, Any]:
        enrich = getattr(self.service, "enrich_feed_context", None)
        context = await enrich(feed) if callable(enrich) else dict(feed)
        context = {key: value for key, value in context.items()
                   if key in {"content", "images", "image_descriptions", "_image_contents"}}
        context["feed"] = context.pop("content", "")
        if comment is not None:
            context.update(comment=comment.get("content", ""), commenter_name=comment.get("nickname", ""))
        return context

    async def _decide(self, contexts: list[dict[str, Any]], *, replies: bool) -> dict[int, dict[str, Any]]:
        if not contexts:
            return {}
        if self._decision_generator is not None:
            self._report["llm_requests"] += len(contexts)
            return {i: await self._decision_generator(context) for i, context in enumerate(contexts)}
        self._report["llm_requests"] += 1
        values = await (self._content_service.generate_batch_replies(contexts) if replies
                        else self._content_service.generate_feed_decisions(contexts))
        result = {}
        for value in values:
            index = value.get("index")
            if isinstance(index, int) and 0 <= index < len(contexts) and index not in result:
                result[index] = value
        return result

    async def _send(self, identity: str, operation: Callable[[], Awaitable[bool]]) -> bool:
        state = self.runtime.polling_state
        if (self._report["attempted"] >= self.config.monitor.max_actions_per_cycle
                or state.rate_limit_cooldown_active() or not self._eligible(identity)):
            self._report["skipped"] += 1
            return False
        if self._report["sent"]:
            minimum = max(0.0, self.config.polling.send_jitter_seconds_min)
            maximum = max(minimum, self.config.polling.send_jitter_seconds_max)
            await asyncio.sleep(random.uniform(minimum, maximum))
        if not self._eligible(identity) or state.rate_limit_cooldown_active():
            return False
        state.reserve(identity)
        await state.save()
        self._report["attempted"] += 1
        try:
            succeeded = await operation()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            succeeded = False
            self._report["errors"].append(type(error).__name__)
            if "1012" in str(error) or "-10049" in str(error):
                state.record_rate_limit_cooldown(time.time() + self.config.polling.rate_limit_retry_minutes * 60)
        if succeeded:
            state.mark_processed(identity)
            self._report["sent"] += 1
        else:
            # 未知是否落库时保留占用，避免超时后的即时重复写入。
            state.record_failure(identity, retry_after=time.time() + self.config.polling.failure_retry_minutes * 60)
            self._report["failed"] += 1
        await state.save()
        return bool(succeeded)

    async def _reply_jobs(self, jobs: list[dict[str, Any]], *, external: bool) -> int:
        contexts, ready = [], []
        for job in jobs[:self.config.monitor.max_decisions_per_cycle]:
            try:
                contexts.append(await self._context(job["feed"], job["comment"]))
                ready.append(job)
            except Exception as error:
                self._report["errors"].append(type(error).__name__)
                self._report["failed"] += 1
        self._report["candidates"] = len(ready)
        decisions = await self._decide(contexts, replies=True)
        for index, job in enumerate(ready):
            if index not in decisions:
                self.runtime.polling_state.record_failure(job["identity"],
                    retry_after=time.time() + self.config.polling.generation_retry_minutes * 60)
                continue
            reply = _text(decisions[index].get("reply") or decisions[index].get("comment"))[:self.config.llm.max_reply_chars]
            if not reply:
                self._report["skipped"] += 1
                continue
            owner, tid, comment, root = job["owner"], job["tid"], job["comment"], job["root"]
            if external and self.runtime.interaction_log.get_external_reply_count(owner, tid) >= self.config.monitor.max_external_replies:
                continue

            async def send(owner=owner, tid=tid, comment=comment, root=root, reply=reply):
                return await self.service.reply_comment(tid, owner, _text(comment.get("nickname")),
                    reply, root, _text(comment.get("qq_account") or comment.get("uin")))

            if await self._send(job["identity"], send):
                await self.service.mark_comment_replied(tid, _text(comment.get("comment_tid") or comment.get("comment_id")))
                if external:
                    self.runtime.interaction_log.increment_external_reply_count(owner, tid)
                    await self.runtime.interaction_log.save()
        await self.runtime.polling_state.save()
        return self._report["sent"]

    async def run_self_comments(self) -> int:
        return await self._cycle("self_comments", self._self_comments)

    async def _self_comments(self) -> int:
        bot = await self.service.self_qq()
        if not bot:
            return 0
        jobs = []
        for feed in await self.service.list_own_feeds_with_comments(self.config.polling.own_posts_count):
            tid = _text(feed.get("tid"))
            comments = _comments(feed)
            roots = {_text(c.get("comment_tid") or c.get("comment_id")) for c in comments if not c.get("parent_tid")}
            for comment in comments:
                cid = _text(comment.get("comment_tid") or comment.get("comment_id"))
                author = _text(comment.get("qq_account") or comment.get("uin"))
                root = _text(comment.get("parent_tid")) or cid
                identity = f"own_post:{bot}:{tid}:{cid}"
                if (not tid or not cid or not author or author == bot or root not in roots
                        or not self._recent(comment) or not self._eligible(identity)
                        or await self.service.has_replied_comment(tid, cid)):
                    continue
                if any(_text(c.get("qq_account") or c.get("uin")) == bot and _text(c.get("parent_tid")) == cid for c in comments):
                    continue
                jobs.append(dict(feed=feed, comment=comment, owner=bot, tid=tid, root=root, identity=identity))
        return await self._reply_jobs(jobs, external=False)

    async def run_external_followups(self) -> int:
        return await self._cycle("external_followups", self._external_followups)

    async def _external_followups(self) -> int:
        bot = await self.service.self_qq()
        if not bot:
            return 0
        jobs, checked = [], []
        for owner, tid in await self.service.iter_followup_feeds(exclude_qq=bot,
                limit=self.config.monitor.followup_count, max_feed_age_hours=self.config.monitor.max_followup_age_hours):
            if self.runtime.interaction_log.get_external_reply_count(owner, tid) >= self.config.monitor.max_external_replies:
                continue
            detail = await self.service.get_feed_detail(owner, tid)
            if detail is None:
                continue
            comments = _comments(detail)
            bot_roots = {_text(c.get("comment_tid")) for c in comments
                         if _text(c.get("qq_account") or c.get("uin")) == bot and not c.get("parent_tid")}
            for comment in comments:
                cid, parent = _text(comment.get("comment_tid")), _text(comment.get("parent_tid"))
                author = _text(comment.get("qq_account") or comment.get("uin"))
                identity = f"friend_feed:{owner}:{tid}:{cid}"
                if (not cid or not author or author == bot or parent not in bot_roots
                        or not self._recent(comment) or not self._eligible(identity)
                        or await self.service.has_replied_comment(tid, cid)):
                    continue
                jobs.append(dict(feed=detail, comment=comment, owner=owner, tid=tid, root=parent, identity=identity))
            checked.append((owner, tid))
        sent = await self._reply_jobs(jobs, external=True)
        for owner, tid in checked:
            await self.service.mark_followup_checked(owner, tid)
        return sent

    async def run_friend_monitor(self) -> int:
        return await self._cycle("friend_monitor", self._friend_monitor)

    async def _friend_monitor(self) -> int:
        if not self.config.monitor.enabled:
            return 0
        contexts, feeds = [], []
        for feed in (await self.service.get_monitor_feeds(self.config.monitor.feed_count))[:self.config.monitor.max_decisions_per_cycle]:
            owner, tid = _text(feed.get("target_qq") or feed.get("uin")), _text(feed.get("tid"))
            if not owner or not tid or self.runtime.interaction_log.has_seen(owner, tid):
                continue
            try:
                context = await self._context(feed)
                context["target_qq"] = owner
                contexts.append(context)
                feeds.append((owner, tid, feed))
            except Exception as error:
                self._report["errors"].append(type(error).__name__)
                self._report["failed"] += 1
        self._report["candidates"] = len(feeds)
        decisions = await self._decide(contexts, replies=False)
        for index, (owner, tid, feed) in enumerate(feeds):
            if index not in decisions:
                continue
            decision, complete = decisions[index], True
            if (self.config.monitor.always_like or decision.get("like") is True) and not (feed.get("liked") or self.runtime.interaction_log.has_liked(owner, tid)):
                complete = await self._send(f"autonomous:like:{owner}:{tid}", lambda owner=owner, tid=tid: self.service.like(owner, tid))
                if complete:
                    await self.service.mark_interaction(owner, tid, ACTION_LIKE)
            comment = _text(decision.get("comment"))[:self.config.llm.max_reply_chars]
            if comment and not self.runtime.interaction_log.has_commented(owner, tid):
                ok = await self._send(f"autonomous:comment:{owner}:{tid}", lambda owner=owner, tid=tid, comment=comment: self.service.comment(owner, tid, comment))
                complete = complete and ok
                if ok:
                    await self.service.mark_interaction(owner, tid, ACTION_COMMENT)
            if complete:
                await self.service.mark_interaction(owner, tid, ACTION_READ)
        return self._report["sent"]


class AutonomousScheduler:
    """独立开关和间隔；启动与手动检查均遵守免打扰设置。"""

    def __init__(self, engine: AutonomousEngine, config: NeoFoxzoneConfig) -> None:
        self.engine, self.config = engine, config

    def in_dnd(self) -> bool:
        start, end = int(self.config.general.dnd_start) % 24, int(self.config.general.dnd_end) % 24
        hour = datetime.now().hour
        return start != end and (start <= hour < end if start < end else hour >= start or hour < end)

    def enabled(self, name: str) -> bool:
        return {"self_comments": self.config.monitor.self_comments_enabled,
                "external_followups": self.config.monitor.external_followup_enabled,
                "friend_monitor": self.config.monitor.enabled}.get(name, False)

    async def run_once(self, operation: Callable[[], Awaitable[int]], name: str) -> int:
        if not self.enabled(name) or self.in_dnd():
            self.engine.runtime.autonomous_reports[name] = {
                "sent": 0, "skipped": 1,
                "reason": "disabled" if not self.enabled(name) else "dnd"}
            return 0
        return await operation()

    async def run_loop(self, operation: Callable[[], Awaitable[int]], name: str) -> None:
        interval = {"self_comments": self.config.monitor.self_interval_minutes,
                    "friend_monitor": self.config.monitor.friend_interval_minutes,
                    "external_followups": self.config.monitor.external_interval_minutes}[name]
        while True:
            await self.run_once(operation, name)
            await asyncio.sleep(max(60.0, interval * 60.0))


__all__ = ["AutonomousEngine", "AutonomousScheduler"]
