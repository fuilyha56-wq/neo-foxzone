"""Neo FoxZone 插件级共享运行时与兼容持久化状态。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

from src.app.plugin_system.api import storage_api

from .polling_state import PollingState

COMPATIBILITY_STORE_NAME = "neo-foxzone"
REPLY_TRACKER_STATE_NAME = "reply_tracker"
INTERACTION_LOG_STATE_NAME = "interaction_log"
VISION_CACHE_STATE_NAME = "vision_cache"
SEND_HISTORY_STATE_NAME = "send_history"

ACTION_LIKE = "liked"
ACTION_COMMENT = "commented"
ACTION_READ = "read"
LIKED_STATE = "liked_state"
SOURCE_BOTH = "both"


def _as_text(value: object) -> str:
    """将未知值收敛为去除首尾空白的字符串。"""
    return str(value).strip() if value is not None else ""


def _interaction_key(target_qq: str, feed_id: str) -> str:
    """构造原版互动记录使用的稳定键。"""
    return f"{_as_text(target_qq)}:{_as_text(feed_id)}"


class ReplyTracker:
    """兼容原版 ``foxzone/reply_tracker`` 形状的已回复评论跟踪器。"""

    def __init__(self) -> None:
        """创建尚未加载的回复跟踪器。"""
        self._data: dict[str, dict[str, float]] = {}
        self._dirty = False

    async def initialize(self) -> None:
        """加载并校验原版兼容的回复跟踪记录。"""
        payload = await storage_api.load_json(
            COMPATIBILITY_STORE_NAME,
            REPLY_TRACKER_STATE_NAME,
        )
        raw_data = payload.get("data") if isinstance(payload, Mapping) else None
        cleaned: dict[str, dict[str, float]] = {}
        if isinstance(raw_data, Mapping):
            for raw_feed_id, raw_comments in raw_data.items():
                feed_id = _as_text(raw_feed_id)
                if not feed_id or not isinstance(raw_comments, Mapping):
                    continue
                comments: dict[str, float] = {}
                for raw_comment_id, raw_timestamp in raw_comments.items():
                    comment_id = _as_text(raw_comment_id)
                    try:
                        timestamp = float(raw_timestamp)
                    except (TypeError, ValueError):
                        continue
                    if comment_id:
                        comments[comment_id] = timestamp
                if comments:
                    cleaned[feed_id] = comments
        self._data = cleaned
        self._dirty = False

    def has_replied(self, feed_id: str, comment_id: str) -> bool:
        """返回指定评论是否已被本插件回复。"""
        return _as_text(comment_id) in self._data.get(_as_text(feed_id), {})

    async def mark_as_replied(self, feed_id: str, comment_id: str) -> None:
        """标记评论已回复并立即写入兼容存储。"""
        normalized_feed_id = _as_text(feed_id)
        normalized_comment_id = _as_text(comment_id)
        if not normalized_feed_id or not normalized_comment_id:
            return
        self._data.setdefault(normalized_feed_id, {})[normalized_comment_id] = time.time()
        self._dirty = True
        await self.save()

    async def save(self) -> None:
        """在状态变更后保存回复跟踪记录。"""
        if not self._dirty:
            return
        await storage_api.save_json(
            COMPATIBILITY_STORE_NAME,
            REPLY_TRACKER_STATE_NAME,
            {
                "data": {
                    feed_id: dict(comments)
                    for feed_id, comments in self._data.items()
                }
            },
        )
        self._dirty = False


class InteractionLog:
    """兼容原版 ``foxzone/interaction_log`` 形状的互动记录。"""

    def __init__(self) -> None:
        """创建尚未加载的互动记录。"""
        self._data: dict[str, dict[str, object]] = {}
        self._dirty = False

    async def initialize(self) -> None:
        """加载可验证的互动记录条目。"""
        payload = await storage_api.load_json(
            COMPATIBILITY_STORE_NAME,
            INTERACTION_LOG_STATE_NAME,
        )
        raw_log = payload.get("log") if isinstance(payload, Mapping) else None
        cleaned: dict[str, dict[str, object]] = {}
        if isinstance(raw_log, Mapping):
            for raw_key, raw_entry in raw_log.items():
                key = _as_text(raw_key)
                if not key or ":" not in key or not isinstance(raw_entry, Mapping):
                    continue
                cleaned[key] = dict(raw_entry)
        self._data = cleaned
        self._dirty = False

    def has_liked(self, target_qq: str, feed_id: str) -> bool:
        """返回 Bot 是否已点赞指定说说。"""
        entry = self._data.get(_interaction_key(target_qq, feed_id), {})
        return bool(entry.get(LIKED_STATE)) or bool(entry.get(ACTION_LIKE))

    def has_commented(self, target_qq: str, feed_id: str) -> bool:
        """返回 Bot 是否已评论指定说说。"""
        return bool(
            self._data.get(_interaction_key(target_qq, feed_id), {}).get(
                ACTION_COMMENT
            )
        )

    def has_interacted(self, target_qq: str, feed_id: str) -> bool:
        """返回 Bot 是否已点赞或评论指定说说。"""
        entry = self._data.get(_interaction_key(target_qq, feed_id), {})
        return bool(entry.get(ACTION_LIKE)) or bool(entry.get(ACTION_COMMENT))

    def has_seen(self, target_qq: str, feed_id: str) -> bool:
        """返回说说是否已被点赞、评论或显式标记为已读。"""
        entry = self._data.get(_interaction_key(target_qq, feed_id), {})
        seen = bool(entry.get(ACTION_LIKE)) or bool(entry.get(ACTION_COMMENT)) or bool(
            entry.get(ACTION_READ)
        )
        if seen and not entry.get(ACTION_READ):
            entry[ACTION_READ] = True
            self._dirty = True
        return seen

    def sync_like_state(self, target_qq: str, feed_id: str, liked: bool) -> None:
        """同步从动态流观察到的真实点赞状态。"""
        key = _interaction_key(target_qq, feed_id)
        if key == ":":
            return
        entry = self._data.get(key)
        if entry is None:
            if not liked:
                return
            entry = {}
            self._data[key] = entry
        current = bool(entry.get(LIKED_STATE))
        if current == bool(liked):
            return
        if liked:
            entry[LIKED_STATE] = True
        else:
            entry.pop(LIKED_STATE, None)
        entry["last_ts"] = time.time()
        self._dirty = True

    def mark(self, target_qq: str, feed_id: str, action: str, source: str) -> None:
        """记录一次点赞、评论或已读互动。"""
        key = _interaction_key(target_qq, feed_id)
        normalized_action = _as_text(action)
        normalized_source = _as_text(source)
        if key == ":" or not normalized_action or not normalized_source:
            return
        entry = self._data.setdefault(key, {})
        entry[normalized_action] = True
        entry["last_ts"] = time.time()
        existing_source = _as_text(entry.get("source"))
        entry["source"] = (
            SOURCE_BOTH
            if existing_source and existing_source != normalized_source
            else normalized_source
        )
        self._dirty = True

    def mark_followup_checked(self, target_qq: str, feed_id: str) -> None:
        """记录指定说说刚刚完成外部评论回查。"""
        entry = self._data.get(_interaction_key(target_qq, feed_id))
        if entry is None:
            return
        entry["last_followup_check"] = time.time()
        self._dirty = True

    def iter_followup_feeds(
        self,
        *,
        exclude_target_qq: str = "",
        limit: int = 0,
        max_feed_age_hours: float = 0.0,
        only_target_qq: str = "",
    ) -> list[tuple[str, str]]:
        """按最久未回查顺序返回已评论的外部说说。"""
        excluded = _as_text(exclude_target_qq)
        only = _as_text(only_target_qq)
        now = time.time()
        max_age_seconds = max(0.0, float(max_feed_age_hours)) * 3600.0
        entries: list[tuple[float, str, str]] = []
        for key, entry in self._data.items():
            if not entry.get(ACTION_COMMENT) or ":" not in key:
                continue
            target_qq, _, feed_id = key.partition(":")
            if not target_qq or not feed_id:
                continue
            if (excluded and target_qq == excluded) or (only and target_qq != only):
                continue
            last_timestamp = entry.get("last_ts", 0.0)
            if max_age_seconds > 0.0 and isinstance(last_timestamp, (int, float)):
                if float(last_timestamp) > 0.0 and now - float(last_timestamp) > max_age_seconds:
                    continue
            last_checked = entry.get("last_followup_check", 0.0)
            priority = float(last_checked) if isinstance(last_checked, (int, float)) else 0.0
            entries.append((priority, target_qq, feed_id))
        entries.sort(key=lambda item: item[0])
        if limit > 0:
            entries = entries[:limit]
        return [(target_qq, feed_id) for _, target_qq, feed_id in entries]

    def get_external_reply_count(self, target_qq: str, feed_id: str) -> int:
        """返回指定说说下已发送的外部接力回复数量。"""
        raw_value = self._data.get(_interaction_key(target_qq, feed_id), {}).get(
            "external_reply_count",
            0,
        )
        return int(raw_value) if isinstance(raw_value, (int, float)) else 0

    def increment_external_reply_count(self, target_qq: str, feed_id: str) -> int:
        """递增并返回指定说说的外部接力回复数量。"""
        key = _interaction_key(target_qq, feed_id)
        if key == ":":
            return 0
        entry = self._data.setdefault(key, {})
        count = self.get_external_reply_count(target_qq, feed_id) + 1
        entry["external_reply_count"] = count
        self._dirty = True
        return count

    async def save(self) -> None:
        """在状态变更后保存原版兼容互动记录。"""
        if not self._dirty:
            return
        await storage_api.save_json(
            COMPATIBILITY_STORE_NAME,
            INTERACTION_LOG_STATE_NAME,
            {"log": {key: dict(entry) for key, entry in self._data.items()}},
        )
        self._dirty = False


class VisionCache:
    """兼容原版 ``foxzone/vision_cache`` 形状的图片描述缓存。"""

    def __init__(self) -> None:
        """创建尚未加载的视觉缓存。"""
        self._data: dict[str, str] = {}
        self._dirty = False

    async def initialize(self) -> None:
        """加载可用的 URL 到描述映射。"""
        payload = await storage_api.load_json(
            COMPATIBILITY_STORE_NAME,
            VISION_CACHE_STATE_NAME,
        )
        raw_cache = payload.get("cache") if isinstance(payload, Mapping) else None
        self._data = (
            {
                _as_text(url): _as_text(description)
                for url, description in raw_cache.items()
                if _as_text(url) and _as_text(description)
            }
            if isinstance(raw_cache, Mapping)
            else {}
        )
        self._dirty = False

    def get(self, url: str) -> str | None:
        """获取指定图片 URL 的缓存描述。"""
        return self._data.get(_as_text(url))

    def set(self, url: str, description: str) -> None:
        """写入非空的图片描述缓存。"""
        normalized_url = _as_text(url)
        normalized_description = _as_text(description)
        if not normalized_url or not normalized_description:
            return
        self._data[normalized_url] = normalized_description
        self._dirty = True

    async def save(self) -> None:
        """在状态变更后保存视觉缓存。"""
        if not self._dirty:
            return
        await storage_api.save_json(
            COMPATIBILITY_STORE_NAME,
            VISION_CACHE_STATE_NAME,
            {"cache": dict(self._data)},
        )
        self._dirty = False


class SendHistory:
    """兼容原版 ``foxzone/send_history`` 形状的最近发布记录。"""

    def __init__(self, maximum_records: int = 20) -> None:
        """创建最近发布记录容器。"""
        self._maximum_records = max(1, int(maximum_records))
        self._records: list[dict[str, str]] = []
        self._dirty = False

    async def initialize(self) -> None:
        """加载并裁剪已有发布记录。"""
        payload = await storage_api.load_json(
            COMPATIBILITY_STORE_NAME,
            SEND_HISTORY_STATE_NAME,
        )
        raw_records = payload.get("records") if isinstance(payload, Mapping) else None
        records: list[dict[str, str]] = []
        if isinstance(raw_records, list):
            for raw_record in raw_records:
                if not isinstance(raw_record, Mapping):
                    continue
                text = _as_text(raw_record.get("text"))
                if not text:
                    continue
                records.append(
                    {"time": _as_text(raw_record.get("time")), "text": text}
                )
        self._records = records[-self._maximum_records :]
        self._dirty = False

    async def record(self, text: str) -> None:
        """追加一条成功发布的说说正文并立即保存。"""
        normalized_text = _as_text(text)
        if not normalized_text:
            return
        self._records.append(
            {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "text": normalized_text}
        )
        self._records = self._records[-self._maximum_records :]
        self._dirty = True
        await self.save()

    async def save(self) -> None:
        """在状态变更后保存发布历史。"""
        if not self._dirty:
            return
        await storage_api.save_json(
            COMPATIBILITY_STORE_NAME,
            SEND_HISTORY_STATE_NAME,
            {"records": [dict(record) for record in self._records]},
        )
        self._dirty = False


class NeoFoxzoneRuntime:
    """由插件持有的唯一共享状态与发送串行锁。"""

    def __init__(self, *, polling_state_max_entries: int = 2000) -> None:
        """创建运行时，不执行任何存储或网络 I/O。"""
        self._polling_state_max_entries = max(1, int(polling_state_max_entries))
        self.polling_state = PollingState(
            max_entries=self._polling_state_max_entries
        )
        self.reply_tracker = ReplyTracker()
        self.interaction_log = InteractionLog()
        self.vision_cache = VisionCache()
        self.send_history = SendHistory()
        self.reply_send_lock = asyncio.Lock()
        self._initialize_lock = asyncio.Lock()
        self._initialized = False

    @property
    def initialized(self) -> bool:
        """返回兼容状态是否已经从存储加载。"""
        return self._initialized

    async def initialize(self) -> None:
        """幂等加载当前轮询状态及原版兼容持久化状态。"""
        async with self._initialize_lock:
            if self._initialized:
                return
            self.polling_state = await PollingState.load(
                max_entries=self._polling_state_max_entries
            )
            await self.reply_tracker.initialize()
            await self.interaction_log.initialize()
            await self.vision_cache.initialize()
            await self.send_history.initialize()
            self._initialized = True

    async def shutdown(self) -> None:
        """保存所有共享状态，供插件卸载或重载前调用。"""
        if not self._initialized:
            return
        await self.polling_state.save()
        await self.reply_tracker.save()
        await self.interaction_log.save()
        await self.vision_cache.save()
        await self.send_history.save()
        self._initialized = False


__all__ = [
    "ACTION_COMMENT",
    "ACTION_LIKE",
    "ACTION_READ",
    "COMPATIBILITY_STORE_NAME",
    "InteractionLog",
    "NeoFoxzoneRuntime",
    "ReplyTracker",
    "SendHistory",
    "VisionCache",
]