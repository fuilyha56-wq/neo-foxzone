"""Neo FoxZone 插件配置。"""

from __future__ import annotations

from typing import ClassVar, Literal

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

    @config_section("image", title="说说配图", tag="ai")
    class ImageSection(SectionBase):
        """可替换的图片生成 Service 配置。"""

        provider: Literal["disabled", "nai_artist", "service"] = Field(
            default="nai_artist",
            description=(
                "图片提供方：nai_artist 适配当前 NAI Artist；service 调用实现统一"
                " generate_image_for_external 接口的任意 Service；disabled 禁用生图。"
            ),
        )
        service_signature: str = Field(
            default="",
            description=(
                "provider=service 时的组件签名，例如 other_plugin:service:image。"
            ),
        )
        service_method: str = Field(
            default="generate_image_for_external",
            description=(
                "通用图片 Service 方法名；方法接收 description 与 style 关键字参数。"
            ),
        )
        default_style: Literal["photo", "drawing"] = Field(
            default="drawing",
            description="未指定时使用的默认生图风格。",
        )
        timeout_seconds: float = Field(
            default=180.0,
            description="等待图片 Provider 完成生成的超时时间（秒）。",
        )

    image: ImageSection = Field(default_factory=ImageSection)

    @config_section("polling", title="自动回复轮询", tag="ai")
    class PollingSection(SectionBase):
        """启动检查、定时轮询和 LLM 回复边界。"""

        enabled: bool = Field(
            default=True,
            description="启用说说评论自动检查与回复。",
        )
        startup_check: bool = Field(
            default=True,
            description="插件每次启动后立即执行一次检查。",
        )
        interval_minutes: float = Field(
            default=30.0,
            description="启动检查后的轮询间隔（分钟）。",
        )
        own_posts_count: int = Field(
            default=20,
            description="每轮检查自己最近说说的数量。",
        )
        friend_feeds_count: int = Field(
            default=20,
            description="每轮检查好友动态的数量。",
        )
        max_replies_per_poll: int = Field(
            default=5,
            description="单轮最多成功自动回复的评论数，避免触发 QQ 空间风控。",
        )
        max_attempts_per_poll: int = Field(
            default=10,
            description="单轮最多尝试生成或发送回复的评论数。",
        )
        failure_retry_minutes: float = Field(
            default=30.0,
            description="LLM 或协议明确失败后的基础重试间隔（分钟）。",
        )
        state_max_entries: int = Field(
            default=2000,
            description="最多保留的已处理评论和 Bot 评论 ID 数量。",
        )
        model_task: str = Field(
            default="utils_small",
            description="生成自动回复所用的 model.toml 任务名称。",
        )
        max_reply_chars: int = Field(
            default=180,
            description="自动回复正文的最大字符数。",
        )

    polling: PollingSection = Field(default_factory=PollingSection)

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