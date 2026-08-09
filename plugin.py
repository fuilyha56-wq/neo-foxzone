"""Neo FoxZone 插件入口。"""

from __future__ import annotations

from src.app.plugin_system.base import BasePlugin, register_plugin

from . import BACKEND_SERVICE_SIGNATURE
from .commands import NeoFoxzoneCommand
from .config import NeoFoxzoneConfig
from .service import NeoFoxzoneService
from .tools import READ_TOOLS, WRITE_TOOLS


@register_plugin
class NeoFoxzonePlugin(BasePlugin):
    """装配基于 OneBot Expand 的 QQ 空间说说能力。"""

    plugin_name = "neo-foxzone"
    plugin_description = "基于 OneBot Expand 的 QQ 空间说说全功能插件"
    plugin_version = "0.1.0"
    configs = [NeoFoxzoneConfig]
    dependencies = [BACKEND_SERVICE_SIGNATURE]

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


__all__ = ["NeoFoxzonePlugin"]