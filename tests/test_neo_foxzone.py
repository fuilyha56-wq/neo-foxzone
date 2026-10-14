"""Neo FoxZone 跨插件契约测试。"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import time
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
providers_module = importlib.import_module(f"{PACKAGE}.providers")

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


@pytest.mark.asyncio
async def test_direct_read_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class ReadService:
        async def get_qzone_user_feeds(self, **kwargs: Any):
            calls.append(("list", kwargs))
            return {"status": "ok"}

        async def get_qzone_msg_detail(self, **kwargs: Any):
            calls.append(("detail", kwargs))
            return {"status": "ok"}

    async def run(self, operation, message):
        return (await operation)["status"] == "ok", message

    monkeypatch.setattr(NeoFoxzoneCommand, "_service", lambda self: ReadService())
    monkeypatch.setattr(NeoFoxzoneCommand, "_run", run)
    command = object.__new__(NeoFoxzoneCommand)
    assert (await command.handle_user_posts(12345, 2, 3))[0]
    assert (await command.handle_detail("post-id", 12345))[0]
    assert calls == [
        ("list", {"host_uin": 12345, "pos": 2, "num": 3}),
        ("detail", {"tid": "post-id", "host_uin": 12345}),
    ]


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

    async def get_qzone_user_feeds(
        self,
        *,
        host_uin: int,
        pos: int = 0,
        num: int = 5,
        self_uin: int | None = None,
    ) -> dict[str, Any]:
        """模拟读取指定 QQ 的说说列表。"""
        return self._response(
            "get_qzone_user_feeds",
            host_uin=host_uin,
            pos=pos,
            num=num,
            self_uin=self_uin,
        )

    async def get_qzone_msg_detail(
        self,
        tid: str,
        host_uin: int,
    ) -> dict[str, Any]:
        """模拟获取说说详情。"""
        return self._response(
            "get_qzone_msg_detail",
            tid=tid,
            host_uin=host_uin,
        )

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

    async def reply_qzone_comment(
        self,
        *,
        tid: str,
        host_uin: int,
        root_comment_id: str,
        target_uin: int,
        target_name: str,
        content: str,
        self_uin: int | None = None,
    ) -> dict[str, Any]:
        """模拟发送楼中楼回复。"""
        return self._response(
            "reply_qzone_comment",
            tid=tid,
            host_uin=host_uin,
            root_comment_id=root_comment_id,
            target_uin=target_uin,
            target_name=target_name,
            content=content,
            self_uin=self_uin,
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
    config.limits.write_min_interval_seconds = 0
    plugin = NeoFoxzonePlugin(config=config)
    service = NeoFoxzoneService(plugin)
    backend = FakeQzoneBackend()

    async def confirmed_login(*, expected_qq: str | None = None) -> dict[str, Any]:
        """返回由测试模拟的实时登录接口确认结果。"""
        return {"status": "confirmed", "qq": expected_qq or "3693525299"}

    async def verified_detail(tid: str, owner_uin: int) -> dict[str, Any]:
        """返回测试用显式作者和顶层评论详情。"""
        return {
            "tid": tid,
            "uin": owner_uin,
            "commentlist": [
                {"comment_id": "global-root-comment-id", "uin": 10003, "list_3": []}
            ],
        }

    async def fake_download_remote_image(url: str, maximum_bytes: int) -> str:
        """返回小型 PNG 替身，避免契约测试发起外网请求。"""
        del url
        image_bytes = b"\x89PNG\r\n\x1a\n"
        assert len(image_bytes) <= maximum_bytes
        return "base64://" + base64.b64encode(image_bytes).decode("ascii")

    monkeypatch.setattr(service_module, "get_current_login_info", confirmed_login)
    monkeypatch.setattr(service, "_verified_post_detail", verified_detail)
    monkeypatch.setattr(service, "_download_remote_image", fake_download_remote_image)
    monkeypatch.setattr(
        tools_module.service_api,
        "get_service",
        lambda signature: service if signature == SERVICE_SIGNATURE else None,
    )
    monkeypatch.setattr(
        service_module,
        "discover_qzone_provider",
        lambda refresh=False: type(
            "Snapshot",
            (),
            {"provider": backend, "diagnostic": "test provider", "source": BACKEND_SIGNATURE},
        )(),
    )
    return plugin, service, backend


class FakeDirectClient:
    """记录 QZone 直连客户端调用的替身。"""

    def __init__(self) -> None:
        """初始化调用记录与可配置返回数据。"""
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.user_feeds: list[dict[str, Any]] = []
        self.msg_detail: dict[str, Any] = {}

    async def get_msg_detail(self, host_uin: int, tid: str) -> dict[str, Any]:
        """记录详情读取并返回预设数据。"""
        self.calls.append(("get_msg_detail", {"host_uin": host_uin, "tid": tid}))
        return self.msg_detail

    async def get_user_feeds(
        self,
        *,
        host_uin: int,
        pos: int = 0,
        num: int = 5,
    ) -> list[dict[str, Any]]:
        """记录列表读取并返回预设数据。"""
        self.calls.append(
            ("get_user_feeds", {"host_uin": host_uin, "pos": pos, "num": num})
        )
        return self.user_feeds

    async def reply_comment(
        self,
        *,
        host_uin: int,
        tid: str,
        root_comment_id: str,
        target_uin: int,
        target_name: str,
        content: str,
    ) -> dict[str, Any]:
        """记录楼中楼回复并返回成功响应。"""
        self.calls.append(
            (
                "reply_comment",
                {
                    "host_uin": host_uin,
                    "tid": tid,
                    "root_comment_id": root_comment_id,
                    "target_uin": target_uin,
                    "target_name": target_name,
                    "content": content,
                },
            )
        )
        return {"code": 0}


def _install_direct_client(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeDirectClient,
) -> None:
    """把 Service 模块的直连依赖替换为测试替身。"""

    async def fake_fetch_cookie(expected_qq: int | str | None = None) -> str:
        """返回可解析出 p_skey 与 uin 的假 Cookie。"""
        del expected_qq
        return "p_skey=fake-skey; uin=o12345"

    class FakeDirectClientFactory:
        """按 Service 调用约定构造直连替身。"""

        @classmethod
        def create(cls, cookie_string: str) -> FakeDirectClient:
            """忽略 Cookie 字符串并返回共享替身。"""
            del cookie_string
            return client

    monkeypatch.setattr(
        service_module,
        "fetch_qzone_cookie_string",
        fake_fetch_cookie,
    )
    monkeypatch.setattr(service_module, "QZoneDirectClient", FakeDirectClientFactory)


@pytest.mark.asyncio
async def test_service_forwards_all_nine_qzone_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
    await service.delete_qzone_msg(
        tid=" tid-1 ",
        expected_author_qq=3693525299,
        confirmation="DELETE tid-1 3693525299 3693525299",
    )
    await service.like_qzone(tid="tid-2", target_uin=20001)
    await service.unlike_qzone(tid="tid-3", target_uin=20002)
    local_image = tmp_path / "comment.png"
    local_image.write_bytes(b"\x89PNG\r\n\x1a\n")
    await service.comment_qzone(
        tid="tid-4",
        content="带图评论",
        target_uin=20003,
        images=[local_image.as_uri()],
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
        "images": ["base64://iVBORw0KGgo="],
        "ugc_right": 16,
        "target_uins": [10001, 10002],
    }
    assert backend.calls[3][1] == {"tid": "tid-1"}


@pytest.mark.asyncio
async def test_service_forwards_detail_and_thread_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """详情和楼中楼应经校验后走本地直连客户端。"""
    _, service, backend = _build_runtime(monkeypatch)
    client = FakeDirectClient()
    client.msg_detail = {"tid": "detail-tid", "uin": 10001, "commentlist": []}
    _install_direct_client(monkeypatch, client)

    await service.get_qzone_msg_detail(tid=" detail-tid ", host_uin=10001)
    await service.reply_qzone_comment(
        tid=" reply-tid ",
        host_uin=10002,
        root_comment_id=" global-root-comment-id ",
        target_uin=10003,
        target_name=" 被回复者 ",
        content=" 楼中楼回复 ",
        self_uin=10004,
    )

    assert client.calls == [
        (
            "get_msg_detail",
            {"host_uin": 10001, "tid": "detail-tid"},
        ),
        (
            "reply_comment",
            {
                "host_uin": 10002,
                "tid": "reply-tid",
                "root_comment_id": "global-root-comment-id",
                "target_uin": 10003,
                "target_name": "被回复者",
                "content": "楼中楼回复",
            },
        ),
    ]
    # 直连路径不应触达 OneBot Expand 后端。
    assert backend.calls == []


@pytest.mark.asyncio
async def test_legacy_service_facade_filters_reads_and_uses_shared_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """原版 Service 门面应返回规范列表并复用插件级互动状态。"""
    _, service, backend = _build_runtime(monkeypatch)
    client = FakeDirectClient()
    client.user_feeds = [
        {"tid": "already-commented", "commentlist": []},
        {
            "tid": "feed-new",
            "content": "新动态",
            "commentlist": [
                {
                    "comment_id": "root-comment",
                    "uin": 20002,
                    "nickname": "访客",
                    "content": "一级评论",
                    "list_3": [
                        {
                            "comment_id": "child-comment",
                            "uin": 20003,
                            "nickname": "回复者",
                            "content": "楼中楼评论",
                            "list_3": [],
                        }
                    ],
                }
            ],
        },
    ]
    client.msg_detail = {
        "tid": "feed-new",
        "uin": 20001,
        "commentlist": [
            {
                "comment_id": "root-comment",
                "uin": 20002,
                "nickname": "访客",
                "content": "一级评论",
                "list_3": [
                    {
                        "comment_id": "child-comment",
                        "uin": 20003,
                        "nickname": "回复者",
                        "content": "楼中楼评论",
                        "list_3": [],
                    }
                ],
            }
        ],
    }
    _install_direct_client(monkeypatch, client)
    service.plugin.runtime.interaction_log.mark(
        "20001",
        "already-commented",
        "commented",
        "agent",
    )

    feeds = await service.list_feeds(
        target_qq="20001",
        num=2,
        skip_commented=True,
    )
    detail = await service.get_feed_detail("20001", "feed-new")
    commented = await service.comment("20001", "feed-new", "原版评论")

    assert [feed["tid"] for feed in feeds] == ["feed-new"]
    assert detail is not None
    assert detail["comments"] == [
        {
            "comment_tid": "root-comment",
            "parent_tid": "",
            "qq_account": "20002",
            "nickname": "访客",
            "content": "一级评论",
        },
        {
            "comment_tid": "child-comment",
            "parent_tid": "root-comment",
            "qq_account": "20003",
            "nickname": "回复者",
            "content": "楼中楼评论",
        },
    ]
    assert commented is True
    # 评论写入仍经 OneBot Expand 后端转发。
    assert backend.calls == [
        (
            "comment_qzone",
            {
                "tid": "feed-new",
                "content": "原版评论",
                "target_uin": 20001,
                "images": None,
            },
        )
    ]
    # 读取路径应走本地直连客户端。
    assert [action for action, _ in client.calls] == [
        "get_user_feeds",
        "get_msg_detail",
    ]


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
    monkeypatch.setattr(
        service_module,
        "discover_qzone_provider",
        lambda refresh=False: type(
            "Snapshot",
            (),
            {
                "provider": None,
                "diagnostic": "未发现任何协议端能力。",
                "source": None,
            },
        )(),
    )

    with pytest.raises(NeoFoxzoneError, match="当前协议端不可用"):
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


def test_plugin_registers_service_command_and_tools() -> None:
    """默认配置应注册基础能力、AI 生图发布入口和原版 Tool 名。"""
    plugin = NeoFoxzonePlugin(config=NeoFoxzoneConfig())
    names = [component.name for component in plugin.get_components()]

    assert names == [
        "qzone_service",
        "qzone_feedback",
        "qzone_activity",
        "neo-foxzone",
        "neo_foxzone_list_posts",
        "neo_foxzone_list_feeds",
        "neo_foxzone_read_detail",
        "neo_foxzone_describe_images",
        "qzone_read_feed",
        "neo_foxzone_publish",
        "neo_foxzone_publish_generated",
        "neo_foxzone_delete",
        "neo_foxzone_like",
        "neo_foxzone_unlike",
        "neo_foxzone_comment",
        "neo_foxzone_reply_comment",
        "neo_foxzone_set_blacklist",
        "neo_foxzone_set_visibility",
        "qzone_post_comment",
        "qzone_like_feed",
    ]
    assert all(
        component.dependencies == [SERVICE_SIGNATURE]
        for component in plugin.get_components()[1:]
    )
    assert plugin.plugin_version == "0.1.7"
    assert plugin.dependencies == []
    assert plugin.config.plugin.version == "0.1.7"


def test_plugin_revalidates_cached_config_after_module_reload() -> None:
    """A previous module's config class must retain settings after hot reload."""
    config = NeoFoxzoneConfig()
    config.plugin.enabled = False
    config.polling.enabled = False
    config.security.write_account_qq = "10003"

    class CachedConfig:
        def model_dump(self) -> dict[str, Any]:
            return config.model_dump()

    plugin = NeoFoxzonePlugin(config=CachedConfig())  # type: ignore[arg-type]
    assert isinstance(plugin.config, NeoFoxzoneConfig)
    assert plugin.config.security.write_account_qq == "10003"
    assert plugin.config.polling.enabled is False
    assert plugin.get_components() == []
    assert NeoFoxzoneService.version == "0.1.7"


