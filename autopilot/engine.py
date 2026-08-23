"""Neo FoxZone 无浏览器自治互动引擎。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Protocol

from src.kernel.logger import get_logger

from ..config import NeoFoxzoneConfig
from ..core.llm.content_service import ContentService
from ..runtime import ACTION_COMMENT, ACTION_LIKE, ACTION_READ, NeoFoxzoneRuntime

logger = get_logger("neo_foxzone.autopilot")


class AutonomousService(Protocol):
    """自治引擎依赖的 FoxZone Service 门面。"""

    async def list_own_feeds_with_comments(self, num: int = 5) -> list[dict[str, Any]]: ...
    async def get_monitor_feeds(self, num: int = 10) -> list[dict[str, Any]]: ...
    async def get_feed_detail(self, host_qq: str, feed_id: str) -> dict[str, Any] | None: ...
    async def reply_comment(self, feed_id: str, host_qq: str, target_name: str, reply_text: str, comment_tid: str, commenter_qq: str = "") -> bool: ...
    async def comment(self, target_qq: str, feed_id: str, text: str) -> bool: ...
    async def like(self, target_qq: str, feed_id: str) -> bool: ...
    async def mark_comment_replied(self, feed_id: str, comment_tid: str) -> None: ...
    async def has_replied_comment(self, feed_id: str, comment_tid: str) -> bool: ...
    async def mark_interaction(self, target_qq: str, feed_id: str, action: str, source: str = "agent") -> None: ...
    async def iter_followup_feeds(self, exclude_qq: str = "", limit: int = 0, max_feed_age_hours: float = 0.0, only_target_qq: str = "") -> list[tuple[str, str]]: ...
    async def mark_followup_checked(self, target_qq: str, feed_id: str) -> None: ...
    async def self_qq(self) -> str: ...


DecisionGenerator = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _text(value: object) -> str:
    """规范化外部字段。"""
    return str(value).strip() if value is not None else ""


def _comments(feed: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 Service 已验证的平铺评论列表。"""
    value = feed.get("comments") or feed.get("commentlist")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class AutonomousEngine:
    """实现自己评论、外部回查和好友动态互动三条自治流程。"""

    def __init__(self, service: AutonomousService, runtime: NeoFoxzoneRuntime, config: NeoFoxzoneConfig, decision_generator: DecisionGenerator | None = None) -> None:
        """注入无状态 Service、共享 Runtime 和可替换模型。"""
        self.service = service
        self.runtime = runtime
        self.config = config
        self._uses_default_decision = decision_generator is None
        self._decision_generator = decision_generator or self._generate_decision
        self._content_service = ContentService(config)

    async def _generate_decision(self, context: dict[str, Any]) -> dict[str, Any]:
        """请求模型返回一条严格 JSON 互动决策。"""
        decisions = await self._content_service.generate_feed_decisions([context])
        return decisions[0] if decisions else {}

    async def _generate_reply(self, context: dict[str, Any]) -> str:
        """请求模型生成一条评论回复。"""
        replies = await self._content_service.generate_batch_replies([context])
        return _text(replies[0].get("reply")) if replies else ""

    async def _reply_for(self, context: dict[str, Any]) -> str:
        """使用注入决策器或统一内容服务生成回复。"""
        if not self._uses_default_decision:
            decision = await self._decision_generator(context)
            return _text(decision.get("reply") or decision.get("comment"))
        return await self._generate_reply(context)

    async def run_self_comments(self) -> int:
        """检查 Bot 自己动态下的新评论并回复顶层评论。"""
        bot_qq = await self.service.self_qq()
        if not bot_qq:
            return 0
        sent = 0
        feeds = await self.service.list_own_feeds_with_comments(self.config.polling.own_posts_count)
        for feed in feeds:
            feed_id = _text(feed.get("tid"))
            for comment in _comments(feed):
                comment_id = _text(comment.get("comment_tid") or comment.get("comment_id"))
                commenter = _text(comment.get("qq_account") or comment.get("uin"))
                if not feed_id or not comment_id or not commenter or commenter == bot_qq:
                    continue
                if _text(comment.get("parent_tid")) or await self.service.has_replied_comment(feed_id, comment_id):
                    continue
                reply = await self._reply_for(
                    {"feed": feed.get("content", ""), "comment": comment.get("content", "")}
                )
                reply = reply[: max(1, int(self.config.llm.max_reply_chars))]
                if not reply:
                    continue
                if await self.service.reply_comment(feed_id, bot_qq, _text(comment.get("nickname")), reply, comment_id, commenter):
                    await self.service.mark_comment_replied(feed_id, comment_id)
                    sent += 1
        return sent

    async def run_external_followups(self) -> int:
        """回查曾评论过的外部动态，并在 Bot 评论下接力回复。"""
        bot_qq = await self.service.self_qq()
        sent = 0
        for target_qq, feed_id in await self.service.iter_followup_feeds(exclude_qq=bot_qq, limit=self.config.monitor.followup_count):
            detail = await self.service.get_feed_detail(target_qq, feed_id)
            if detail is None:
                continue
            count = self.runtime.interaction_log.get_external_reply_count(target_qq, feed_id)
            bot_roots = {
                _text(comment.get("comment_tid"))
                for comment in _comments(detail)
                if _text(comment.get("qq_account") or comment.get("uin")) == bot_qq
                and not _text(comment.get("parent_tid"))
            }
            for comment in _comments(detail):
                if count >= self.config.monitor.max_external_replies:
                    break
                parent_tid = _text(comment.get("parent_tid"))
                if parent_tid not in bot_roots:
                    continue
                comment_id = _text(comment.get("comment_tid"))
                commenter = _text(comment.get("qq_account") or comment.get("uin"))
                if not comment_id or not commenter or commenter == bot_qq:
                    continue
                reply = await self._reply_for(
                    {"feed": detail.get("content", ""), "comment": comment.get("content", "")}
                )
                reply = reply[: max(1, int(self.config.llm.max_reply_chars))]
                if reply and await self.service.reply_comment(feed_id, target_qq, _text(comment.get("nickname")), reply, parent_tid, commenter):
                    self.runtime.interaction_log.increment_external_reply_count(target_qq, feed_id)
                    await self.runtime.interaction_log.save()
                    count += 1
                    sent += 1
            await self.service.mark_followup_checked(target_qq, feed_id)
        return sent

    async def run_friend_monitor(self) -> int:
        """读取未处理好友动态并执行点赞、评论和已读持久化。"""
        if not self.config.monitor.enabled:
            return 0
        sent = 0
        feeds = await self.service.get_monitor_feeds(self.config.monitor.feed_count)
        candidates: list[dict[str, Any]] = []
        valid_feeds: list[dict[str, Any]] = []
        for feed in feeds:
            target_qq, feed_id = _text(feed.get("target_qq") or feed.get("uin")), _text(feed.get("tid"))
            if not target_qq or not feed_id:
                continue
            valid_feeds.append(feed)
            candidates.append({"feed": feed.get("content", ""), "target_qq": target_qq})
        if self._uses_default_decision:
            raw_decisions = await self._content_service.generate_feed_decisions(candidates)
            decisions = {
                int(item.get("index", index)): item
                for index, item in enumerate(raw_decisions)
            }
        else:
            decisions = {}
            for index, candidate in enumerate(candidates):
                decisions[index] = await self._decision_generator(candidate)
        for index, feed in enumerate(valid_feeds):
            target_qq = _text(feed.get("target_qq") or feed.get("uin"))
            feed_id = _text(feed.get("tid"))
            decision = decisions.get(index, {})
            if bool(decision.get("like")) and await self.service.like(target_qq, feed_id):
                await self.service.mark_interaction(target_qq, feed_id, ACTION_LIKE)
                sent += 1
            comment = _text(decision.get("comment"))[: max(1, int(self.config.llm.max_reply_chars))]
            if comment and await self.service.comment(target_qq, feed_id, comment):
                await self.service.mark_interaction(target_qq, feed_id, ACTION_COMMENT)
                sent += 1
            await self.service.mark_interaction(target_qq, feed_id, ACTION_READ)
        return sent


class AutonomousScheduler:
    """以任务管理器可接管的协程形式运行三条自治任务。"""

    def __init__(self, engine: AutonomousEngine, config: NeoFoxzoneConfig) -> None:
        """创建调度器。"""
        self.engine = engine
        self.config = config

    def in_dnd(self) -> bool:
        """判断当前本地小时是否处于免打扰区间。"""
        start, end = int(self.config.general.dnd_start) % 24, int(self.config.general.dnd_end) % 24
        hour = datetime.now().hour
        return start != end and (start <= hour < end if start < end else hour >= start or hour < end)

    async def run_loop(self, operation: Callable[[], Awaitable[int]], name: str) -> None:
        """隔离单条自治任务异常并持续运行。"""
        while True:
            if not self.in_dnd():
                try:
                    await operation()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning(f"FoxZone 自治任务 {name} 异常: {error}")
            await asyncio.sleep(max(1.0, float(self.config.general.interval_minutes) * 60.0))


__all__ = ["AutonomousEngine", "AutonomousScheduler"]