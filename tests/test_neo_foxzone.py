"""Neo FoxZone 跨插件契约测试。"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PACKAGE = "plugins.neo-foxzone"
constants = importlib.import_module(PACKAGE)
commands_module = importlib.import_module(f"{PACKAGE}.commands")
config_module = importlib.import_module(f"{PACKAGE}.config")
plugin_module = importlib.import_module(f"{PACKAGE}.plugin")
service_module = importlib.import_module(f"{PACKAGE}.service")
tools_module = importlib.import_module(f"{PACKAGE}.tools")
image_provider_module = importlib.import_module(f"{PACKAGE}.image_provider")

BACKEND_SIGNATURE = constants.BACKEND_SERVICE_SIGNATURE
ACCOUNT_SIGNATURE = "onebot_expand:service:account_service"
SERVICE_SIGNATURE = constants.SERVICE_SIGNATURE
NeoFoxzoneCommand = commands_module.NeoFoxzoneCommand
NeoFoxzoneConfig = config_module.NeoFoxzoneConfig
NeoFoxzonePlugin = plugin_module.NeoFoxzonePlugin
NeoFoxzoneError = service_module.NeoFoxzoneError
NeoFoxzoneService = service_module.NeoFoxzoneService
ImageProviderError = image_provider_module.ImageProviderError
normalize_image_result = image_provider_module.normalize_image_result


class FakeQzoneBackend:
    """记录 Neo FoxZone 转发参数的 OneBot Expand 替身。"""

    def __init__(self) -> None:
        """初始化调用记录。"""
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _response(self, action: str, **params: Any) -> dict[str, Any]:
        """记录调用并返回成功响应。"""
        self.calls.append((action, params))
        return {"status": "ok", "retcode": 0, "data": {"action": action}}

    async def get_qzone_msg_list(
        self,
        pos: int = 0,
        num: int = 10,
    ) -> dict[str, Any]:
        """模拟获取说说列表。"""
        return self._response("get_qzone_msg_list", pos=pos, num=num)

    async def get_qzone_feeds(
        self,
        page_num: int = 1,
        count: int = 10,
    ) -> dict[str, Any]:
        """模拟获取好友动态。"""
        return self._response("get_qzone_feeds", page_num=page_num, count=count)

    async def send_qzone_msg(
        self,
        content: str,
        images: list[str] | None = None,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> dict[str, Any]:
        """模拟发表说说。"""
        return self._response(
            "send_qzone_msg",
            content=content,
            images=images,
            ugc_right=ugc_right,
            target_uins=target_uins,
        )

    async def delete_qzone_msg(self, tid: str) -> dict[str, Any]:
        """模拟删除说说。"""
        return self._response("delete_qzone_msg", tid=tid)

    async def like_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> dict[str, Any]:
        """模拟点赞。"""
        return self._response("like_qzone", tid=tid, target_uin=target_uin)

    async def unlike_qzone(
        self,
        tid: str,
        target_uin: int | None = None,
    ) -> dict[str, Any]:
        """模拟取消点赞。"""
        return self._response("unlike_qzone", tid=tid, target_uin=target_uin)

    async def comment_qzone(
        self,
        tid: str,
        content: str,
        target_uin: int | None = None,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """模拟评论。"""
        return self._response(
            "comment_qzone",
            tid=tid,
            content=content,
            target_uin=target_uin,
            images=images,
        )

    async def set_qzone_ban(
        self,
        user_id: int,
        enable: bool = True,
    ) -> dict[str, Any]:
        """模拟空间黑名单设置。"""
        return self._response("set_qzone_ban", user_id=user_id, enable=enable)

    async def set_qzone_msg_right(
        self,
        tid: str,
        ugc_right: int,
        target_uins: list[int] | None = None,
    ) -> dict[str, Any]:
        """模拟修改说说权限。"""
        return self._response(
            "set_qzone_msg_right",
            tid=tid,
            ugc_right=ugc_right,
            target_uins=target_uins,
        )


def _build_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, Any, FakeQzoneBackend]:
    """创建插件、Service 和可解析两个签名的替身运行时。"""
    config = NeoFoxzoneConfig()
    plugin = NeoFoxzonePlugin(config=config)
    service = NeoFoxzoneService(plugin)
    backend = FakeQzoneBackend()

    def get_service(signature: str) -> object | None:
        """按组件签名返回测试实例。"""
        if signature == SERVICE_SIGNATURE:
            return service
        if signature == BACKEND_SIGNATURE:
            return backend
        return None

    monkeypatch.setattr(service_module.service_api, "get_service", get_service)
    return plugin, service, backend


@pytest.mark.asyncio
async def test_service_forwards_all_nine_qzone_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service 应完整转发 OneBot Expand 暴露的九个 QZone action。"""
    _, service, backend = _build_runtime(monkeypatch)

    await service.get_qzone_msg_list(pos=2, num=3)
    await service.get_qzone_feeds(page_num=4, count=5)
    await service.send_qzone_msg(
        content="带图说说",
        images=[" https://example.test/a.jpg "],
        ugc_right=16,
        target_uins=[10001, 10001, 10002],
    )
    await service.delete_qzone_msg(tid=" tid-1 ")
    await service.like_qzone(tid="tid-2", target_uin=20001)
    await service.unlike_qzone(tid="tid-3", target_uin=20002)
    await service.comment_qzone(
        tid="tid-4",
        content="带图评论",
        target_uin=20003,
        images=["file:///tmp/comment.png"],
    )
    await service.set_qzone_ban(user_id=30001, enable=False)
    await service.set_qzone_msg_right(
        tid="tid-5",
        ugc_right=128,
        target_uins=[40001],
    )

    assert [action for action, _ in backend.calls] == [
        "get_qzone_msg_list",
        "get_qzone_feeds",
        "send_qzone_msg",
        "delete_qzone_msg",
        "like_qzone",
        "unlike_qzone",
        "comment_qzone",
        "set_qzone_ban",
        "set_qzone_msg_right",
    ]
    assert backend.calls[2][1] == {
        "content": "带图说说",
        "images": ["https://example.test/a.jpg"],
        "ugc_right": 16,
        "target_uins": [10001, 10002],
    }
    assert backend.calls[3][1] == {"tid": "tid-1"}