def test_manifest_keeps_protocol_plugins_optional() -> None:
    """缺少 OneBot Expand 时插件清单仍允许其加载。"""
    manifest_path = Path(__file__).parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "neo-foxzone"
    assert manifest["version"] == "0.1.7"
    assert manifest["dependencies"]["plugins"] == []
    assert manifest["dependencies"]["components"] == []
    assert manifest["dependencies_required"] is False
    assert len(manifest["include"]) == 18


@pytest.mark.asyncio
async def test_write_is_blocked_when_login_account_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知登录账号时绝不调用写接口。"""
    _, service, backend = _build_runtime(monkeypatch)

    async def unknown_login(*, expected_qq: str | None = None) -> dict[str, Any]:
        del expected_qq
        return {"status": "unknown", "qq": None, "message": "实时接口不可用。"}

    monkeypatch.setattr(service_module, "get_current_login_info", unknown_login)
    with pytest.raises(NeoFoxzoneError, match="已阻止真实写操作"):
        await service.send_qzone_msg(content="must not be sent")
    assert backend.calls == []


def test_content_normalization_blocks_cq_injection_and_caps_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """写接口正文统一清理 CQ 标记、HTML 边界与超长输入。"""
    _, service, _ = _build_runtime(monkeypatch)

    normalized = service._normalize_content(" <b>[CQ:at,qq=1]</b>\x00 ", "正文")

    assert normalized == "&lt;b&gt;［CQ:at,qq=1]&lt;/b&gt;"
    service._config().limits.max_content_chars = 5
    with pytest.raises(NeoFoxzoneError, match="不能超过 5 个字符"):
        service._normalize_content("123456", "正文")


@pytest.mark.asyncio
async def test_image_normalization_rejects_private_and_local_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """图片引用不能将协议端导向回环、内网或云元数据地址。"""
    _, service, _ = _build_runtime(monkeypatch)

    for image in (
        "http://127.0.0.1/private.png",
        "http://192.168.1.20/image.png",
        "http://metadata.google.internal/latest/meta-data/",
        "file://server/share/image.png",
    ):
        with pytest.raises(NeoFoxzoneError):
            await service._normalize_images([image])


@pytest.mark.asyncio
async def test_image_dns_resolver_rejects_private_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """域名即使名称看似公开，DNS 返回私网地址时也会拒绝。"""
    resolver = service_module._PublicImageResolver()

    async def private_resolution(host: str, port: int, family: int):
        del host, port, family
        return [{"host": "127.0.0.1"}]

    monkeypatch.setattr(resolver._resolver, "resolve", private_resolution)
    try:
        with pytest.raises(OSError, match="非公网地址"):
            await resolver.resolve("public.example")
    finally:
        await resolver.close()


@pytest.mark.asyncio
async def test_publish_uses_normalized_body_before_forwarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发布调用转发前会执行统一正文安全处理。"""
    _, service, backend = _build_runtime(monkeypatch)

    await service.send_qzone_msg(content=" [CQ:face,id=1] <b>hi</b> ")

    assert backend.calls[0][1]["content"] == "［CQ:face,id=1] &lt;b&gt;hi&lt;/b&gt;"


