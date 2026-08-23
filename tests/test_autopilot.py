"""Tests for Neo FoxZone autonomous interaction flows."""

from __future__ import annotations

import importlib
from typing import Any
from uuid import uuid4

import pytest

PACKAGE = "plugins.neo-foxzone"
engine_module = importlib.import_module(f"{PACKAGE}.autopilot.engine")
config_module = importlib.import_module(f"{PACKAGE}.config")
runtime_module = importlib.import_module(f"{PACKAGE}.runtime")
AutonomousEngine = engine_module.AutonomousEngine
AutonomousScheduler = engine_module.AutonomousScheduler
NeoFoxzoneConfig = config_module.NeoFoxzoneConfig
NeoFoxzoneRuntime = runtime_module.NeoFoxzoneRuntime


class FakeAutonomousService:
    """In-memory FoxZone Service double for autonomous flow tests."""

    def __init__(self) -> None:
        """Create deterministic feeds and an action log."""
        self.actions: list[tuple[Any, ...]] = []
        self.external_feed_id = f"autopilot-test-{uuid4().hex}"
        self.own_feeds = [
            {
                "tid": "own-1",
                "content": "A post",
                "comments": [
                    {
                        "comment_tid": "comment-1",
                        "qq_account": "200",
                        "nickname": "friend",
                        "content": "Nice post",
                    }
                ],
            }
        ]
        self.external_detail = {
            "tid": self.external_feed_id,
            "content": "An external post",
            "comments": [
                {
                    "comment_tid": "bot-root",
                    "qq_account": "100",
                    "nickname": "bot",
                    "content": "Bot comment",
                },
                {
                    "comment_tid": "reply-1",
                    "parent_tid": "bot-root",
                    "qq_account": "200",
                    "nickname": "friend",
                    "content": "Reply to bot",
                },
            ],
        }
        self.monitor_feeds = [
            {"tid": "friend-1", "target_qq": "200", "content": "Friend post"}
        ]

    async def list_own_feeds_with_comments(self, num: int = 5) -> list[dict[str, Any]]:
        """Return own test feeds."""
        return self.own_feeds[:num]

    async def get_monitor_feeds(self, num: int = 10) -> list[dict[str, Any]]:
        """Return monitor test feeds."""
        return self.monitor_feeds[:num]

    async def get_feed_detail(self, host_qq: str, feed_id: str) -> dict[str, Any] | None:
        """Return the external detail fixture."""
        if host_qq == "200" and feed_id == self.external_feed_id:
            return self.external_detail
        return None

    async def reply_comment(
        self,
        feed_id: str,
        host_qq: str,
        target_name: str,
        reply_text: str,
        comment_tid: str,
        commenter_qq: str = "",
    ) -> bool:
        """Record a nested reply."""
        self.actions.append(("reply", feed_id, host_qq, comment_tid, commenter_qq, reply_text))
        return True

    async def comment(self, target_qq: str, feed_id: str, text: str) -> bool:
        """Record a top-level comment."""
        self.actions.append(("comment", target_qq, feed_id, text))
        return True

    async def like(self, target_qq: str, feed_id: str) -> bool:
        """Record a like."""
        self.actions.append(("like", target_qq, feed_id))
        return True

    async def mark_comment_replied(self, feed_id: str, comment_tid: str) -> None:
        """Record reply deduplication."""
        self.actions.append(("mark_reply", feed_id, comment_tid))

    async def has_replied_comment(self, feed_id: str, comment_tid: str) -> bool:
        """Return whether this fixture already received a reply."""
        return ("mark_reply", feed_id, comment_tid) in self.actions

    async def mark_interaction(
        self,
        target_qq: str,
        feed_id: str,
        action: str,
        source: str = "agent",
    ) -> None:
        """Record an interaction state transition."""
        self.actions.append(("mark", target_qq, feed_id, action, source))

    async def iter_followup_feeds(
        self,
        exclude_qq: str = "",
        limit: int = 0,
        max_feed_age_hours: float = 0.0,
        only_target_qq: str = "",
    ) -> list[tuple[str, str]]:
        """Return one external feed fixture."""
        del exclude_qq, limit, max_feed_age_hours, only_target_qq
        return [("200", self.external_feed_id)]

    async def mark_followup_checked(self, target_qq: str, feed_id: str) -> None:
        """Record external follow-up completion."""
        self.actions.append(("checked", target_qq, feed_id))

    async def self_qq(self) -> str:
        """Return the fixture bot QQ."""
        return "100"


@pytest.mark.asyncio
async def test_autonomous_engine_covers_three_flows() -> None:
    """Run all flows and verify action contracts and external root selection."""
    runtime = NeoFoxzoneRuntime()
    await runtime.initialize()
    service = FakeAutonomousService()
    config = NeoFoxzoneConfig()
    config.monitor.enabled = True
    engine = AutonomousEngine(
        service,
        runtime,
        config,
        decision_generator=lambda context: _decision(context),
    )

    assert await engine.run_self_comments() == 1
    assert await engine.run_external_followups() == 1
    assert await engine.run_friend_monitor() == 2
    assert (
        "reply",
        service.external_feed_id,
        "200",
        "bot-root",
        "200",
        "reply",
    ) in service.actions
    assert ("like", "200", "friend-1") in service.actions
    assert ("comment", "200", "friend-1", "comment") in service.actions
    assert any(action[3] == "read" for action in service.actions if action[0] == "mark")
    await runtime.shutdown()


async def _decision(context: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic decisions for every test context."""
    if "target_qq" in context:
        return {"like": True, "comment": "comment"}
    return {"reply": "reply"}


@pytest.mark.asyncio
async def test_external_followups_respect_reply_limit() -> None:
    """Do not send another external reply after the configured limit."""
    runtime = NeoFoxzoneRuntime()
    await runtime.initialize()
    service = FakeAutonomousService()
    config = NeoFoxzoneConfig()
    config.monitor.max_external_replies = 0
    engine = AutonomousEngine(
        service,
        runtime,
        config,
        decision_generator=lambda context: _decision(context),
    )

    assert await engine.run_external_followups() == 0
    assert not any(action[0] == "reply" for action in service.actions)
    await runtime.shutdown()


def test_scheduler_dnd_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Support both normal and overnight DND windows."""
    config = NeoFoxzoneConfig()
    config.general.dnd_start = 22
    config.general.dnd_end = 7
    scheduler = AutonomousScheduler(None, config)  # type: ignore[arg-type]
    monkeypatch.setattr("plugins.neo-foxzone.autopilot.engine.datetime", _FixedDateTime)

    assert scheduler.in_dnd() is True


class _FixedDateTime:
    """Fixed clock used by the DND test."""

    @classmethod
    def now(cls) -> Any:
        """Return a time inside the overnight DND interval."""
        return type("FixedNow", (), {"hour": 23})()