@pytest.mark.asyncio
async def test_service_rejects_invalid_inputs_before_backend_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """明显无效输入不应到达协议端。"""
    _, service, backend = _build_runtime(monkeypatch)

    with pytest.raises(NeoFoxzoneError, match="同时为空"):
        await service.send_qzone_msg(content="", images=[])
    with pytest.raises(NeoFoxzoneError, match="正文不能为空"):
        await service.send_qzone_msg(
            content="",
            images=["https://example.test/a.jpg"],
        )
    with pytest.raises(NeoFoxzoneError, match="正文不能为空"):
        await service.comment_qzone(
            tid="tid-image-comment",
            content="",
            images=["https://example.test/a.jpg"],
        )
    with pytest.raises(NeoFoxzoneError, match="target_uins"):
        await service.send_qzone_msg(content="test", ugc_right=16)
    with pytest.raises(NeoFoxzoneError, match="1 到 50"):
        await service.get_qzone_feeds(count=51)
    with pytest.raises(NeoFoxzoneError, match="正整数"):
        await service.set_qzone_ban(user_id=0)

    assert backend.calls == []


@pytest.mark.asyncio
async def test_missing_backend_reports_required_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """前置 Service 缺失时应给出可操作错误。"""
    plugin = NeoFoxzonePlugin(config=NeoFoxzoneConfig())
    service = NeoFoxzoneService(plugin)
    monkeypatch.setattr(service_module.service_api, "get_service", lambda _: None)

    with pytest.raises(NeoFoxzoneError, match="OneBot Expand"):
        await service.get_qzone_msg_list()


@pytest.mark.asyncio
async def test_tools_and_command_use_plugin_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool 与管理员命令应通过 Neo FoxZone Service 调用后端。"""
    plugin, _, backend = _build_runtime(monkeypatch)
    publish_tool = tools_module.NeoFoxzonePublishTool(plugin)

    success, result = await publish_tool.execute(content="tool publish")
    assert success is True
    assert result["action"] == "send_qzone_msg"

    command = NeoFoxzoneCommand(plugin, stream_id="test-stream")
    command_success, output = await command.execute(
        'comment tid-9 "command comment" 50001'
    )
    assert command_success is True
    assert "评论发送成功" in output
    assert backend.calls[-1] == (
        "comment_qzone",
        {
            "tid": "tid-9",
            "content": "command comment",
            "target_uin": 50001,
            "images": None,
        },
    )


def test_plugin_registers_service_command_and_ten_tools() -> None:
    """默认配置应注册基础能力和 AI 生图发布入口。"""
    plugin = NeoFoxzonePlugin(config=NeoFoxzoneConfig())
    names = [component.name for component in plugin.get_components()]

    assert names == [
        "neo_foxzone_service",
        "neofoxzone",
        "neo_foxzone_list_posts",
        "neo_foxzone_list_feeds",
        "neo_foxzone_publish",
        "neo_foxzone_publish_generated",
        "neo_foxzone_delete",
        "neo_foxzone_like",
        "neo_foxzone_unlike",
        "neo_foxzone_comment",
        "neo_foxzone_set_blacklist",
        "neo_foxzone_set_visibility",
    ]
    assert all(
        component.dependencies == [SERVICE_SIGNATURE]
        for component in plugin.get_components()[1:]
    )
    assert plugin.plugin_version == "0.1.1"
    assert plugin.dependencies == [BACKEND_SIGNATURE, ACCOUNT_SIGNATURE]
    assert plugin.config.plugin.version == "0.1.1"
    assert NeoFoxzoneService.version == "0.1.1"


def test_manifest_declares_market_and_runtime_dependency() -> None:
    """Manifest 应同时声明插件级依赖与组件级依赖。"""
    manifest_path = Path(__file__).parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "neo-foxzone"
    assert manifest["version"] == "0.1.1"
    assert manifest["dependencies"]["plugins"] == [
        "onebot_expand>=1.0.13"
    ]
    assert manifest["dependencies"]["components"] == [
        BACKEND_SIGNATURE,
        ACCOUNT_SIGNATURE,
    ]
    assert manifest["dependencies_required"] is True
    assert len(manifest["include"]) == 13


def test_repository_contains_agpl_v3_license() -> None:
    """仓库根目录应包含与 manifest 一致的标准 AGPL v3 许可证。"""
    plugin_root = Path(__file__).parents[1]
    manifest = json.loads(
        (plugin_root / "manifest.json").read_text(encoding="utf-8")
    )
    license_text = (plugin_root / "LICENSE").read_text(encoding="utf-8")

    assert manifest["license"] == "AGPL-3.0"
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text


def test_image_result_normalizes_common_service_shapes() -> None:
    """通用图片 Provider 应统一 URL、data URI、裸 Base64 和结构化返回。"""
    payload = "a" * 64

    assert normalize_image_result(" https://example.test/a.png ") == [
        "https://example.test/a.png"
    ]
    assert normalize_image_result(f"data:image/png;base64,{payload}") == [
        f"base64://{payload}"
    ]
    assert normalize_image_result({"images": [payload]}, assume_base64=True) == [
        f"base64://{payload}"
    ]
    with pytest.raises(ImageProviderError, match="无法识别"):
        normalize_image_result({"unexpected": "value"})
    with pytest.raises(ImageProviderError, match="任何图片"):
        normalize_image_result([])


@pytest.mark.asyncio
async def test_standard_image_service_uses_generic_external_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通用 Provider 应按 description/style 契约调用配置的 Service。"""
    calls: list[dict[str, str]] = []

    class FakeExternalImageService:
        """实现 Neo FoxZone 通用图片接口。"""

        async def generate_image_for_external(
            self,
            *,
            description: str,
            style: str,
        ) -> dict[str, Any]:
            calls.append({"description": description, "style": style})
            return {"images": ["https://example.test/generated.png"]}

    config = NeoFoxzoneConfig()
    config.image.provider = "service"
    config.image.service_signature = "image_plugin:service:generator"
    monkeypatch.setattr(
        image_provider_module.service_api,
        "get_service",
        lambda signature: (
            FakeExternalImageService()
            if signature == "image_plugin:service:generator"
            else None
        ),
    )

    images = await image_provider_module.generate_images(
        config,
        " 海边日落 ",
        "photo",
    )

    assert images == ["https://example.test/generated.png"]
    assert calls == [{"description": "海边日落", "style": "photo"}]


