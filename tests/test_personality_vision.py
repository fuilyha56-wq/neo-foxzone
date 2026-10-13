"""人格、视觉输入和缓存边界测试；模型与网络均隔离。"""

from __future__ import annotations

import base64
import importlib
from types import SimpleNamespace

import pytest

content = importlib.import_module("plugins.neo-foxzone.core.llm.content_service")
persona = importlib.import_module("plugins.neo-foxzone.core.llm.personality")
vision = importlib.import_module("plugins.neo-foxzone.core.llm.vision")
config_module = importlib.import_module("plugins.neo-foxzone.config")
runtime_module = importlib.import_module("plugins.neo-foxzone.runtime")
Config = config_module.NeoFoxzoneConfig
IMAGE = "base64://" + base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()


class Response:
    def __init__(self, value: str):
        self.value = value

    def __await__(self):
        async def result():
            return self.value
        return result().__await__()


class Request:
    def __init__(self, value: str):
        self.value, self.payloads = value, []

    def add_payload(self, payload):
        self.payloads.append(payload)

    async def send(self, stream=False):
        return Response(self.value)


class Cache:
    def __init__(self):
        self.data, self.saves = {}, 0

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    async def save(self):
        self.saves += 1


@pytest.fixture
def models(monkeypatch):
    requests, tasks = [], []

    def create(**kwargs):
        request = Request("模型生成的内容")
        requests.append(request)
        return request

    monkeypatch.setattr(content.llm_api, "create_llm_request", create)
    monkeypatch.setattr(content.llm_api, "get_model_set_by_task", lambda name: tasks.append(name))
    monkeypatch.setattr(persona.config_api, "get_core_config", lambda: SimpleNamespace(
        personality=SimpleNamespace(nickname="小狐", identity="空间好友", personality_core="温和",
                                    reply_style="简短口语", personality_side="", background_story="")))
    return requests, tasks


@pytest.mark.asyncio
async def test_story_inherits_core_personality_and_separate_task(models):
    requests, tasks = models
    config = Config()
    config.llm.story_model_task = "actor"
    service = content.ContentService(config)
    assert await service.generate_story("测试", recent_posts="近期说说") == "模型生成的内容"
    system = requests[0].payloads[0].content[0].text
    assert all(value in system for value in ("小狐", "温和", "简短口语", "不可信", "Asia/Shanghai"))
    assert "近期说说" in requests[0].payloads[1].content[0].text
    assert tasks == ["actor"]


def test_personality_can_be_disabled(models):
    prompt = persona.build_system_prompt("任务", inherit_personality=False)
    assert "小狐" not in prompt
    assert "不可信" in prompt


@pytest.mark.asyncio
async def test_multimodal_reply_attaches_image_without_json_base64(models):
    requests, _ = models
    service = content.ContentService(Config())
    await service.generate_reply({"comment": "看看图片", "_image_contents": [IMAGE]})
    payload = requests[0].payloads[1]
    assert isinstance(payload.content[1], content.Image)
    assert "base64" not in payload.content[0].text
    assert "image_attachment_range" in payload.content[0].text


@pytest.mark.asyncio
async def test_vision_caches_success_with_hashed_daily_key(models):
    requests, tasks = models
    loaded = []

    async def load(ref):
        loaded.append(ref)
        return IMAGE

    cache = Cache()
    service = vision.VisionService(Config(), cache, load)
    ref = "https://example.org/image.png?signature=private"
    assert await service.describe_images([ref, ref]) == {ref: "模型生成的内容"}
    assert await service.describe_images([ref]) == {ref: "模型生成的内容"}
    assert len(requests) == len(loaded) == 1
    assert tasks == ["vlm"]
    assert all("private" not in key and "example.org" not in key for key in cache.data)


@pytest.mark.asyncio
async def test_vision_rejects_empty_model_output_without_cache(models):
    requests, _ = models
    cache = Cache()

    async def load(ref):
        return IMAGE

    def create(**kwargs):
        request = Request("")
        requests.append(request)
        return request

    original = vision.llm_api.create_llm_request
    vision.llm_api.create_llm_request = create
    try:
        with pytest.raises(ValueError, match="未返回"):
            await vision.VisionService(Config(), cache, load).describe_images([IMAGE])
    finally:
        vision.llm_api.create_llm_request = original
    assert cache.data == {}


@pytest.mark.asyncio
async def test_vision_rejects_unverified_loader_result(models):
    requests, _ = models

    async def load(ref):
        return "http://127.0.0.1/private"

    with pytest.raises(ValueError, match="图片验证"):
        await vision.VisionService(Config(), Cache(), load).describe_images([IMAGE])
    assert requests == []


def test_protocol_image_fields_and_cache_bound():
    assert vision.image_references({"images": ["a", {"url": "b"}], "pic": [{"url3": "b"}, {"url2": "c"}, {"unknown": "d"}]}) == ["a", "b", "c"]
    cache = runtime_module.VisionCache(maximum_records=2)
    for index in range(3):
        cache.set(str(index), "描述")
    assert cache.get("0") is None
    assert cache.get("2") == "描述"
