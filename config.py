"""Neo FoxZone 插件配置。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class NeoFoxzoneConfig(BaseConfig):
    """控制 Neo FoxZone 组件暴露范围与输入边界。"""

    config_name: ClassVar[str] = "config"
    name: ClassVar[str] = "config"
    description: ClassVar[str] = "Neo FoxZone QQ 空间说说插件配置"

    @config_section("plugin", title="插件设置", tag="plugin")
    class PluginSection(SectionBase):
        """插件总开关与版本信息。"""

        enabled: bool = Field(default=True, description="启用 Neo FoxZone。")
        version: str = Field(
            default="0.1.0",
            description="当前插件版本。",
            disabled=True,
        )

    plugin: PluginSection = Field(default_factory=PluginSection)

    @config_section("components", title="组件入口", tag="plugin")
    class ComponentsSection(SectionBase):
        """命令和 LLM Tool 注册开关。"""

        command_enabled: bool = Field(
            default=True,
            description="注册 /neofoxzone 管理命令。",
        )
        read_tools_enabled: bool = Field(
            default=True,
            description="注册说说列表与好友动态查询 Tool。",
        )
        write_tools_enabled: bool = Field(
            default=True,
            description="注册发布、删除、点赞、评论、黑名单和权限管理 Tool。",
        )

    components: ComponentsSection = Field(default_factory=ComponentsSection)

    @config_section("limits", title="调用限制", tag="performance")
    class LimitsSection(SectionBase):
        """保护协议端免受明显异常输入影响。"""

        max_query_count: int = Field(
            default=50,
            description="单次列表或动态查询允许的最大条数。",
        )
        max_images: int = Field(
            default=9,
            description="单条说说或评论允许携带的最大图片数。",
        )
        max_command_output_chars: int = Field(
            default=12000,
            description="管理命令输出原始 JSON 的最大字符数。",
        )

    limits: LimitsSection = Field(default_factory=LimitsSection)


__all__ = ["NeoFoxzoneConfig"]