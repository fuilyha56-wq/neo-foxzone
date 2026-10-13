"""Tests for the FoxZone LLM content service contracts."""

from __future__ import annotations

import importlib
import json
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
    """Keep explicit valid indexes; no guessed association with input candidates."""
    request = _FakeRequest('[{"index": 0, "reply": "hello"}, {"index": 1, "reply": "world"}]')
    monkeypatch.setattr(content_module.llm_api, "get_model_set_by_task", lambda name: object())
    monkeypatch.setattr(
        content_module.llm_api,
        "create_llm_request",
        lambda **kwargs: request,
    )
    config = NeoFoxzoneConfig()
    service = ContentService(config)

    result = await service.generate_batch_replies([{"content": "one"}, {"content": "two"}])

    assert result == [{"index": 0, "reply": "hello"}, {"index": 1, "reply": "world"}]
    assert len(request.payloads) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ['[{"reply":"x"}]', '[{"index":2,"reply":"x"}]',
                                     '[{"index":0,"reply":"x"},{"index":0,"reply":"y"}]'])
async def test_decisions_reject_missing_out_of_range_or_duplicate_indexes(monkeypatch, response):
    service = ContentService(NeoFoxzoneConfig())

    async def request(*args, **kwargs):
        return response

    monkeypatch.setattr(service, "_request", request)
    assert await service.generate_batch_replies([{"content": "one"}]) == []


@pytest.mark.asyncio
async def test_multimodal_batches_bound_images_and_remap_global_indexes(monkeypatch):
    service = ContentService(NeoFoxzoneConfig())
    counts = []

    async def request(prompt, payload, **kwargs):
        counts.append(len(kwargs["images"]))
        return json.dumps([{"index": value["index"], "reply": value["content"]} for value in payload])

    monkeypatch.setattr(service, "_request", request)
    items = [{"content": str(index), "_image_contents": ["base64://AA=="] * 3} for index in range(4)]
    assert await service.generate_batch_replies(items) == [{"index": index, "reply": str(index)} for index in range(4)]
    assert counts == [9, 3]


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


@pytest.mark.asyncio
async def test_story_decision_accepts_only_bounded_image_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured image decisions keep bounded text and a known style."""
    request = _FakeRequest(
        '{"content":"hello","generate_image":true,'
        '"image_description":"forest","image_style":"photo"}'
    )
    monkeypatch.setattr(content_module.llm_api, "get_model_set_by_task", lambda name: object())
    monkeypatch.setattr(
        content_module.llm_api,
        "create_llm_request",
        lambda **kwargs: request,
    )
    service = ContentService(NeoFoxzoneConfig())

    result = await service.generate_story_decision("topic")

    assert result == {
        "content": "hello",
        "generate_image": True,
        "image_description": "forest",
        "image_style": "photo",
    }


@pytest.mark.asyncio
async def test_story_decision_parse_failure_cancels_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed model output must not publish the input topic as fake generation."""
    request = _FakeRequest("not-json")
    monkeypatch.setattr(content_module.llm_api, "get_model_set_by_task", lambda name: object())
    monkeypatch.setattr(
        content_module.llm_api,
        "create_llm_request",
        lambda **kwargs: request,
    )
    service = ContentService(NeoFoxzoneConfig())

    with pytest.raises(ValueError, match="JSON"):
        await service.generate_story_decision("safe topic")


@pytest.mark.asyncio
async def test_story_generation_failure_does_not_echo_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider failure remains a failure rather than authorizing a post."""
    service = ContentService(NeoFoxzoneConfig())

    async def failed_request(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(service, "_request", failed_request)
    with pytest.raises(RuntimeError, match="429"):
        await service.generate_story("must not publish this topic")
