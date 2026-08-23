"""Neo FoxZone 的 LLM 内容生成、批量回复和互动决策服务。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from src.app.plugin_system.api import llm_api
from src.app.plugin_system.types import LLMPayload, ROLE, Text

from ...config import NeoFoxzoneConfig


class ContentService:
    """封装 FoxZone 所有自治内容请求，保持调用方与 LLM 协议解耦。"""

    def __init__(self, config: NeoFoxzoneConfig) -> None:
        """创建无状态内容服务。"""
        self.config = config

    async def _request(self, system_prompt: str, user_payload: Any) -> str:
        """发送一次非流式请求并提取文本结果。"""
        model_set = llm_api.get_model_set_by_task(self.config.llm.model_task.strip())
        request = llm_api.create_llm_request(
            model_set=model_set,
            request_name="neo_foxzone_content",
        )
        request.add_payload(LLMPayload(ROLE.SYSTEM, Text(system_prompt)))
        request.add_payload(
            LLMPayload(
                ROLE.USER,
                Text(json.dumps(user_payload, ensure_ascii=False)),
            )
        )
        response = await request.send(stream=False)
        return str((await response) or "").strip()

    async def generate_story(self, topic: str = "") -> str:
        """生成一条适合 QQ 空间的说说正文。"""
        prompt = (
            "请写一条自然、口语化、适合发布到 QQ 空间的中文说说。"
            "只输出正文，不要引号、标题、解释或 Markdown，长度不超过 30 字。"
        )
        payload = {"topic": str(topic).strip() or "自由发挥", "recent_posts": ""}
        try:
            text = await self._request(prompt, payload)
        except Exception:
            return str(topic).strip() or ""
        return text[: max(1, int(self.config.llm.max_reply_chars))].strip()

    async def generate_batch_replies(
        self,
        candidates: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """批量生成评论回复，结果保留候选索引和回复正文。"""
        items = [dict(item) for item in candidates]
        if not items:
            return []
        prompt = (
            "你负责为 QQ 空间评论生成回复。对每个候选返回 JSON 数组，"
            "每项必须包含 index 和 reply；不适合回复时 reply 为空字符串。"
            "只输出 JSON，不要解释。"
        )
        try:
            raw = await self._request(prompt, items)
            parsed = json.loads(raw)
        except (Exception, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        results: list[dict[str, Any]] = []
        for fallback_index, item in enumerate(parsed):
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", fallback_index))
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "index": index,
                    "reply": str(item.get("reply") or "").strip()
                    [: max(1, int(self.config.llm.max_reply_chars))],
                }
            )
        return results

    async def generate_feed_decisions(
        self,
        feeds: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """批量生成好友动态点赞、评论和楼中楼决策。"""
        items = [dict(item) for item in feeds]
        if not items:
            return []
        prompt = (
            "你负责决定 QQ 空间好友动态互动。返回 JSON 数组，每项包含 index、"
            "like(bool)、comment(string)、reply_to_qq(string)、reply_to(string)。"
            "不想互动时 like=false 且 comment 为空。只输出 JSON。"
        )
        try:
            raw = await self._request(prompt, items)
            parsed = json.loads(raw)
        except (Exception, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        results: list[dict[str, Any]] = []
        for fallback_index, item in enumerate(parsed):
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", fallback_index))
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "index": index,
                    "like": bool(item.get("like")),
                    "comment": str(item.get("comment") or "").strip()
                    [: max(1, int(self.config.llm.max_reply_chars))],
                    "reply_to_qq": str(item.get("reply_to_qq") or "").strip(),
                    "reply_to": str(item.get("reply_to") or "").strip(),
                }
            )
        return results

    async def get_recent_self_feeds_block(
        self,
        feeds: Iterable[dict[str, Any]],
    ) -> str:
        """把近期自身说说压缩为可注入 Prompt 的上下文块。"""
        lines = []
        for feed in feeds:
            content = str(feed.get("content") or "").strip()
            created_time = str(feed.get("created_time") or "").strip()
            if content:
                lines.append(f"- {created_time}: {content}" if created_time else f"- {content}")
        return "\n".join(lines)


__all__ = ["ContentService"]
