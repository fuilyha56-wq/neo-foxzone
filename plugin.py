"""Neo FoxZone 插件入口。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, cast

from src.app.plugin_system.api import adapter_api, service_api
from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.concurrency import get_task_manager
from src.kernel.logger import get_logger

from . import SERVICE_SIGNATURE
from .commands import NeoFoxzoneCommand
from .config import NeoFoxzoneConfig
from .autopilot.engine import AutonomousEngine, AutonomousScheduler
from .poller import PollReport, QzoneReplyPoller, create_poller
from .polling_state import PollingState  # noqa: F401  兼容旧测试注入点
from .runtime import NeoFoxzoneRuntime
from .service import NeoFoxzoneService
from .tools import READ_TOOLS, WRITE_TOOLS
from .feedback import ADAPTER_SIGNATURE, ActivityBridge, ActivityStore, QzoneActivityChatter, QzoneFeedbackAdapter

logger = get_logger("neo_foxzone.plugin")


def _interval_label(interval_seconds: float) -> str:
    """把轮询秒数格式化为适合日志展示的时间间隔。"""
    if interval_seconds >= 60.0 and interval_seconds % 60.0 == 0:
        return f"{int(interval_seconds / 60.0)} 分钟"
    return f"{interval_seconds:g} 秒"


@register_plugin
class NeoFoxzonePlugin(BasePlugin):
    """装配可选协议端上的 QQ 空间说说能力。"""

    plugin_name = "neo-foxzone"
    plugin_description = "自动发现兼容 QZone Service 或 OneBot Adapter 的 QQ 空间插件"
    plugin_version = "0.1.7"
    configs = [NeoFoxzoneConfig]
    # 协议端在运行时发现，缺少 OneBot Expand 不阻止插件注册。
    dependencies: list[str] = []

    def __init__(self, config: NeoFoxzoneConfig | None = None) -> None:
        """初始化共享运行时和轮询任务引用。"""
        # 核心热重载保留配置缓存；旧模块的模型实例应按当前模型重新验证。
        if config is not None and not isinstance(config, NeoFoxzoneConfig):
            config = NeoFoxzoneConfig.model_validate(config.model_dump())
        super().__init__(config)
        state_max_entries = max(1, int(self._config().polling.state_max_entries))
        self.runtime = NeoFoxzoneRuntime(
            polling_state_max_entries=state_max_entries
        )
        self._poller: QzoneReplyPoller | None = None
        self._poll_task_id: str | None = None
        self._poll_task: asyncio.Task[Any] | None = None
        self._autonomous_task_ids: list[str] = []
        self._autonomous_tasks: list[asyncio.Task[Any]] = []
        self._scheduler: AutonomousScheduler | None = None
        self.feedback_store = ActivityStore(state_max_entries)
        self._activity_bridge: ActivityBridge | None = None

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
        if config.feedback.enabled:
            components.extend([QzoneFeedbackAdapter, QzoneActivityChatter])
        if config.components.command_enabled:
            components.append(NeoFoxzoneCommand)
        if config.components.read_tools_enabled:
            components.extend(READ_TOOLS)
        if config.components.write_tools_enabled:
            components.extend(WRITE_TOOLS)
        return components

    async def _run_poll_loop(self) -> None:
        """启动即检查，并按配置间隔持续轮询。"""
        poller = self._activity_bridge or self._poller
        if poller is None:
            return
        config = self._config().polling
        if config.startup_check:
            logger.info(
                "Neo FoxZone 启动检查开始: "
                "正在读取自身说说与好友动态并检查可回复评论。"
            )
            try:
                report = await poller.poll_once()
                logger.info(
                    "Neo FoxZone 启动检查完成: "
                    f"候选={report.candidates}, 回复={report.replied}, "
                    f"失败={report.failed}, 查询错误={len(report.query_errors)}"
                )
                for error in report.query_errors:
                    logger.warning(f"Neo FoxZone 启动检查查询错误: {error}")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error(
                    f"Neo FoxZone 启动检查异常: {error}",
                    exc_info=error,
                )
        else:
            logger.info("Neo FoxZone 已按配置跳过启动检查。")

        while True:
            interval_seconds = max(1.0, float(config.interval_minutes) * 60.0)
            interval = _interval_label(interval_seconds)
            next_run = datetime.now().astimezone() + timedelta(
                seconds=interval_seconds
            )
            logger.info(
                f"Neo FoxZone 下次定时检查将在 {interval}后执行: "
                f"预计时间={next_run:%Y-%m-%d %H:%M:%S %z}。"
            )
            await asyncio.sleep(interval_seconds)
            logger.info(
                "Neo FoxZone 定时检查开始: "
                "正在读取自身说说与好友动态并检查可回复评论。"
            )
            try:
                report = await poller.poll_once()
                logger.info(
                    "Neo FoxZone 定时检查完成: "
                    f"候选={report.candidates}, 回复={report.replied}, "
                    f"失败={report.failed}, 查询错误={len(report.query_errors)}"
                )
                for error in report.query_errors:
                    logger.warning(f"Neo FoxZone 定时检查查询错误: {error}")
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
        if not config.plugin.enabled:
            logger.info(
                "Neo FoxZone 运行时未启动: "
                f"plugin.enabled={config.plugin.enabled}。"
            )
            return
        await self._stop_feedback_streams()
        try:
            await self.runtime.initialize()
        except Exception as error:
            logger.error(
                f"Neo FoxZone 共享状态加载失败，已停止启动: {error}",
                exc_info=error,
            )
            return
        raw_service = service_api.get_service(SERVICE_SIGNATURE)
        if raw_service is None:
            logger.warning("Neo FoxZone Service 未注册，跳过后台任务启动。")
            return
        if config.polling.enabled:
            self._poller = create_poller(
                self,
                cast(NeoFoxzoneService, raw_service),
                self.runtime.polling_state,
            )
            if config.feedback.enabled:
                await self.feedback_store.load()
                self._activity_bridge = ActivityBridge(self, self._poller, raw_service)
                if not await adapter_api.start_adapter(ADAPTER_SIGNATURE):
                    logger.warning("空间消息适配器暂未启动；保留待处理活动，稍后重试。")
            task = get_task_manager().create_task(
                self._run_poll_loop(),
                name="neo_foxzone_reply_poller",
                daemon=True,
            )
            self._poll_task_id = task.task_id
            self._poll_task = task.task
            logger.info(
                "Neo FoxZone 自动回复轮询已启动: "
                f"启动检查={config.polling.startup_check}, "
                f"间隔={config.polling.interval_minutes:g} 分钟, "
                f"自身说说={config.polling.own_posts_count} 条, "
                f"好友动态={config.polling.friend_feeds_count} 条, "
                f"单轮最多回复={config.polling.max_replies_per_poll} 条, "
                f"任务ID={task.task_id}。"
            )
        else:
            logger.info("Neo FoxZone 自动回复轮询已按配置禁用。")
        scheduler = AutonomousScheduler(
                AutonomousEngine(
                    cast(NeoFoxzoneService, raw_service),
                    self.runtime,
                    config,
                ),
                config,
            )
        self._scheduler = scheduler
        if config.general.enabled:
            operations = (
                (scheduler.engine.run_self_comments, "self_comments"),
                (scheduler.engine.run_external_followups, "external_followups"),
                (scheduler.engine.run_friend_monitor, "friend_monitor"),
            )
            if config.general.startup_check:
                for operation, name in operations:
                    if config.feedback.enabled and (name != "friend_monitor" or config.feedback.include_friend_posts):
                        continue
                    try:
                        await scheduler.run_once(operation, name)
                    except Exception as error:
                        logger.warning(f"FoxZone 自治启动任务 {name} 异常: {error}")
            for operation, name in operations:
                if config.feedback.enabled and (name != "friend_monitor" or config.feedback.include_friend_posts):
                    continue
                if not scheduler.enabled(name):
                    continue
                autonomous_task = get_task_manager().create_task(
                    scheduler.run_loop(operation, name),
                    name=f"neo_foxzone_{name}",
                    daemon=True,
                )
                self._autonomous_task_ids.append(autonomous_task.task_id)
                if autonomous_task.task is not None:
                    self._autonomous_tasks.append(autonomous_task.task)
            logger.info(
                "FoxZone 三条自治任务已启动: "
                f"任务数={len(self._autonomous_task_ids)}。"
            )
        else:
            logger.info("FoxZone 自治任务已按配置禁用。")

    async def on_plugin_unloaded(self) -> None:
        """取消自动回复守护任务并清理运行时引用。"""
        await self._stop_feedback_streams()
        for task_id in self._autonomous_task_ids:
            get_task_manager().cancel_task(task_id)
        for task in self._autonomous_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.error(
                    f"FoxZone 自治任务退出异常: {error}",
                    exc_info=error,
                )
        self._autonomous_task_ids.clear()
        self._autonomous_tasks.clear()
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
        self._scheduler = None
        self._activity_bridge = None
        if self._config().feedback.enabled:
            await adapter_api.stop_adapter(ADAPTER_SIGNATURE)
            await self.feedback_store.save()
        try:
            await self.runtime.shutdown()
        except Exception as error:
            logger.error(
                f"Neo FoxZone 共享状态保存失败: {error}",
                exc_info=error,
            )

    async def _stop_feedback_streams(self) -> None:
        """热重载时停止本插件会话，避免旧 Chatter 持有旧运行时继续写入。"""
        from src.core.managers.chatter_manager import get_chatter_manager
        from src.core.transport.distribution.stream_loop_manager import get_stream_loop_manager
        manager = get_chatter_manager()
        for stream_id, chatter in manager.get_active_chatters().items():
            if chatter.name == "qzone_activity" and getattr(chatter.plugin, "plugin_name", "") == self.plugin_name:
                await get_stream_loop_manager().stop_stream_loop(stream_id)
                manager.unregister_active_chatter(stream_id)

    async def poll_now(self) -> PollReport:
        """复用当前轮询器执行一次手动检查。"""
        if self._poller is None:
            raise RuntimeError("自动回复轮询器未启用或尚未初始化。")
        if self._activity_bridge is not None:
            return await self._activity_bridge.poll_once()
        return await self._poller.poll_once()

    def get_feedback_status(self) -> dict[str, object]:
        """返回真实消息桥的运行状态与能力边界。"""
        return {"enabled": self._config().feedback.enabled,
                "adapter_active": adapter_api.get_adapter(ADAPTER_SIGNATURE) is not None,
                "native_unread_supported": False,
                "pending_events": self.feedback_store.pending_count(),
                "last_report": self._activity_bridge.last_report if self._activity_bridge else None}

    def get_poll_report(self) -> PollReport | None:
        """返回最近一次自动或手动轮询报告。"""
        if self._poller is None:
            return None
        return self._poller.last_report

    async def run_autonomous_now(self, flow: str) -> dict[str, object]:
        """运营者手动执行单条自治流程，保留独立开关和免打扰检查。"""
        scheduler = self._scheduler
        if scheduler is None:
            raise RuntimeError("自治引擎尚未初始化。")
        operations = {
            "self_comments": scheduler.engine.run_self_comments,
            "friend_monitor": scheduler.engine.run_friend_monitor,
            "external_followups": scheduler.engine.run_external_followups,
        }
        if flow not in operations:
            raise ValueError("flow 必须为 self_comments、friend_monitor 或 external_followups。")
        await scheduler.run_once(operations[flow], flow)
        return dict(self.runtime.autonomous_reports.get(flow, {}))

    def get_autonomous_status(self) -> dict[str, object]:
        """返回三条自治流程的开关、最近结果与实际后台任务数量。"""
        config = self._config()
        return {"background_enabled": config.general.enabled,
                "background_tasks_running": sum(not task.done() for task in self._autonomous_tasks),
                "cooldown_active": self.runtime.polling_state.rate_limit_cooldown_active(),
                "flows": {name: {"enabled": self._scheduler.enabled(name) if self._scheduler else False,
                                 "last_report": self.runtime.autonomous_reports.get(name)}
                          for name in ("self_comments", "friend_monitor", "external_followups")}}


__all__ = ["NeoFoxzonePlugin"]
