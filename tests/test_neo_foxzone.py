"""Neo FoxZone 跨插件契约测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

PACKAGE = "plugins.neo-foxzone"
constants = importlib.import_module(PACKAGE)
commands_module = importlib.import_module(f"{PACKAGE}.commands")
config_module = importlib.import_module(f"{PACKAGE}.config")
plugin_module = importlib.import_module(f"{PACKAGE}.plugin")
service_module = importlib.import_module(f"{PACKAGE}.service")
tools_module = importlib.import_module(f"{PACKAGE}.tools")

BACKEND_SIGNATURE = constants.BACKEND_SERVICE_SIGNATURE
SERVICE_SIGNATURE = constants.SERVICE_SIGNATURE
NeoFoxzoneCommand = commands_module.NeoFoxzoneCommand
NeoFoxzoneConfig = config_module.NeoFoxzoneConfig
NeoFoxzonePlugin = plugin_module.NeoFoxzonePlugin
NeoFoxzoneError = service_module.NeoFoxzoneError
NeoFoxzoneService = service_module.NeoFoxzoneService


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
        page_num: int = 0,
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
        content="",
        images=[" https://example.test/a.jpg "],
        ugc_right=16,
        target_uins=[10001, 10001, 10002],
    )
    await service.delete_qzone_msg(tid=" tid-1 ")
    await service.like_qzone(tid="tid-2", target_uin=20001)
    await service.unlike_qzone(tid="tid-3", target_uin=20002)
    await service.comment_qzone(
        tid="tid-4",
        content="",
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
        "content": "",
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


def test_plugin_registers_service_command_and_nine_tools() -> None:
    """默认配置应注册全部用户入口。"""
    plugin = NeoFoxzonePlugin(config=NeoFoxzoneConfig())
    names = [component.name for component in plugin.get_components()]

    assert names == [
        "neo_foxzone_service",
        "neofoxzone",
        "neo_foxzone_list_posts",
        "neo_foxzone_list_feeds",
        "neo_foxzone_publish",
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


def test_manifest_declares_market_and_runtime_dependency() -> None:
    """Manifest 应同时声明插件级依赖与组件级依赖。"""
    manifest_path = Path(__file__).parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "neo-foxzone"
    assert manifest["dependencies"]["plugins"] == [
        "onebot_expand>=1.0.13"
    ]
    assert manifest["dependencies"]["components"] == [BACKEND_SIGNATURE]
    assert manifest["dependencies_required"] is True
    assert len(manifest["include"]) == 12