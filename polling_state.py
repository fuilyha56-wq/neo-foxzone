"""Neo FoxZone 自动回复轮询的持久状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.app.plugin_system.api import storage_api

STORE_NAME = "neo-foxzone"
STATE_NAME = "polling_state"
STATE_VERSION = 2


def _string_list(value: Any) -> list[str]:
    """把未知 JSON 值收敛为有序非空字符串列表。"""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        normalized = str(item).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _string_float_map(value: Any) -> dict[str, float]:
    """把未知 JSON 值收敛为字符串到非负浮点数的映射。"""
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        try:
            normalized = float(raw_value)
        except (TypeError, ValueError):
            continue
        if key and normalized >= 0:
            result[key] = normalized
    return result


def _string_int_map(value: Any) -> dict[str, int]:
    """把未知 JSON 值收敛为字符串到正整数的映射。"""
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        try:
            normalized = int(raw_value)
        except (TypeError, ValueError):
            continue
        if key and normalized > 0:
            result[key] = normalized
    return result


@dataclass(slots=True)
class PollingState:
    """保存已处理评论与 Bot 自己发出的评论引用。"""

    max_entries: int = 2000
    processed_comment_ids: list[str] = field(default_factory=list)
    in_flight_comment_ids: list[str] = field(default_factory=list)
    bot_comments_by_post: dict[str, list[str]] = field(default_factory=dict)
    retry_after_by_identity: dict[str, float] = field(default_factory=dict)
    failure_counts_by_identity: dict[str, int] = field(default_factory=dict)
    last_attempted_identity: str = ""

    @classmethod
    async def load(cls, max_entries: int = 2000) -> "PollingState":
        """从插件隔离 JSON 存储加载状态。"""
        payload = await storage_api.load_json(STORE_NAME, STATE_NAME)
        state = cls(max_entries=max(1, int(max_entries)))
        if not isinstance(payload, dict):
            return state
        state.processed_comment_ids = _string_list(
            payload.get("processed_comment_ids")
        )
        state.in_flight_comment_ids = _string_list(
            payload.get("in_flight_comment_ids")
        )
        raw_comments = payload.get("bot_comments_by_post")
        if isinstance(raw_comments, dict):
            state.bot_comments_by_post = {
                str(post_key): _string_list(comment_ids)
                for post_key, comment_ids in raw_comments.items()
                if str(post_key).strip()
            }
        state.retry_after_by_identity = _string_float_map(
            payload.get("retry_after_by_identity")
        )
        state.failure_counts_by_identity = _string_int_map(
            payload.get("failure_counts_by_identity")
        )
        state.last_attempted_identity = str(
            payload.get("last_attempted_identity") or ""
        ).strip()
        state._trim()
        return state

    @staticmethod
    def post_key(post_id: str, owner_uin: int | None) -> str:
        """构造说说所有者与 ID 的稳定联合键。"""
        return f"{int(owner_uin or 0)}:{str(post_id).strip()}"

    def is_processed(self, identity: str) -> bool:
        """判断评论身份是否已经成功处理。"""
        return str(identity).strip() in self.processed_comment_ids

    def is_in_flight(self, identity: str) -> bool:
        """判断评论是否已在远端写入前持久占用。"""
        return str(identity).strip() in self.in_flight_comment_ids

    def reserve(self, identity: str) -> None:
        """在远端写入前占用评论，防止重启后重复发送。"""
        normalized = str(identity).strip()
        if not normalized:
            return
        if normalized in self.in_flight_comment_ids:
            self.in_flight_comment_ids.remove(normalized)
        self.in_flight_comment_ids.append(normalized)
        self._trim()

    def release(self, identity: str) -> None:
        """在确认远端未成功时释放评论占用。"""
        normalized = str(identity).strip()
        if normalized in self.in_flight_comment_ids:
            self.in_flight_comment_ids.remove(normalized)

    def mark_processed(self, identity: str) -> None:
        """把评论标记为已成功处理，并保持最近使用顺序。"""
        normalized = str(identity).strip()
        if not normalized:
            return
        if normalized in self.processed_comment_ids:
            self.processed_comment_ids.remove(normalized)
        self.processed_comment_ids.append(normalized)
        self.release(normalized)
        self.clear_failure(normalized)
        self._trim()

    def record_failure(self, identity: str, *, retry_after: float) -> None:
        """记录明确失败及下一次允许重试的时间。"""
        normalized = str(identity).strip()
        if not normalized:
            return
        count = self.failure_counts_by_identity.pop(normalized, 0) + 1
        self.failure_counts_by_identity[normalized] = count
        self.retry_after_by_identity.pop(normalized, None)
        self.retry_after_by_identity[normalized] = max(0.0, float(retry_after))
        self._trim()

    def clear_failure(self, identity: str) -> None:
        """清除评论的失败计数与退避时间。"""
        normalized = str(identity).strip()
        self.failure_counts_by_identity.pop(normalized, None)
        self.retry_after_by_identity.pop(normalized, None)

    def retry_after(self, identity: str) -> float:
        """返回评论下一次允许重试的 Unix 时间戳。"""
        return self.retry_after_by_identity.get(str(identity).strip(), 0.0)

    def failure_count(self, identity: str) -> int:
        """返回评论已记录的明确失败次数。"""
        return self.failure_counts_by_identity.get(str(identity).strip(), 0)

    def remember_bot_comment(
        self,
        *,
        post_id: str,
        owner_uin: int | None,
        comment_id: str,
    ) -> None:
        """记录 Bot 在一条说说下成功发出的评论 ID。"""
        normalized_comment_id = str(comment_id).strip()
        if not normalized_comment_id:
            return
        key = self.post_key(post_id, owner_uin)
        comments = self.bot_comments_by_post.setdefault(key, [])
        if normalized_comment_id in comments:
            comments.remove(normalized_comment_id)
        comments.append(normalized_comment_id)
        self._trim()

    def known_bot_comment_ids(
        self,
        post_id: str,
        owner_uin: int | None,
    ) -> set[str]:
        """返回指定说说下 Neo FoxZone 已发出的评论 ID。"""
        key = self.post_key(post_id, owner_uin)
        return set(self.bot_comments_by_post.get(key, []))

    def _trim(self) -> None:
        """限制持久记录数量，优先保留最近项目。"""
        maximum = max(1, int(self.max_entries))
        if len(self.processed_comment_ids) > maximum:
            self.processed_comment_ids = self.processed_comment_ids[-maximum:]
        if len(self.in_flight_comment_ids) > maximum:
            self.in_flight_comment_ids = self.in_flight_comment_ids[-maximum:]
        if len(self.retry_after_by_identity) > maximum:
            self.retry_after_by_identity = dict(
                list(self.retry_after_by_identity.items())[-maximum:]
            )
        if len(self.failure_counts_by_identity) > maximum:
            self.failure_counts_by_identity = dict(
                list(self.failure_counts_by_identity.items())[-maximum:]
            )

        flattened: list[tuple[str, str]] = [
            (post_key, comment_id)
            for post_key, comment_ids in self.bot_comments_by_post.items()
            for comment_id in comment_ids
        ]
        if len(flattened) <= maximum:
            return
        keep = set(flattened[-maximum:])
        self.bot_comments_by_post = {
            post_key: [
                comment_id
                for comment_id in comment_ids
                if (post_key, comment_id) in keep
            ]
            for post_key, comment_ids in self.bot_comments_by_post.items()
        }
        self.bot_comments_by_post = {
            key: values
            for key, values in self.bot_comments_by_post.items()
            if values
        }

    async def save(self) -> None:
        """把当前状态持久化到插件隔离 JSON 存储。"""
        self._trim()
        await storage_api.save_json(
            STORE_NAME,
            STATE_NAME,
            {
                "version": STATE_VERSION,
                "processed_comment_ids": list(self.processed_comment_ids),
                "in_flight_comment_ids": list(self.in_flight_comment_ids),
                "bot_comments_by_post": {
                    key: list(values)
                    for key, values in self.bot_comments_by_post.items()
                },
                "retry_after_by_identity": dict(self.retry_after_by_identity),
                "failure_counts_by_identity": dict(
                    self.failure_counts_by_identity
                ),
                "last_attempted_identity": self.last_attempted_identity,
            },
        )


__all__ = ["PollingState", "STATE_NAME", "STORE_NAME"]