@pytest.mark.asyncio
async def test_manual_writes_obey_minimum_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相邻写操作会遵守可配置的最小发送间隔。"""
    _, service, _ = _build_runtime(monkeypatch)
    service._config().limits.write_min_interval_seconds = 0.02
    clock = [100.0]
    delays = []

    async def sleep(delay):
        delays.append(delay)
        clock[0] += delay

    monkeypatch.setattr(service_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(service_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(service_module, "_LAST_WRITE_STARTED", 0.0)
    await service._respect_write_rate_limit()
    await service._respect_write_rate_limit()
    assert delays == [pytest.approx(0.02)]


@pytest.mark.asyncio
async def test_delete_requires_confirmed_own_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目标作者不是当前账号时，即使确认串格式正确也禁止删除。"""
    _, service, backend = _build_runtime(monkeypatch)

    async def foreign_post(tid: str, owner_uin: int) -> dict[str, Any]:
        return {"tid": tid, "uin": owner_uin + 1, "commentlist": []}

    monkeypatch.setattr(service, "_verified_post_detail", foreign_post)
    with pytest.raises(NeoFoxzoneError, match="不属于当前登录账号"):
        await service.delete_qzone_msg(
            tid="test-tid",
            expected_author_qq=3693525299,
            confirmation="DELETE test-tid 3693525299 3693525299",
        )
    assert backend.calls == []


