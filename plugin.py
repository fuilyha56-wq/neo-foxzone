"""Neo FoxZone 插件入口。"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from src.app.plugin_system.api import service_api
from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.concurrency import get_task_manager
from src.kernel.logger import get_logger

from . import (
    ACCOUNT_SERVICE_SIGNATURE,
    BACKEND_SERVICE_SIGNATURE,
    SERVICE_SIGNATURE,
)
from .commands import NeoFoxzoneCommand
from .config import NeoFoxzoneConfig
from .poller import PollReport, QzoneReplyPoller, create_poller
from .polling_state import PollingState
from .service import NeoFoxzoneService
from .tools import READ_TOOLS, WRITE_TOOLS

logger = get_logger("neo_foxzone.plugin")


@register_plugin
class NeoFoxzonePlugin(BasePlugin):
    """装配基于 OneBot Expand 的 QQ 空间说说能力。"""

    plugin_name = "neo-foxzone"
    plugin_description = "基于 OneBot Expand 的 QQ 空间说说全功能插件"
    plugin_version = "0.1.0"
    configs = [NeoFoxzoneConfig]
    dependencies = [BACKEND_SERVICE_SIGNATURE, ACCOUNT_SERVICE_SIGNATURE]

    def __init__(self, config: NeoFoxzoneConfig | None = None) -> None:
        """初始化轮询任务引用。"""
        super().__init__(config)
        self._poller: QzoneReplyPoller | None = None
        self._poll_task_id: str | None = None
        self._poll_task: asyncio.Task[Any] | None = None

    def _config(self) -> NeoFoxzoneConfig:
        """返回当前配置，异常装配时使用默认配置。"""
        if isinstance(self.config, NeoFoxzoneConfig):
            return self.config
        return NeoFoxzoneConfig()

    def get_components(self) -> list[type]:
        """按配置返回 Neo FoxZone 组件。"""
        config = (
            self.config
            if isinstance(self.config, NeoFoxzoneConfig)
            else NeoFoxzoneConfig()
        )
        if not config.plugin.enabled:
            return []
        components: list[type] = [NeoFoxzoneService]
        if config.components.command_enabled:
            components.append(NeoFoxzoneCommand)
        if config.components.read_tools_enabled:
            components.extend(READ_TOOLS)
        if config.components.write_tools_enabled:
            components.extend(WRITE_TOOLS)
        return components

    async def _run_poll_loop(self) -> None:
        """启动即检查，并按配置间隔持续轮询。"""
        poller = self._poller
        if poller is None:
            return
        config = self._config().polling
        if config.startup_check:
            try:
                report = await poller.poll_once()
                logger.info(
                    "Neo FoxZone 启动检查完成: "
                    f"候选={report.candidates}, 回复={report.replied}, "
                    f"失败={report.failed}, 查询错误={len(report.query_errors)}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error(
                    f"Neo FoxZone 启动检查异常: {error}",
                    exc_info=error,
                )

        while True:
            interval_seconds = max(1.0, float(config.interval_minutes) * 60.0)
            await asyncio.sleep(interval_seconds)
            try:
                report = await poller.poll_once()
                logger.info(
                    "Neo FoxZone 定时检查完成: "
                    f"候选={report.candidates}, 回复={report.replied}, "
                    f"失败={report.failed}, 查询错误={len(report.query_errors)}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error(
                    f"Neo FoxZone 定时检查异常: {error}",
                    exc_info=error,
                )

    async def on_plugin_loaded(self) -> None:
        """加载持久状态并注册自动回复守护任务。"""
        config = self._config()
        if not config.plugin.enabled or not config.polling.enabled:
            return
        raw_service = service_api.get_service(SERVICE_SIGNATURE)
        if raw_service is None:
            logger.warning("Neo FoxZone Service 未注册，跳过自动回复轮询。")
            return
        try:
            state = await PollingState.load(
                max_entries=max(1, int(config.polling.state_max_entries))
            )
        except Exception as error:
            logger.error(
                f"Neo FoxZone 轮询状态加载失败，已停止自动回复: {error}",
                exc_info=error,
            )
            return
        self._poller = create_poller(
            self,
            cast(NeoFoxzoneService, raw_service),
            state,
        )
        task = get_task_manager().create_task(
            self._run_poll_loop(),
            name="neo_foxzone_reply_poller",
            daemon=True,
        )
        self._poll_task_id = task.task_id
        self._poll_task = task.task

    async def on_plugin_unloaded(self) -> None:
        """取消自动回复守护任务并清理运行时引用。"""
        task = self._poll_task
        if self._poll_task_id is not None:
            get_task_manager().cancel_task(self._poll_task_id)
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.error(
                    f"Neo FoxZone 轮询任务退出异常: {error}",
                    exc_info=error,
                )
        self._poll_task_id = None
        self._poll_task = None
        self._poller = None

    async def poll_now(self) -> PollReport:
        """复用当前轮询器执行一次手动检查。"""
        if self._poller is None:
            raise RuntimeError("自动回复轮询器未启用或尚未初始化。")
        return await self._poller.poll_once()

    def get_poll_report(self) -> PollReport | None:
        """返回最近一次自动或手动轮询报告。"""
        if self._poller is None:
            return None
        return self._poller.last_report


__all__ = ["NeoFoxzonePlugin"]