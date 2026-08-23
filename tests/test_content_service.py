"""Tests for the FoxZone LLM content service contracts."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

PACKAGE = "plugins.neo-foxzone"
content_module = importlib.import_module(f"{PACKAGE}.core.llm.content_service")
config_module = importlib.import_module(f"{PACKAGE}.config")
ContentService = content_module.ContentService
NeoFoxzoneConfig = config_module.NeoFoxzoneConfig


class _FakeResponse:
    """Awaitable response returned by the fake LLM request."""

    def __init__(self, value: str) -> None:
        """Store the response text."""
        self.value = value

    def __await__(self):
        """Return the configured response text."""
        async def _value() -> str:
            return self.value

        return _value().__await__()


class _FakeRequest:
    """Minimal request double capturing payloads."""

    def __init__(self, response: str) -> None:
        """Create a request double."""
        self.response = response
        self.payloads: list[Any] = []

    def add_payload(self, payload: Any) -> None:
        """Capture a payload."""
        self.payloads.append(payload)

    async def send(self, stream: bool = False) -> _FakeResponse:
        """Return the configured non-stream response."""
        assert stream is False
        return _FakeResponse(self.response)


@pytest.mark.asyncio
async def test_content_service_normalizes_batch_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normalize omitted indexes and cap generated reply text."""
    request = _FakeRequest('[{"reply": "hello"}, {"index": 4, "reply": "world"}]')
    monkeypatch.setattr(content_module.llm_api, "get_model_set_by_task", lambda name: object())
    monkeypatch.setattr(
        content_module.llm_api,
        "create_llm_request",
        lambda **kwargs: request,
    )
    config = NeoFoxzoneConfig()
    service = ContentService(config)

    result = await service.generate_batch_replies([{"content": "one"}, {"content": "two"}])

    assert result == [{"index": 0, "reply": "hello"}, {"index": 4, "reply": "world"}]
    assert len(request.payloads) == 2


@pytest.mark.asyncio
async def test_content_service_invalid_decision_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject malformed model JSON without raising into the scheduler."""
    request = _FakeRequest("not-json")
    monkeypatch.setattr(content_module.llm_api, "get_model_set_by_task", lambda name: object())
    monkeypatch.setattr(
        content_module.llm_api,
        "create_llm_request",
        lambda **kwargs: request,
    )
    service = ContentService(NeoFoxzoneConfig())

    assert await service.generate_feed_decisions([{"content": "one"}]) == []
