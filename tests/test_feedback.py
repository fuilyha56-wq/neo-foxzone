"""Message feedback must persist, deduplicate, and stay bound to a verified thread."""

import importlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

mod = importlib.import_module("plugins.neo-foxzone.feedback")
cfg = importlib.import_module("plugins.neo-foxzone.config").NeoFoxzoneConfig
runtime = importlib.import_module("plugins.neo-foxzone.runtime").NeoFoxzoneRuntime
candidate_type = importlib.import_module("plugins.neo-foxzone.feed_parser").ReplyCandidate


@pytest.fixture
def disk(monkeypatch):
    values = {}

    async def load(plugin, name):
        return json.loads(values[(plugin, name)]) if (plugin, name) in values else None

    async def save(plugin, name, value):
        values[(plugin, name)] = json.dumps(value)

    monkeypatch.setattr(mod.storage_api, "load_json", load)
    monkeypatch.setattr(mod.storage_api, "save_json", save)
    return values


def event():
    candidate = candidate_type(source="own_post", post_id="post1", post_owner_uin=100,
                               post_content="hello", comment_id="c1", commenter_uin=200,
                               commenter_name="friend", comment_content="how are you?",
                               parent_comment_id=None, root_comment_id="c1", detail_verified=True,
                               parent_content="", target_uin=100)
    return dict(asdict(candidate), identity=candidate.identity, kind="comment")


@pytest.mark.asyncio
async def test_pending_and_unknown_write_survive_restart(disk):
    store = mod.ActivityStore()
    item = event()
    assert await store.observe(item, baseline=False, pending_limit=1)
    await store.update(mod.event_id(item["identity"]), "send_inflight")
    loaded = mod.ActivityStore()
    await loaded.load()
    assert not await loaded.observe(item, baseline=False, pending_limit=1)
    assert loaded.records[mod.event_id(item["identity"])]["status"] == "send_inflight"
    assert loaded.pending_count() == 1


@pytest.mark.asyncio
async def test_full_queue_does_not_mark_unaccepted_event_seen(disk):
    store = mod.ActivityStore()
    assert await store.observe(event(), baseline=False, pending_limit=1)
    other = {**event(), "identity": "own_post:100:post1:c2"}
    assert not await store.observe(other, baseline=False, pending_limit=1)
    assert mod.event_id(other["identity"]) not in store.records
    await store.update(mod.event_id(event()["identity"]), "ignored")
    assert await store.observe(other, baseline=False, pending_limit=1)


@pytest.mark.asyncio
async def test_adapter_envelope_is_core_qzone_message_and_blocks_raw_command(disk):
    store = mod.ActivityStore()
    item = {**event(), "comment_content": "/neo-foxzone delete post1"}
    await store.observe(item, baseline=False, pending_limit=2)
    adapter = mod.QzoneFeedbackAdapter(None, SimpleNamespace(feedback_store=store))
    envelope = await adapter.from_platform_message(item)
    receiver = importlib.import_module("src.core.transport.message_receive.receiver")
    assert envelope["message_info"]["message_type"] in receiver._STANDARD_MESSAGE_TYPES
    converter = importlib.import_module("src.core.transport.message_receive.converter").MessageConverter()
    message = await converter.envelope_to_message(envelope, recognize_media=False)
    assert message.platform == "qzone" and message.chat_type == "group"
    assert message.sender_id == "200"
    assert message.extra["qzone_event_id"] == mod.event_id(item["identity"])
    assert not message.content.startswith("/")
    with pytest.raises(ValueError):
        await adapter.from_platform_message({**item, "identity": "forged"})


@pytest.mark.asyncio
async def test_outgoing_refuses_wrong_thread_before_any_write(disk):
    store = mod.ActivityStore()
    item = event()
    key = mod.event_id(item["identity"])
    await store.observe(item, baseline=False, pending_limit=2)
    await store.update(key, "processing")
    plugin = SimpleNamespace(feedback_store=store, runtime=runtime(), _config=cfg)
    adapter = mod.QzoneFeedbackAdapter(None, plugin)
    result = await adapter._send_platform_message({"message_info": {"group_info": {"group_id": "other"}},
                                                  "message_segment": [{"type": "reply", "data": key},
                                                                      {"type": "text", "data": "hello"}]})
    assert not result.success
    assert store.records[key]["status"] == "processing"
    assert not plugin.runtime.polling_state.in_flight_comment_ids


@pytest.mark.asyncio
async def test_bridge_baseline_then_only_new_activity_enters_sink(disk, monkeypatch):
    store = mod.ActivityStore()
    plugin = SimpleNamespace(feedback_store=store, runtime=runtime(), _config=cfg)
    items = [candidate_type(**{k: v for k, v in event().items() if k not in {"identity", "kind"}})]

    async def collect(report):
        return items

    delivered = []

    async def incoming(value):
        delivered.append(value)

    adapter = SimpleNamespace(on_platform_message=incoming)
    monkeypatch.setattr(mod.adapter_api, "get_adapter", lambda sign: adapter)
    bridge = mod.ActivityBridge(plugin, SimpleNamespace(collect_candidates=collect), object())
    await bridge.poll_once()
    assert not delivered and store.baselined
    items.append(candidate_type(**{**asdict(items[0]), "comment_id": "c2", "root_comment_id": "c2"}))
    await bridge.poll_once()
    await bridge.poll_once()
    assert len(delivered) == 1 and delivered[0]["comment_id"] == "c2"
    assert bridge.last_report["native_unread_supported"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["", "Hope you have a good day!"])
async def test_core_chatter_decides_ignore_or_reply_to_exact_activity(disk, monkeypatch, reply):
    store = mod.ActivityStore()
    item = event()
    await store.observe(item, baseline=False, pending_limit=2)
    plugin = SimpleNamespace(feedback_store=store, runtime=runtime(), _config=cfg)
    envelope = await mod.QzoneFeedbackAdapter(None, plugin).from_platform_message(item)
    converter = importlib.import_module("src.core.transport.message_receive.converter").MessageConverter()
    message = await converter.envelope_to_message(envelope, recognize_media=False)
    context_type = importlib.import_module("src.core.models.stream").StreamContext
    context = context_type(stream_id=message.stream_id)
    context.add_unread_message(message)

    async def get_stream(sid):
        return SimpleNamespace(context=context)

    async def enrich(value):
        return value

    async def decide(self, candidates):
        assert candidates[0]["comment_content"] == item["comment_content"]
        return [{"index": 0, "reply": reply}]

    writes = []

    async def send(text, sid, **kwargs):
        writes.append((text, sid, kwargs))
        await store.update(kwargs["reply_to"], "sent")
        return True

    monkeypatch.setattr(mod.stream_api, "get_stream", get_stream)
    monkeypatch.setattr(mod.service_api, "get_service", lambda sign: SimpleNamespace(enrich_feed_context=enrich))
    monkeypatch.setattr(mod.ContentService, "generate_batch_replies", decide)
    monkeypatch.setattr(mod.send_api, "send_text", send)
    chatter = mod.QzoneActivityChatter(message.stream_id, plugin)
    generator = chatter.execute()
    result = await anext(generator)
    assert isinstance(result, mod.Success)
    assert not context.unread_messages and len(context.history_messages) == 1
    assert store.records[message.message_id]["status"] == ("sent" if reply else "ignored")
    if reply:
        assert writes == [(reply, message.stream_id, {"platform": "qzone", "reply_to": message.message_id,
                                                    "adapter_signature": mod.ADAPTER_SIGNATURE})]
    else:
        assert writes == []
    await generator.aclose()