@pytest.mark.asyncio
async def test_nai_artist_adapter_translates_and_normalizes_raw_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NAI 适配器应复用翻译配置，并把裸 Base64 转为 QZone 引用。"""
    generated: list[dict[str, Any]] = []
    artist_config = SimpleNamespace(
        api=SimpleNamespace(get_translate_model=lambda: "translator"),
        character=SimpleNamespace(base_tags="1girl"),
        wardrobe=SimpleNamespace(enabled=False, auto_daily=False),
    )

    class FakeNaiService:
        """模拟 NAI Artist 的现有非通用 Service。"""

        plugin = SimpleNamespace(config=artist_config)

        async def generate_image(
            self,
            prompt_tags: str,
            style_type: str,
            config: Any,
        ) -> str:
            generated.append(
                {
                    "prompt_tags": prompt_tags,
                    "style_type": style_type,
                    "config": config,
                }
            )
            return "a" * 64

    async def translate_to_nai_tags(**kwargs: Any) -> str:
        assert kwargs == {
            "description": "窗边晨光",
            "style_hint": "hint:photo",
            "translate_model": "translator",
            "character_profile": "1girl",
            "mode": "photo",
            "outfit_context": "",
        }
        return "best quality, window light"

    def import_module(name: str) -> Any:
        if name == "plugins.nai_artist.prompt_builder":
            return SimpleNamespace(translate_to_nai_tags=translate_to_nai_tags)
        if name == "plugins.nai_artist.action":
            return SimpleNamespace(get_style_hint=lambda style: f"hint:{style}")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(
        image_provider_module.service_api,
        "get_service",
        lambda signature: (
            FakeNaiService()
            if signature == image_provider_module.NAI_ARTIST_SERVICE_SIGNATURE
            else None
        ),
    )
    monkeypatch.setattr(image_provider_module.importlib, "import_module", import_module)

    images = await image_provider_module.generate_images(
        NeoFoxzoneConfig(),
        "窗边晨光",
        "photo",
    )

    assert images == [f"base64://{'a' * 64}"]
    assert generated == [
        {
            "prompt_tags": "best quality, window light",
            "style_type": "photo",
            "config": artist_config,
        }
    ]


@pytest.mark.asyncio
async def test_image_provider_timeout_prevents_partial_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """图片 Service 超时应转为 Provider 错误，不允许继续发布纯文字。"""
    config = NeoFoxzoneConfig()
    assert config.image.timeout_seconds == 180.0
    config.image.provider = "service"
    config.image.service_signature = "image_plugin:service:slow"
    config.image.timeout_seconds = 0.01

    class SlowImageService:
        """模拟永不及时完成的外部图片 Service。"""

        async def generate_image_for_external(
            self,
            *,
            description: str,
            style: str,
        ) -> str:
            await asyncio.sleep(60)
            return "https://example.test/late.png"

    monkeypatch.setattr(
        image_provider_module.service_api,
        "get_service",
        lambda _: SlowImageService(),
    )

    with pytest.raises(ImageProviderError, match="超时"):
        await image_provider_module.generate_images(config, "慢速图片", "drawing")


def test_feed_parser_selects_only_unanswered_recoverable_comments() -> None:
    """解析器只应产出尚未被 Bot 回复且具备明确回复关系的评论。"""
    parser_module = importlib.import_module(f"{PACKAGE}.feed_parser")
    extract_reply_candidates = parser_module.extract_reply_candidates
    response = {
        "status": "ok",
        "retcode": 0,
        "data": {
            "msglist": [
                {
                    "tid": "own-post",
                    "content": "自己的说说",
                    "commentlist": [
                        {
                            "commentid": "c1",
                            "uin": 10001,
                            "content": "还没有回复",
                        },
                        {
                            "commentid": "c2",
                            "uin": 10002,
                            "content": "已经回复",
                            "list_3": [
                                {
                                    "commentid": "bot-r1",
                                    "uin": 99999,
                                    "content": "已处理",
                                }
                            ],
                        },
                    ],
                }
            ],
            "feeds": [
                {
                    "uin": 20001,
                    "key": "friend-post",
                    "content": "朋友的说说",
                    "comments": [
                        {
                            "id": "c3",
                            "uin": 99999,
                            "content": "Bot 先前的评论",
                        },
                        {
                            "id": "c4",
                            "uin": 20001,
                            "content": "直接回复 Bot",
                            "parent_comment_id": "c3",
                        },
                        {
                            "id": "c5",
                            "uin": 20002,
                            "content": "普通评论",
                        },
                    ],
                }
            ],
        },
    }

    candidates = extract_reply_candidates(response, bot_uin=99999)

    assert [(item.post_id, item.comment_id) for item in candidates] == [
        ("own-post", "c1"),
        ("friend-post", "c4"),
    ]
    assert candidates[0].target_uin is None
    assert candidates[1].target_uin == 20001


def test_feed_parser_recovers_reply_to_persisted_bot_comment() -> None:
    """父评论未展开时，持久化的 Bot 评论 ID 仍应恢复直接回复。"""
    parser_module = importlib.import_module(f"{PACKAGE}.feed_parser")
    candidates = parser_module.extract_reply_candidates(
        {
            "status": "ok",
            "retcode": 0,
            "data": {
                "feeds": [
                    {
                        "uin": 20001,
                        "key": "friend-post",
                        "comments": [
                            {
                                "id": "friend-reply",
                                "uin": 20001,
                                "content": "接着聊",
                                "parent_comment_id": "persisted-bot-comment",
                            }
                        ],
                    }
                ]
            },
        },
        bot_uin=99999,
        known_bot_comment_ids={
            "20001:friend-post": {"persisted-bot-comment"}
        },
    )

    assert [(item.post_id, item.comment_id) for item in candidates] == [
        ("friend-post", "friend-reply")
    ]


def test_feed_parser_rejects_ambiguous_comment_fields() -> None:
    """未知容器、说说 ID 别名和 target_uin 不得被猜成评论关系。"""
    parser_module = importlib.import_module(f"{PACKAGE}.feed_parser")
    candidates = parser_module.extract_reply_candidates(
        {
            "status": "ok",
            "retcode": 0,
            "data": {
                "msglist": [
                    {
                        "tid": "own-post",
                        "children": [
                            {
                                "tid": "not-a-comment-id",
                                "owner_uin": 10001,
                                "content": "未知结构",
                            }
                        ],
                    }
                ],
                "feeds": [
                    {
                        "uin": 20001,
                        "key": "friend-post",
                        "comments": [
                            {
                                "id": "bot-comment",
                                "uin": 99999,
                                "content": "Bot 评论",
                            },
                            {
                                "id": "ambiguous-target",
                                "uin": 20001,
                                "content": "target_uin 只是说说所有者",
                                "target_uin": 99999,
                            },
                        ],
                    }
                ],
            },
        },
        bot_uin=99999,
    )

    assert candidates == []


def test_feed_parser_rebuilds_flat_parent_graph_before_replying() -> None:
    """平铺评论中已有 Bot 直接子回复时不得再次选为候选。"""
    parser_module = importlib.import_module(f"{PACKAGE}.feed_parser")
    candidates = parser_module.extract_reply_candidates(
        {
            "status": "ok",
            "retcode": 0,
            "data": {
                "msglist": [
                    {
                        "tid": "own-post",
                        "commentlist": [
                            {
                                "commentid": "own-user",
                                "uin": 10001,
                                "content": "用户评论",
                            },
                            {
                                "commentid": "own-bot",
                                "uin": 99999,
                                "content": "Bot 已回复",
                                "parent_comment_id": "own-user",
                            },
                        ],
                    }
                ],
                "feeds": [
                    {
                        "uin": 20001,
                        "key": "friend-post",
                        "comments": [
                            {
                                "id": "friend-bot-root",
                                "uin": 99999,
                                "content": "Bot 先前评论",
                            },
                            {
                                "id": "friend-user-reply",
                                "uin": 20001,
                                "content": "用户直接回复",
                                "parent_comment_id": "friend-bot-root",
                            },
                            {
                                "id": "friend-bot-reply",
                                "uin": 99999,
                                "content": "Bot 已跟进",
                                "parent_comment_id": "friend-user-reply",
                            },
                        ],
                    }
                ],
            },
        },
        bot_uin=99999,
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_feed_queries_default_to_one_based_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """好友动态入口默认应使用 SnowLuma 要求的 1 起页码。"""
    plugin, service, backend = _build_runtime(monkeypatch)

    await service.get_qzone_feeds()
    assert backend.calls[-1] == (
        "get_qzone_feeds",
        {"page_num": 1, "count": 10},
    )
    with pytest.raises(NeoFoxzoneError, match="不能小于 1"):
        await service.get_qzone_feeds(page_num=0)

    feed_tool = tools_module.NeoFoxzoneListFeedsTool(plugin)
    success, _ = await feed_tool.execute()
    assert success is True
    assert backend.calls[-1][1]["page_num"] == 1

    command = NeoFoxzoneCommand(plugin, stream_id="test-stream")
    success, _ = await command.execute("feeds")
    assert success is True
    assert backend.calls[-1][1]["page_num"] == 1


@pytest.mark.asyncio
async def test_generated_publish_rejects_empty_provider_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider 空结果不得退化为纯文字说说。"""
    _, service, backend = _build_runtime(monkeypatch)

    async def generate_images(
        config: Any,
        description: str,
        style: str | None = None,
    ) -> list[str]:
        return []

    monkeypatch.setattr(service_module, "generate_images", generate_images)

    with pytest.raises(NeoFoxzoneError, match="任何图片"):
        await service.send_generated_qzone_msg(
            content="不能单独发布",
            image_description="空结果",
        )
    assert backend.calls == []