@pytest.mark.asyncio
async def test_nested_reply_requires_top_level_comment_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """楼中楼目标必须是详情中明确存在的顶层评论。"""
    _, service, backend = _build_runtime(monkeypatch)

    async def no_comments(tid: str, owner_uin: int) -> dict[str, Any]:
        return {"tid": tid, "uin": owner_uin, "commentlist": []}

    monkeypatch.setattr(service, "_verified_post_detail", no_comments)
    with pytest.raises(NeoFoxzoneError, match="不是详情中的顶层评论"):
        await service.reply_qzone_comment(
            tid="post-tid",
            host_uin=20001,
            root_comment_id="unknown-comment",
            target_uin=20002,
            target_name="friend",
            content="reply",
        )
    assert backend.calls == []


@pytest.mark.asyncio
async def test_adapter_provider_is_used_without_qzone_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有 OneBot Expand Service 时，使用运行时发现的 QQ Adapter。"""
    calls: list[tuple[str, str, dict[str, Any]]] = []

    class FakeAdapter:
        platform = "qq"

        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr(providers_module.service_api, "get_all_services", lambda: {})
    monkeypatch.setattr(providers_module.service_api, "get_service", lambda _: None)
    monkeypatch.setattr(
        providers_module.adapter_api,
        "get_all_adapters",
        lambda: {"test_onebot:adapter:qq": FakeAdapter()},
    )

    async def send_adapter_command(
        *, adapter_sign: str, command_name: str, command_data: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        calls.append((adapter_sign, command_name, command_data))
        return {"status": "ok", "retcode": 0, "data": {"accepted": True}}

    monkeypatch.setattr(
        providers_module.adapter_api,
        "send_adapter_command",
        send_adapter_command,
    )
    snapshot = providers_module.discover_qzone_provider(refresh=True)
    assert snapshot.source == "test_onebot:adapter:qq"
    assert snapshot.provider is not None
    response = await snapshot.provider.send_qzone_msg(
        content="test",
        images=None,
        ugc_right=1,
        target_uins=None,
    )
    assert response["status"] == "ok"
    assert calls == [
        (
            "test_onebot:adapter:qq",
            "send_qzone_msg",
            {"content": "test", "ugc_right": 1},
        )
    ]


def test_multiple_qq_adapters_are_not_selected_arbitrarily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多个登录适配器同时在线时发现层不猜测读取或写入账号。"""
    class FakeAdapter:
        platform = "qq"

        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr(providers_module.service_api, "get_all_services", lambda: {})
    monkeypatch.setattr(providers_module.service_api, "get_service", lambda _: None)
    monkeypatch.setattr(
        providers_module.adapter_api,
        "get_all_adapters",
        lambda: {
            "snowluma:adapter:qq": FakeAdapter(),
            "napcat:adapter:qq": FakeAdapter(),
        },
    )

    snapshot = providers_module.discover_qzone_provider(refresh=True)

    assert snapshot.provider is None
    assert len(snapshot.adapter_signatures) == 2
    assert "多个" in snapshot.diagnostic


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
    """NAI Artist 通过公开 Service 契约提供图片，FoxZone 只做格式归一化。"""
    generated: list[dict[str, Any]] = []

    class FakeNaiService:
        """模拟 NAI Artist 的公共外部 Service 接口。"""

        async def generate_image_for_external(
            self, *, description: str, style: str
        ) -> str:
            generated.append({"description": description, "style": style})
            return "a" * 64

    monkeypatch.setattr(
        image_provider_module.service_api,
        "get_service",
        lambda signature: (
            FakeNaiService()
            if signature == image_provider_module.NAI_ARTIST_SERVICE_SIGNATURE
            else None
        ),
    )
    images = await image_provider_module.generate_images(
        NeoFoxzoneConfig(),
        "窗边晨光",
        "photo",
    )

    assert images == [f"base64://{'a' * 64}"]
    assert generated == [{"description": "窗边晨光", "style": "photo"}]


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