@pytest.mark.asyncio
async def test_polling_state_persists_and_trims_deduplication_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """轮询状态应跨重启保存去重记录，并按配置裁剪最旧项目。"""
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    PollingState = state_module.PollingState
    saved: dict[str, Any] = {}

    async def load_json(store_name: str, name: str) -> dict[str, Any] | None:
        """返回上一次保存的状态副本。"""
        assert store_name == "neo-foxzone"
        assert name == "polling_state"
        return dict(saved) if saved else None

    async def save_json(
        store_name: str,
        name: str,
        data: dict[str, Any],
    ) -> None:
        """记录待持久化状态。"""
        assert store_name == "neo-foxzone"
        assert name == "polling_state"
        saved.clear()
        saved.update(data)

    monkeypatch.setattr(state_module.storage_api, "load_json", load_json)
    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    state = await PollingState.load(max_entries=2)
    state.mark_processed("comment-1")
    state.mark_processed("comment-2")
    state.mark_processed("comment-3")
    state.reserve("comment-in-flight")
    state.record_failure("comment-retry", retry_after=1234.5)
    state.last_attempted_identity = "comment-retry"
    state.remember_bot_comment(
        post_id="friend-post",
        owner_uin=20001,
        comment_id="bot-comment-1",
    )
    await state.save()

    restored = await PollingState.load(max_entries=2)

    assert restored.is_processed("comment-1") is False
    assert restored.is_processed("comment-2") is True
    assert restored.is_processed("comment-3") is True
    assert restored.is_in_flight("comment-in-flight") is True
    assert restored.retry_after("comment-retry") == 1234.5
    assert restored.failure_count("comment-retry") == 1
    assert restored.last_attempted_identity == "comment-retry"
    assert restored.known_bot_comment_ids("friend-post", 20001) == {
        "bot-comment-1"
    }


@pytest.mark.asyncio
async def test_poller_replies_only_to_new_candidates_and_commits_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单轮轮询只处理新评论，并在协议成功后提交状态。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    QzoneReplyPoller = poller_module.QzoneReplyPoller
    PollingState = state_module.PollingState
    saved: dict[str, Any] = {}
    snapshots: list[dict[str, Any]] = []
    messages: list[str] = []

    class FakeLogger:
        """收集候选决策与发送日志。"""

        def info(self, message: str) -> None:
            messages.append(message)

        def warning(self, message: str) -> None:
            messages.append(message)

        def error(self, message: str, **kwargs: Any) -> None:
            messages.append(message)

    async def save_json(
        store_name: str,
        name: str,
        data: dict[str, Any],
    ) -> None:
        """记录轮询器提交的状态。"""
        saved.clear()
        saved.update(data)
        snapshots.append(json.loads(json.dumps(data)))

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)
    monkeypatch.setattr(poller_module, "logger", FakeLogger())

    class FakePollingService:
        """提供一条旧评论与一条新评论的 QZone Service。"""

        def __init__(self) -> None:
            self.comments: list[dict[str, Any]] = []

        async def get_qzone_msg_list(
            self,
            pos: int = 0,
            num: int = 10,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "content": "测试说说",
                            "commentlist": [
                                {
                                    "commentid": "old-comment",
                                    "uin": 10001,
                                    "content": "旧评论",
                                },
                                {
                                    "commentid": "new-comment",
                                    "uin": 10002,
                                    "nickname": "新访客",
                                    "content": "新评论",
                                },
                            ],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(
            self,
            page_num: int = 1,
            count: int = 10,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {"feeds": []},
            }

        async def comment_qzone(
            self,
            tid: str,
            content: str,
            target_uin: int | None = None,
            images: list[str] | None = None,
        ) -> dict[str, Any]:
            assert snapshots[-1]["in_flight_comment_ids"] == [
                "own_post:0:own-post:new-comment"
            ]
            self.comments.append(
                {
                    "tid": tid,
                    "content": content,
                    "target_uin": target_uin,
                    "images": images,
                }
            )
            return {
                "status": "ok",
                "retcode": 0,
                "data": {"comment_id": "bot-comment-new"},
            }

    generated: list[str] = []

    async def generate_reply(candidate: Any) -> str:
        """根据候选评论生成可预测回复。"""
        generated.append(candidate.comment_id)
        return f"回复 {candidate.comment_content}"

    async def load_bot_uin() -> int:
        """返回测试 Bot QQ。"""
        return 99999

    config = NeoFoxzoneConfig()
    plugin = NeoFoxzonePlugin(config=config)
    state = PollingState(max_entries=20)
    state.mark_processed("own_post:0:own-post:old-comment")
    service = FakePollingService()
    poller = QzoneReplyPoller(
        plugin,
        service=service,
        state=state,
        reply_generator=generate_reply,
        bot_uin_loader=load_bot_uin,
    )

    report = await poller.poll_once()

    assert generated == ["new-comment"]
    assert service.comments == [
        {
            "tid": "own-post",
            "content": "回复 新评论",
            "target_uin": None,
            "images": None,
        }
    ]
    assert report.candidates == 2
    assert report.skipped_processed == 1
    assert report.replied == 1
    assert report.failed == 0
    assert state.is_processed("own_post:0:own-post:new-comment") is True
    assert state.known_bot_comment_ids("own-post", None) == {
        "bot-comment-new"
    }
    assert saved["processed_comment_ids"][-1].endswith("new-comment")
    assert saved["in_flight_comment_ids"] == []
    assert len(snapshots) == 2
    assert any(
        "评论ID=new-comment" in message
        and "决策=生成并发送回复" in message
        for message in messages
    )
    assert any(
        "自动回复生成完成" in message
        and "回复 新评论" in message
        for message in messages
    )
    assert any(
        "自动回复发送成功" in message
        and "Bot评论ID=bot-comment-new" in message
        for message in messages
    )


@pytest.mark.asyncio
async def test_poller_logs_query_shape_and_safe_skip_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺少结构化评论时应明确记录读取结果和安全跳过原因。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    messages: list[str] = []

    class FakeLogger:
        """收集轮询器信息日志。"""

        def info(self, message: str) -> None:
            messages.append(message)

        def warning(self, message: str) -> None:
            messages.append(message)

        def error(self, message: str, **kwargs: Any) -> None:
            messages.append(message)

    class ShapeOnlyService:
        """模拟只返回评论数量与预渲染 HTML 的协议端。"""

        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "content": "只有评论数量",
                            "comment_num": 2,
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "feeds": [
                        {
                            "uin": 20001,
                            "key": "friend-post",
                            "html": "<li>预渲染动态</li>",
                        }
                    ]
                },
            }

        async def comment_qzone(self, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("无结构化候选时不应发表评论")

    monkeypatch.setattr(poller_module, "logger", FakeLogger())
    poller = poller_module.QzoneReplyPoller(
        NeoFoxzonePlugin(config=NeoFoxzoneConfig()),
        service=ShapeOnlyService(),
        state=state_module.PollingState(),
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    report = await poller.poll_once()

    assert report.candidates == 0
    assert any(
        "自身说说读取完成" in message
        and "返回说说=1" in message
        and "声明评论=2" in message
        and "结构化评论=0" in message
        for message in messages
    )
    assert any(
        "协议仅返回评论数量" in message
        and "决策=不回复" in message
        for message in messages
    )
    assert any(
        "好友动态读取完成" in message
        and "返回动态=1" in message
        and "HTML动态=1" in message
        for message in messages
    )
    assert any(
        "协议返回预渲染 HTML" in message
        and "决策=不回复" in message
        for message in messages
    )
    assert any("本轮没有可安全回复的评论候选" in message for message in messages)


@pytest.mark.asyncio
async def test_poller_does_not_send_when_reservation_cannot_be_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发送前状态落盘失败时必须停止，不能产生远端副作用。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    PollingState = state_module.PollingState
    sent: list[str] = []

    async def save_json(*args: Any, **kwargs: Any) -> None:
        raise OSError("storage unavailable")

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    class FakePollingService:
        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "commentlist": [
                                {
                                    "commentid": "new-comment",
                                    "uin": 10001,
                                    "content": "请回复",
                                }
                            ],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def comment_qzone(self, **kwargs: Any) -> dict[str, Any]:
            sent.append(str(kwargs["tid"]))
            return {"status": "ok", "retcode": 0}

    async def generate_reply(candidate: Any) -> str:
        return "测试回复"

    poller = poller_module.QzoneReplyPoller(
        NeoFoxzonePlugin(config=NeoFoxzoneConfig()),
        service=FakePollingService(),
        state=PollingState(),
        reply_generator=generate_reply,
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    report = await poller.poll_once()

    assert sent == []
    assert report.replied == 0
    assert report.failed == 1
    assert report.state_errors == [
        "own_post:0:own-post:new-comment: storage unavailable"
    ]


@pytest.mark.asyncio
async def test_poller_keeps_ambiguous_remote_result_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """远端调用抛异常时保留持久占用，下一轮不得重复发送。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    PollingState = state_module.PollingState
    saved: dict[str, Any] = {}
    sends = 0

    async def save_json(
        store_name: str,
        name: str,
        data: dict[str, Any],
    ) -> None:
        saved.clear()
        saved.update(json.loads(json.dumps(data)))

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    class FakePollingService:
        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "commentlist": [
                                {
                                    "commentid": "uncertain-comment",
                                    "uin": 10001,
                                    "content": "网络结果不明",
                                }
                            ],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def comment_qzone(self, **kwargs: Any) -> dict[str, Any]:
            nonlocal sends
            sends += 1
            raise TimeoutError("response lost")

    async def generate_reply(candidate: Any) -> str:
        return "测试回复"

    state = PollingState()
    poller = poller_module.QzoneReplyPoller(
        NeoFoxzonePlugin(config=NeoFoxzoneConfig()),
        service=FakePollingService(),
        state=state,
        reply_generator=generate_reply,
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    first = await poller.poll_once()
    second = await poller.poll_once()

    identity = "own_post:0:own-post:uncertain-comment"
    assert sends == 1
    assert first.failed == 1
    assert second.skipped_in_flight == 1
    assert state.is_in_flight(identity) is True
    assert saved["in_flight_comment_ids"] == [identity]


@pytest.mark.asyncio
async def test_poller_rotates_after_failed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单轮尝试上限命中后，下轮应从失败候选之后继续。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    monkeypatch.setattr(
        state_module.storage_api,
        "save_json",
        lambda *args, **kwargs: asyncio.sleep(0),
    )
    attempted: list[str] = []
    sent: list[str] = []

    class FakePollingService:
        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "commentlist": [
                                {
                                    "commentid": "always-fails",
                                    "uin": 10001,
                                    "content": "第一条",
                                },
                                {
                                    "commentid": "should-run-next",
                                    "uin": 10002,
                                    "content": "第二条",
                                },
                            ],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def comment_qzone(self, **kwargs: Any) -> dict[str, Any]:
            sent.append(str(kwargs["content"]))
            return {"status": "ok", "retcode": 0}

    async def generate_reply(candidate: Any) -> str:
        attempted.append(candidate.comment_id)
        if candidate.comment_id == "always-fails":
            raise RuntimeError("model failure")
        return "第二条回复"

    config = NeoFoxzoneConfig()
    config.polling.max_replies_per_poll = 1
    config.polling.max_attempts_per_poll = 1
    plugin = NeoFoxzonePlugin(config=config)
    poller = poller_module.QzoneReplyPoller(
        plugin,
        service=FakePollingService(),
        state=state_module.PollingState(),
        reply_generator=generate_reply,
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    first = await poller.poll_once()
    second = await poller.poll_once()

    assert first.failed == 1
    assert second.replied == 1
    assert attempted == ["always-fails", "should-run-next"]
    assert sent == ["第二条回复"]


@pytest.mark.asyncio
async def test_plugin_lifecycle_runs_startup_poll_and_cancels_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """插件加载应注册启动检查守护任务，卸载时按 task ID 取消。"""
    plugin = NeoFoxzonePlugin(config=NeoFoxzoneConfig())
    fake_service = object()

    class FakePoller:
        """记录实际执行的轮询次数。"""

        def __init__(self) -> None:
            self.calls = 0

        async def poll_once(self) -> Any:
            self.calls += 1
            return SimpleNamespace(
                candidates=0,
                replied=0,
                failed=0,
                query_errors=[],
            )

    class FakeTaskManager:
        """接管守护协程，避免测试创建真实后台任务。"""

        def __init__(self) -> None:
            self.task: asyncio.Task[Any] | None = None
            self.name = ""
            self.daemon = False
            self.cancelled: list[str] = []

        def create_task(
            self,
            coro: Any,
            name: str | None = None,
            daemon: bool = False,
        ) -> Any:
            self.name = name or ""
            self.daemon = daemon
            self.task = asyncio.create_task(coro)
            return SimpleNamespace(
                task_id="neo-foxzone-poll-task",
                task=self.task,
            )

        def cancel_task(self, task_id: str) -> bool:
            self.cancelled.append(task_id)
            if self.task is not None:
                self.task.cancel()
            return True

    poller = FakePoller()
    task_manager = FakeTaskManager()

    async def load_state(max_entries: int = 2000) -> Any:
        return SimpleNamespace(max_entries=max_entries)

    monkeypatch.setattr(
        plugin_module.service_api,
        "get_service",
        lambda signature: fake_service if signature == SERVICE_SIGNATURE else None,
    )
    monkeypatch.setattr(plugin_module.PollingState, "load", load_state)
    monkeypatch.setattr(
        plugin_module,
        "create_poller",
        lambda owner, service, state: poller,
    )
    monkeypatch.setattr(plugin_module, "get_task_manager", lambda: task_manager)
    await plugin.on_plugin_loaded()
    for _ in range(10):
        if poller.calls:
            break
        await asyncio.sleep(0)

    assert task_manager.name == "neo_foxzone_reply_poller"
    assert task_manager.daemon is True
    assert plugin._poll_task_id == "neo-foxzone-poll-task"
    assert poller.calls == 1

    await plugin.on_plugin_unloaded()

    assert task_manager.cancelled == ["neo-foxzone-poll-task"]
    assert task_manager.task is not None
    assert task_manager.task.done() is True
    assert plugin._poll_task_id is None


@pytest.mark.asyncio
async def test_poll_loop_survives_startup_check_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """启动检查异常应被记录，不能让守护循环直接退出。"""
    plugin = NeoFoxzonePlugin(config=NeoFoxzoneConfig())
    messages: list[str] = []

    class FakeLogger:
        """收集轮询调度日志。"""

        def info(self, message: str) -> None:
            messages.append(message)

        def warning(self, message: str) -> None:
            messages.append(message)

        def error(self, message: str, **kwargs: Any) -> None:
            messages.append(message)

    class FakePoller:
        def __init__(self) -> None:
            self.calls = 0

        async def poll_once(self) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("startup failed")
            return SimpleNamespace(
                candidates=0,
                replied=0,
                failed=0,
                query_errors=[],
            )

    poller = FakePoller()
    plugin._poller = poller  # type: ignore[assignment]
    sleeps = 0

    async def run_one_interval(_: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(plugin_module, "logger", FakeLogger())
    monkeypatch.setattr(plugin_module.asyncio, "sleep", run_one_interval)

    with pytest.raises(asyncio.CancelledError):
        await plugin._run_poll_loop()

    assert poller.calls == 2
    assert any("启动检查开始" in message for message in messages)
    assert any(
        "下次定时检查将在 30 分钟后执行" in message
        for message in messages
    )
    assert any("定时检查开始" in message for message in messages)


@pytest.mark.asyncio
async def test_generated_publish_waits_for_provider_then_publishes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI 配图应完成后与正文合并为一次 QZone 发布。"""
    _, service, backend = _build_runtime(monkeypatch)
    events: list[str] = []

    async def generate_images(
        config: Any,
        description: str,
        style: str | None = None,
    ) -> list[str]:
        events.append(f"generated:{description}:{style}")
        assert backend.calls == []
        return ["base64://generated-image"]

    monkeypatch.setattr(service_module, "generate_images", generate_images)

    response = await service.send_generated_qzone_msg(
        content="配图说说",
        image_description="雨夜霓虹",
        image_style="drawing",
    )

    assert service.response_succeeded(response) is True
    assert events == ["generated:雨夜霓虹:drawing"]
    assert backend.calls == [
        (
            "send_qzone_msg",
            {
                "content": "配图说说",
                "images": ["base64://generated-image"],
                "ugc_right": 1,
                "target_uins": None,
            },
        )
    ]


@pytest.mark.asyncio
async def test_generated_publish_tool_and_commands_use_existing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新 Tool、publish-ai 与 poll-now 应复用现有 Service 和轮询器。"""
    plugin, service, backend = _build_runtime(monkeypatch)

    async def generate_images(
        config: Any,
        description: str,
        style: str | None = None,
    ) -> list[str]:
        return ["https://example.test/generated.png"]

    monkeypatch.setattr(service_module, "generate_images", generate_images)
    generated_tool_class = tools_module.NeoFoxzonePublishGeneratedTool
    generated_tool = generated_tool_class(plugin)

    tool_success, _ = await generated_tool.execute(
        content="Tool AI 发布",
        image_description="窗边晨光",
        image_style="photo",
    )

    class FakeManualPoller:
        """提供可观察的手动轮询报告。"""

        def __init__(self) -> None:
            self.calls = 0
            self.last_report: Any = None

        async def poll_once(self) -> Any:
            self.calls += 1
            self.last_report = SimpleNamespace(
                candidates=3,
                skipped_processed=1,
                replied=2,
                failed=0,
                query_errors=[],
                reply_errors=[],
            )
            return self.last_report

    poller = FakeManualPoller()
    plugin._poller = poller  # type: ignore[assignment]
    command = NeoFoxzoneCommand(plugin, stream_id="test-stream")
    command_success, output = await command.execute(
        'publish-ai "命令 AI 发布" "夜空烟花" drawing'
    )
    poll_success, poll_output = await command.execute("poll-now")

    assert tool_success is True
    assert command_success is True
    assert "AI 配图说说发表成功" in output
    assert poll_success is True
    assert "候选=3" in poll_output
    assert "回复=2" in poll_output
    assert poller.calls == 1
    assert [call[0] for call in backend.calls] == [
        "send_qzone_msg",
        "send_qzone_msg",
    ]