def test_feed_parser_recovers_thread_root_for_persisted_bot_comment() -> None:
    """父评论未展开时，应从持久化映射恢复真实顶层评论 ID。"""
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
        known_bot_comment_roots={
            "20001:friend-post": {
                "persisted-bot-comment": "global-root-comment-id"
            }
        },
    )

    assert [(item.post_id, item.comment_id) for item in candidates] == [
        ("friend-post", "friend-reply")
    ]
    assert candidates[0].root_comment_id == "global-root-comment-id"


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
async def test_runtime_preserves_original_plugin_state_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """插件级运行时应共享并保留原版 FoxZone 的持久化 JSON 形状。"""
    runtime_module = importlib.import_module(f"{PACKAGE}.runtime")
    stored: dict[tuple[str, str], dict[str, Any]] = {
        ("neo-foxzone", "reply_tracker"): {
            "data": {"feed-1": {"comment-1": 1234.5}}
        },
        ("neo-foxzone", "interaction_log"): {
            "log": {"20001:feed-1": {"liked": True, "source": "poll"}}
        },
        ("neo-foxzone", "vision_cache"): {
            "cache": {"https://example.test/old.png": "旧图片描述"}
        },
        ("neo-foxzone", "send_history"): {
            "records": [{"time": "2025-01-01 00:00:00", "text": "旧说说"}]
        },
        ("neo-foxzone", "polling_state"): {
            "processed_comment_ids": ["existing-comment"]
        },
    }

    async def load_json(
        store_name: str,
        name: str,
    ) -> dict[str, Any] | None:
        """返回内存中的隔离状态副本。"""
        payload = stored.get((store_name, name))
        return json.loads(json.dumps(payload)) if payload is not None else None

    async def save_json(
        store_name: str,
        name: str,
        data: dict[str, Any],
    ) -> None:
        """记录运行时写回的兼容状态。"""
        stored[(store_name, name)] = json.loads(json.dumps(data))

    monkeypatch.setattr(runtime_module.storage_api, "load_json", load_json)
    monkeypatch.setattr(runtime_module.storage_api, "save_json", save_json)

    runtime = runtime_module.NeoFoxzoneRuntime(polling_state_max_entries=8)
    await runtime.initialize()

    assert runtime.initialized is True
    assert runtime.reply_tracker.has_replied("feed-1", "comment-1") is True
    assert runtime.interaction_log.has_liked("20001", "feed-1") is True
    assert runtime.vision_cache.get("https://example.test/old.png") == "旧图片描述"
    assert runtime.polling_state.is_processed("existing-comment") is True

    await runtime.reply_tracker.mark_as_replied("feed-2", "comment-2")
    runtime.interaction_log.mark("20002", "feed-2", "commented", "agent")
    runtime.vision_cache.set("https://example.test/new.png", "新图片描述")
    await runtime.send_history.record("新说说")
    await runtime.shutdown()

    assert stored[("neo-foxzone", "reply_tracker")]["data"]["feed-2"] == {
        "comment-2": pytest.approx(
            stored[("neo-foxzone", "reply_tracker")]["data"]["feed-2"]["comment-2"]
        )
    }
    assert stored[("neo-foxzone", "interaction_log")]["log"]["20002:feed-2"][
        "commented"
    ] is True
    assert stored[("neo-foxzone", "vision_cache")]["cache"][
        "https://example.test/new.png"
    ] == "新图片描述"
    assert [record["text"] for record in stored[("neo-foxzone", "send_history")]["records"]] == [
        "旧说说",
        "新说说",
    ]


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
                                    "nickname": "旧访客",
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

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "content": "测试说说",
                    "commentlist": [
                        {
                            "comment_id": "old-comment",
                            "uin": 10001,
                            "nickname": "旧访客",
                            "content": "旧评论",
                            "list_3": [],
                        },
                        {
                            "comment_id": "new-comment",
                            "uin": 10002,
                            "nickname": "新访客",
                            "content": "新评论",
                            "list_3": [],
                        },
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
            assert snapshots[-1]["in_flight_comment_ids"] == [
                "own_post:99999:own-post:new-comment"
            ]
            self.comments.append(kwargs)
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
    state.mark_processed("own_post:99999:own-post:old-comment")
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
            "host_uin": 99999,
            "root_comment_id": "new-comment",
            "target_uin": 10002,
            "target_name": "新访客",
            "content": "回复 新评论",
            "self_uin": 99999,
        }
    ]
    assert report.candidates == 2
    assert report.skipped_processed == 1
    assert report.replied == 1
    assert report.failed == 0
    assert state.is_processed("own_post:99999:own-post:new-comment") is True
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
async def test_poller_enriches_snowluma_summaries_before_thread_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要列表必须先补全详情，再用顶层全局评论 ID 发送楼中楼回复。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    detail_calls: list[tuple[str, int]] = []
    reply_calls: list[dict[str, Any]] = []
    plain_comment_calls: list[dict[str, Any]] = []

    async def save_json(*args: Any, **kwargs: Any) -> None:
        """避免测试写入实际插件状态。"""

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    class SnowLumaSummaryService:
        """模拟只提供说说摘要、但支持详情兼容接口的 SnowLuma。"""

        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "content": "SnowLuma 摘要正文",
                            "comment_num": 1,
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            detail_calls.append((tid, host_uin))
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "content": "完整说说正文",
                    "commentlist": [
                        {
                            "comment_id": "global-root-comment-id",
                            "uin": 10001,
                            "nickname": "访客",
                            "content": "请回复我",
                            "list_3": [],
                        }
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
            reply_calls.append(kwargs)
            return {
                "status": "ok",
                "retcode": 0,
                "data": {"commentid": "bot-thread-reply-id"},
            }

        async def comment_qzone(self, **kwargs: Any) -> dict[str, Any]:
            plain_comment_calls.append(kwargs)
            raise AssertionError("详情路径可用时不得退回普通评论")

    async def generate_reply(candidate: Any) -> str:
        """返回固定回复，便于断言远端参数。"""
        assert candidate.comment_id == "global-root-comment-id"
        return "收到啦"

    poller = poller_module.QzoneReplyPoller(
        NeoFoxzonePlugin(config=NeoFoxzoneConfig()),
        service=SnowLumaSummaryService(),
        state=state_module.PollingState(),
        reply_generator=generate_reply,
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    report = await poller.poll_once()

    assert detail_calls == [("own-post", 99999)]
    assert plain_comment_calls == []
    assert reply_calls == [
        {
            "tid": "own-post",
            "host_uin": 99999,
            "root_comment_id": "global-root-comment-id",
            "target_uin": 10001,
            "target_name": "访客",
            "content": "收到啦",
            "self_uin": 99999,
        }
    ]
    assert report.candidates == 1
    assert report.replied == 1
    assert report.failed == 0


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
                                    "nickname": "访客",
                                    "content": "网络结果不明",
                                }
                            ],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "commentlist": [
                        {
                            "comment_id": "uncertain-comment",
                            "uin": 10001,
                            "nickname": "访客",
                            "content": "网络结果不明",
                            "list_3": [],
                        }
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
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

    identity = "own_post:99999:own-post:uncertain-comment"
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
                                    "nickname": "第一位访客",
                                    "content": "第一条",
                                },
                                {
                                    "commentid": "should-run-next",
                                    "uin": 10002,
                                    "nickname": "第二位访客",
                                    "content": "第二条",
                                },
                            ],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "commentlist": [
                        {
                            "comment_id": "always-fails",
                            "uin": 10001,
                            "nickname": "第一位访客",
                            "content": "第一条",
                            "list_3": [],
                        },
                        {
                            "comment_id": "should-run-next",
                            "uin": 10002,
                            "nickname": "第二位访客",
                            "content": "第二条",
                            "list_3": [],
                        },
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
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
    plugin.config.feedback.enabled = False
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
        return ["https://example.test/generated-image.png"]

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
                "images": ["base64://iVBORw0KGgo="],
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


@pytest.mark.asyncio
async def test_service_forwards_internal_user_feed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任意 QQ 读取应经本地直连客户端完整转发参数。"""
    _, service, backend = _build_runtime(monkeypatch)
    client = FakeDirectClient()
    _install_direct_client(monkeypatch, client)

    await service.get_qzone_user_feeds(
        host_uin=20001,
        pos=2,
        num=3,
        self_uin=10001,
    )

    assert client.calls == [
        (
            "get_user_feeds",
            {
                "host_uin": 20001,
                "pos": 2,
                "num": 3,
            },
        )
    ]
    # 直连路径不应触达 OneBot Expand 后端。
    assert backend.calls == []


def test_rate_limit_error_detection() -> None:
    """1012 与 -10049 文本都应识别为 QZone 频率限制。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    is_rate_limit_error = poller_module.is_rate_limit_error

    assert is_rate_limit_error(
        RuntimeError("QZone 请求失败（subcode=1012）: 使用人数过多，请稍后再试")
    )
    assert is_rate_limit_error(RuntimeError("QZone 限流（code=-10049）"))
    assert is_rate_limit_error("回复接口返回错误: code=-10049, subcode=-106")
    assert not is_rate_limit_error(RuntimeError("QZone 响应为空。"))
    assert not is_rate_limit_error(RuntimeError("评论正文不能为空。"))


@pytest.mark.asyncio
async def test_poller_stops_batch_and_backs_off_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """触发 QZone 频率限制后应终止本轮剩余候选并使用长退避。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    QzoneReplyPoller = poller_module.QzoneReplyPoller
    PollingState = state_module.PollingState

    async def save_json(
        store_name: str,
        name: str,
        data: dict[str, Any],
    ) -> None:
        """静默保存。"""

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    class FakeLogger:
        """收集日志。"""

        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, message: str) -> None:
            self.messages.append(message)

        def warning(self, message: str) -> None:
            self.messages.append(message)

        def error(self, message: str, **kwargs: Any) -> None:
            self.messages.append(message)

    fake_logger = FakeLogger()
    monkeypatch.setattr(poller_module, "logger", fake_logger)

    class FakePollingService:
        """两条新评论；第一条发送触发 1012 限流。"""

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
                            "comment_num": 2,
                            "commentlist": [],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(
            self,
            page_num: int = 1,
            count: int = 10,
        ) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "content": "测试说说",
                    "commentlist": [
                        {
                            "comment_id": "comment-1",
                            "uin": 20001,
                            "nickname": "访客一",
                            "content": "第一条",
                            "list_3": [],
                        },
                        {
                            "comment_id": "comment-2",
                            "uin": 20002,
                            "nickname": "访客二",
                            "content": "第二条",
                            "list_3": [],
                        },
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["target_uin"] == 20001:
                return {
                    "status": "failed",
                    "retcode": -1,
                    "data": None,
                    "msg": "QZone 请求失败（subcode=1012）: 使用人数过多，请稍后再试",
                }
            raise AssertionError("触发限流后不应继续处理剩余候选")

    async def generate_reply(candidate: Any) -> str:
        """返回固定回复。"""
        return f"回复 {candidate.comment_id}"

    async def load_bot_uin() -> int:
        """返回测试 Bot QQ。"""
        return 99999

    config = NeoFoxzoneConfig()
    plugin = NeoFoxzonePlugin(config=config)
    state = PollingState(max_entries=20)
    service = FakePollingService()
    poller = QzoneReplyPoller(
        plugin,
        service=service,
        state=state,
        reply_generator=generate_reply,
        bot_uin_loader=load_bot_uin,
    )

    report = await poller.poll_once()

    assert report.replied == 0
    assert report.failed == 1
    identity = "own_post:99999:own-post:comment-1"
    assert state.is_processed(identity) is False
    retry_after = state.retry_after(identity)
    # 限流退避（默认 120 分钟）应远大于普通失败退避（30 分钟起步）。
    assert retry_after > asyncio.get_event_loop().time() + 3600
    assert any(
        "频率限制" in message and "本轮剩余候选全部跳过" in message
        for message in fake_logger.messages
    )


@pytest.mark.asyncio
async def test_poller_uses_short_backoff_for_generation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 生成失败应使用短退避且不阻断本轮剩余候选。

    回归背景：LLM 网关 "Connection error." 曾按协议失败走 30 分钟起步的
    指数退避，26 次失败后全部候选退避到 8 小时后，自动回复完全停滞。
    """
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    QzoneReplyPoller = poller_module.QzoneReplyPoller
    PollingState = state_module.PollingState

    monkeypatch.setattr(
        state_module.storage_api,
        "save_json",
        lambda *args, **kwargs: asyncio.sleep(0),
    )

    class FakePollingService:
        """两条评论；生成阶段全部失败，发送阶段不应被触达。"""

        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "comment_num": 2,
                            "commentlist": [],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "commentlist": [
                        {
                            "comment_id": "comment-1",
                            "uin": 20001,
                            "nickname": "访客一",
                            "content": "第一条",
                            "list_3": [],
                        },
                        {
                            "comment_id": "comment-2",
                            "uin": 20002,
                            "nickname": "访客二",
                            "content": "第二条",
                            "list_3": [],
                        },
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("生成失败后不应进入发送阶段")

    async def generate_reply(candidate: Any) -> str:
        raise ConnectionError("Connection error.")

    config = NeoFoxzoneConfig()
    plugin = NeoFoxzonePlugin(config=config)
    state = PollingState(max_entries=20)
    poller = QzoneReplyPoller(
        plugin,
        service=FakePollingService(),
        state=state,
        reply_generator=generate_reply,
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    report = await poller.poll_once()

    # 两条候选都应被尝试（生成失败不终止本轮），且都记录失败。
    assert report.failed == 2
    assert report.replied == 0
    now = time.time()
    for identity in (
        "own_post:99999:own-post:comment-1",
        "own_post:99999:own-post:comment-2",
    ):
        retry_after = state.retry_after(identity)
        # 生成失败退避（默认 5 分钟）必须远小于普通失败退避（30 分钟起步）。
        assert now < retry_after <= now + 6 * 60
        assert state.is_in_flight(identity) is False


def test_polling_state_expires_stale_in_flight_reservations() -> None:
    """占用超过超时时间后应自动释放，允许候选重新处理。

    回归背景：发送异常后候选被永久占用（in_flight 无超时释放），
    后续每轮都被「上次发送结果不明」跳过。
    """
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    PollingState = state_module.PollingState

    state = PollingState()
    state.in_flight_timeout_seconds = 3600.0
    state.reserve("stale-comment")
    assert state.is_in_flight("stale-comment") is True

    # 模拟占用发生在超时时间之前。
    state.in_flight_reserved_at["stale-comment"] = time.time() - 7200.0

    assert state.is_in_flight("stale-comment") is False
    assert "stale-comment" not in state.in_flight_comment_ids
    assert "stale-comment" not in state.in_flight_reserved_at


@pytest.mark.asyncio
async def test_poller_jitters_between_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一轮内第二条及以后的回复发送前应有随机抖动等待。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    QzoneReplyPoller = poller_module.QzoneReplyPoller
    PollingState = state_module.PollingState

    sleep_calls: list[float] = []
    real_sleep = poller_module.asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(poller_module.asyncio, "sleep", fake_sleep)

    async def save_json(
        store_name: str,
        name: str,
        data: dict[str, Any],
    ) -> None:
        """静默保存。"""

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    class FakeLogger:
        """静默日志。"""

        def info(self, message: str) -> None:
            pass

        def warning(self, message: str) -> None:
            pass

        def error(self, message: str, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr(poller_module, "logger", FakeLogger())

    class FakePollingService:
        """两条新评论，全部可成功回复。"""

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
                            "comment_num": 2,
                            "commentlist": [],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(
            self,
            page_num: int = 1,
            count: int = 10,
        ) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "content": "测试说说",
                    "commentlist": [
                        {
                            "comment_id": "comment-1",
                            "uin": 30001,
                            "nickname": "访客一",
                            "content": "第一条",
                            "list_3": [],
                        },
                        {
                            "comment_id": "comment-2",
                            "uin": 30002,
                            "nickname": "访客二",
                            "content": "第二条",
                            "list_3": [],
                        },
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {"comment_id": f"bot-{kwargs['target_uin']}"},
            }

    async def generate_reply(candidate: Any) -> str:
        """返回固定回复。"""
        return f"回复 {candidate.comment_id}"

    async def load_bot_uin() -> int:
        """返回测试 Bot QQ。"""
        return 99999

    config = NeoFoxzoneConfig()
    plugin = NeoFoxzonePlugin(config=config)
    state = PollingState(max_entries=20)
    poller = QzoneReplyPoller(
        plugin,
        service=FakePollingService(),
        state=state,
        reply_generator=generate_reply,
        bot_uin_loader=load_bot_uin,
    )

    report = await poller.poll_once()

    assert report.replied == 2
    # 详情节流（1 条间隔）+ 发送抖动（1 次间隔）。
    assert len(sleep_calls) >= 1
    jitter_sleeps = [
        delay
        for delay in sleep_calls
        if config.polling.send_jitter_seconds_min <= delay
    ]
    assert len(jitter_sleeps) == 1


@pytest.mark.asyncio
async def test_poller_enriches_html_friend_feeds_via_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SnowLuma 好友动态只有预渲染 html 时，也必须发起详情补全。

    回归背景：好友动态条目没有任何结构化评论字段时曾被直接跳过，
    导致好友说说下的评论永远不会被发现（可回复候选恒为 0）。
    """
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    detail_calls: list[tuple[str, int]] = []
    reply_calls: list[dict[str, Any]] = []

    async def save_json(*args: Any, **kwargs: Any) -> None:
        """避免测试写入实际插件状态。"""

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    class FakeLogger:
        """静默日志。"""

        def info(self, message: str) -> None:
            pass

        def warning(self, message: str) -> None:
            pass

        def error(self, message: str, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr(poller_module, "logger", FakeLogger())

    class HtmlFriendFeedService:
        """好友动态仅返回预渲染 html，无结构化评论。"""

        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"msglist": []}}

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "feeds": [
                        {
                            "appid": "311",
                            "uin": 2295127191,
                            "key": "friend-post-1",
                            "nickname": "好友甲",
                            "html": "<div>预渲染动态</div>",
                        },
                        {
                            "appid": "6600",
                            "uin": 0,
                            "key": "advertisement_outlink_0",
                            "html": "<div>广告</div>",
                        },
                    ]
                },
            }

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            detail_calls.append((tid, host_uin))
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "tid": tid,
                    "uin": host_uin,
                    "content": "好友说说正文",
                    "commentlist": [
                        {
                            "comment_id": "friend-comment-1",
                            "uin": 3893256464,
                            "nickname": "评论者",
                            "content": "好看",
                            "list_3": [],
                        }
                    ],
                },
            }

        async def reply_qzone_comment(self, **kwargs: Any) -> dict[str, Any]:
            reply_calls.append(kwargs)
            return {
                "status": "ok",
                "retcode": 0,
                "data": {"comment_id": "bot-thread-reply"},
            }

    async def generate_reply(candidate: Any) -> str:
        """返回固定回复。"""
        return "谢谢关注"

    poller = poller_module.QzoneReplyPoller(
        NeoFoxzonePlugin(config=NeoFoxzoneConfig()),
        service=HtmlFriendFeedService(),
        state=state_module.PollingState(),
        reply_generator=generate_reply,
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    report = await poller.poll_once()

    # appid=311 的 html 好友动态必须触发详情补全；appid=6600 的广告跳过。
    assert detail_calls == [("friend-post-1", 2295127191)]
    # 详情返回的是好友自己顶层评论（非回复 bot 的评论），不会生成候选；
    # 这里验证的是详情链路打通而非回复行为。
    assert report.candidates == 0
    assert reply_calls == []


@pytest.mark.asyncio
async def test_poller_skips_detail_storm_during_rate_limit_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """限流冷却期内不得发起详情补全，避免风控窗口内继续打请求。"""
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    QzoneReplyPoller = poller_module.QzoneReplyPoller
    PollingState = state_module.PollingState
    detail_calls: list[tuple[str, int]] = []

    async def save_json(*args: Any, **kwargs: Any) -> None:
        """避免测试写入实际插件状态。"""

    monkeypatch.setattr(state_module.storage_api, "save_json", save_json)

    class FakeLogger:
        """收集日志。"""

        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, message: str) -> None:
            self.messages.append(message)

        def warning(self, message: str) -> None:
            self.messages.append(message)

        def error(self, message: str, **kwargs: Any) -> None:
            self.messages.append(message)

    monkeypatch.setattr(poller_module, "logger", FakeLogger())

    class FakePollingService:
        """摘要中有待补全的说说，但冷却期内不应触发详情。"""

        async def get_qzone_msg_list(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "msglist": [
                        {
                            "tid": "own-post",
                            "content": "测试说说",
                            "comment_num": 1,
                            "commentlist": [],
                        }
                    ]
                },
            }

        async def get_qzone_feeds(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

        async def get_qzone_msg_detail(
            self,
            tid: str,
            host_uin: int,
        ) -> dict[str, Any]:
            detail_calls.append((tid, host_uin))
            return {
                "status": "ok",
                "retcode": 0,
                "data": {"tid": tid, "uin": host_uin, "commentlist": []},
            }

    state = PollingState(max_entries=20)
    state.record_rate_limit_cooldown(time.time() + 3600.0)
    poller = QzoneReplyPoller(
        NeoFoxzonePlugin(config=NeoFoxzoneConfig()),
        service=FakePollingService(),
        state=state,
        reply_generator=lambda candidate: asyncio.sleep(0, result="收到"),
        bot_uin_loader=lambda: asyncio.sleep(0, result=99999),
    )

    report = await poller.poll_once()

    assert detail_calls == []
    assert report.candidates == 0
    assert report.failed == 0
    assert state.rate_limit_cooldown_until > time.time()
    # 冷却标记持久化字段存在。
    assert state.rate_limit_cooldown_active() is True


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_detail_rate_limit_stops_queries(raises: bool) -> None:
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    calls: list[str] = []

    class LimitedService:
        async def get_qzone_msg_detail(self, tid: str, host_uin: int):
            calls.append(tid)
            message = "QZone 请求失败（subcode=1012）"
            if raises:
                raise RuntimeError(message)
            return {"status": "failed", "retcode": -1, "msg": message}

    config = NeoFoxzoneConfig()
    config.polling.detail_request_interval_seconds = 0
    state = state_module.PollingState()
    poller = poller_module.QzoneReplyPoller(
        NeoFoxzonePlugin(config=config), service=LimitedService(), state=state,
    )
    report = poller_module.PollReport()
    await poller._detail_candidates(
        posts=[{"tid": "first", "comment_num": 1},
               {"tid": "second", "comment_num": 1}],
        source="own_post", bot_uin=99999, known_bot_comments={},
        known_bot_comment_roots={}, report=report,
    )
    assert calls == ["first"]
    assert len(report.query_errors) == 1
    assert state.rate_limit_cooldown_active()


@pytest.mark.asyncio
async def test_poller_uses_direct_list_comment_tree() -> None:
    poller_module = importlib.import_module(f"{PACKAGE}.poller")
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    calls: list[dict[str, Any]] = []

    class DirectService:
        async def get_qzone_user_feeds(self, **kwargs: Any):
            calls.append(kwargs)
            return {"status": "ok", "retcode": 0, "data": {"msglist": [{
                "tid": "own-post", "uin": 99999, "content": "测试", "comment_num": 1,
                "commentlist": [{"comment_id": "1", "uin": 12345,
                                 "nickname": "访客", "content": "你好", "list_3": []}],
            }]}}

        async def get_qzone_msg_detail(self, tid: str, host_uin: int):
            raise AssertionError("完整评论树不应重复查询详情")

        async def get_qzone_feeds(self, **kwargs: Any):
            return {"status": "ok", "retcode": 0, "data": {"feeds": []}}

    poller = poller_module.QzoneReplyPoller(
        NeoFoxzonePlugin(config=NeoFoxzoneConfig()), service=DirectService(),
        state=state_module.PollingState(),
    )
    report = poller_module.PollReport()
    candidates = await poller._query_candidates(99999, report)
    assert not report.query_errors
    assert calls[0]["host_uin"] == 99999
    assert len(candidates) == 1
    assert candidates[0].detail_verified
    assert candidates[0].root_comment_id == "1"


def test_rate_limit_cooldown_persists_and_expires() -> None:
    """限流冷却时间戳应随状态保存并可随时间过期。"""
    state_module = importlib.import_module(f"{PACKAGE}.polling_state")
    state = state_module.PollingState()
    assert state.rate_limit_cooldown_active() is False
    state.record_rate_limit_cooldown(time.time() + 60.0)
    assert state.rate_limit_cooldown_active() is True
    # 不会缩短已有的更长冷却。
    state.record_rate_limit_cooldown(time.time() + 10.0)
    assert state.rate_limit_cooldown_until > time.time() + 30.0
    state.record_rate_limit_cooldown(0.0)
    assert state.rate_limit_cooldown_until > 0


@pytest.mark.asyncio
async def test_llm_command_does_not_publish_after_generation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider limits must not turn a user's topic into a fake generated post."""
    plugin, service, backend = _build_runtime(monkeypatch)

    async def fail_story(self: Any, topic: str = "", recent_posts: str = "") -> str:
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(service_module.ContentService, "generate_story", fail_story)
    command = NeoFoxzoneCommand(plugin, stream_id="test")
    success, result = await command.handle_send_private("must not publish")

    assert success is False
    assert "429" in result
    assert backend.calls == []


@pytest.mark.asyncio
async def test_reply_tool_blocks_an_unconfirmed_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The LLM entry point retains the service's thread verification gate."""
    plugin, service, backend = _build_runtime(monkeypatch)
    tool = tools_module.NeoFoxzoneReplyCommentTool(plugin)
    success, result = await tool.execute(
        tid="test-post", host_uin=3693525299, root_comment_id="unknown-root",
        target_uin=10003, target_name="test", content="must not send",
    )

    assert success is False
    assert "顶层" in str(result)
    assert backend.calls == []


@pytest.mark.asyncio
async def test_command_route_sends_its_result_back_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core dispatch only executes commands; the plugin must deliver feedback."""
    sent: list[dict[str, Any]] = []
    plugin = NeoFoxzonePlugin(config=NeoFoxzoneConfig())
    plugin.config.feedback.enabled = False
    command = NeoFoxzoneCommand(plugin, stream_id="test-stream", message_id="incoming-id")

    async def status() -> tuple[bool, str]:
        return True, "test status"

    async def send_text(content: str, **kwargs: Any) -> bool:
        sent.append({"content": content, **kwargs})
        return True

    command._root.children["status"].handler = status
    monkeypatch.setattr(commands_module.send_api, "send_text", send_text)
    assert await command.execute("status") == (True, "test status")
    assert sent == [{"content": "✅ test status", "stream_id": "test-stream", "reply_to": "incoming-id"}]
