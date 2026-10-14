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
            default="0.1.7",
            description="当前插件版本。",
            disabled=True,
        )

    plugin: PluginSection = Field(default_factory=PluginSection)

    @config_section("components", title="组件入口", tag="plugin")
    class ComponentsSection(SectionBase):
        """命令和 LLM Tool 注册开关。"""

        command_enabled: bool = Field(
            default=True,
            description="注册 /neo-foxzone 管理命令。",
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

    @config_section("security", title="写操作账号校验", tag="security")
    class SecuritySection(SectionBase):
        """限制真实写操作必须使用明确配置的当前 Bot 账号。"""

        write_account_qq: str = Field(
            default="3693525299",
            description=(
                "真实写操作允许使用的 Bot QQ。每次发布、评论、点赞、删除、"
                "权限和黑名单操作都会通过当前登录接口确认；未知或不匹配时拒绝。"
            ),
        )

    security: SecuritySection = Field(default_factory=SecuritySection)

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
        auto_decision_enabled: bool = Field(
            default=False,
            description="启用主题发布时由 LLM 选择是否配图、画面描述和 photo/drawing 风格。",
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
            description="协议明确失败后的基础重试间隔（分钟）。",
        )
        generation_retry_minutes: float = Field(
            default=5.0,
            description=(
                "LLM 生成失败（如网关连接错误）后的重试间隔（分钟）。"
                "生成失败与 QZone 发送失败无关，短退避即可，避免一次网关抖动"
                "让全部候选退避数小时。"
            ),
        )
        rate_limit_retry_minutes: float = Field(
            default=120.0,
            description="触发 QZone 频率限制（subcode=1012/-10049）后的退避间隔（分钟）。",
        )
        send_jitter_seconds_min: float = Field(
            default=15.0,
            description="同一轮内相邻两次回复发送之间的最小随机等待（秒），对齐原版防风控节奏。",
        )
        send_jitter_seconds_max: float = Field(
            default=30.0,
            description="同一轮内相邻两次回复发送之间的最大随机等待（秒）。",
        )
        detail_request_interval_seconds: float = Field(
            default=1.5,
            description="相邻两条说说详情请求之间的最小间隔（秒），避免详情风暴触发风控。",
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

    @config_section("feedback", title="空间消息反馈", tag="ai")
    class FeedbackSection(SectionBase):
        """把轮询发现的新活动送入核心 qzone 会话。"""

        enabled: bool = Field(default=True, description="新评论进入 MoFox 未读消息，由 QZone Chatter 决定回复或忽略。")
        emit_existing_on_first_poll: bool = Field(default=False, description="首次建立基线时是否推送已有评论；默认只推送之后新增的活动。")
        include_friend_posts: bool = Field(default=False, description="把新好友说说也作为消息，由模型决定是否评论。")
        max_events_per_poll: int = Field(default=5, ge=1, le=20, description="每轮最多投递的新活动数量。")
        max_pending_events: int = Field(default=200, ge=1, le=1000, description="持久待处理消息上限；满时停止接收新活动，后续轮询重试。")
        decision_timeout_seconds: float = Field(default=90, ge=1, le=180, description="单条消息的模型决策超时。")
        delivery_retry_seconds: float = Field(default=180, ge=30, description="核心尚未确认消费时的重新投递间隔。")

    feedback: FeedbackSection = Field(default_factory=FeedbackSection)

    @config_section("general", title="自治总控", tag="ai")
    class GeneralSection(SectionBase):
        """原版 FoxZone 自治任务总开关与运行节奏。"""

        enabled: bool = Field(default=False, description="启用 FoxZone 自治任务。")
        interval_minutes: float = Field(
            default=30.0,
            description="自治任务之间的最小检查间隔（分钟）。",
        )
        startup_check: bool = Field(
            default=False,
            description="插件加载后是否立即执行自治任务。",
        )
        dnd_start: int = Field(default=0, description="免打扰开始小时（0-23）。")
        dnd_end: int = Field(default=0, description="免打扰结束小时（0-23）。")

    general: GeneralSection = Field(default_factory=GeneralSection)

    @config_section("llm", title="自治模型", tag="ai")
    class LlmSection(SectionBase):
        """自治任务使用的模型和输出边界。"""

        model_task: str = Field(default="utils_small", description="自治模型任务名。")
        max_reply_chars: int = Field(default=180, description="自治回复最大字符数。")
        inherit_personality: bool = Field(default=True, description="生成正文、评论和轮询回复时继承核心人格。")
        story_model_task: str = Field(default="", description="说说生成模型任务；空值沿用 model_task。")
        comment_model_task: str = Field(default="", description="自治评论决策模型任务；空值沿用 model_task。")
        vision_model_task: str = Field(default="vlm", description="图片理解模型任务；空值关闭图片理解。")
        multimodal_mode: bool = Field(default=False, description="直接把已验证图片传给评论模型；开启时评论模型必须支持视觉。")
        vision_max_images: int = Field(default=3, ge=1, le=9, description="单条动态最多理解的图片数量。")
        vision_max_description_chars: int = Field(default=600, ge=1, le=2000, description="单张图片描述长度上限。")
        vision_timeout_seconds: float = Field(default=60.0, ge=1, le=180, description="单张图片理解超时。")

    llm: LlmSection = Field(default_factory=LlmSection)

    @config_section("monitor", title="自治监控", tag="ai")
    class MonitorSection(SectionBase):
        """好友动态与外部评论回查边界。"""

        enabled: bool = Field(default=True, description="启用好友动态互动。")
        feed_count: int = Field(default=10, description="每轮读取的好友动态数量。")
        followup_count: int = Field(default=10, description="每轮外部评论回查数量。")
        max_external_replies: int = Field(default=3, description="单条动态最多接力次数。")
        self_comments_enabled: bool = Field(default=True, description="启用自治自身评论回复。")
        external_followup_enabled: bool = Field(default=False, description="启用他人空间的接力回复。")
        self_interval_minutes: float = Field(default=30.0, ge=1, description="自身评论检查间隔。")
        friend_interval_minutes: float = Field(default=30.0, ge=1, description="好友动态主动互动间隔。")
        external_interval_minutes: float = Field(default=60.0, ge=1, description="他人空间接力回查间隔。")
        max_comment_age_hours: float = Field(default=72.0, ge=0, description="最大评论年龄；未知时间不猜测年龄。")
        max_followup_age_hours: float = Field(default=168.0, ge=0, description="最长外部动态回查年龄。")
        max_actions_per_cycle: int = Field(default=5, ge=1, le=20, description="每条自治流程每轮最多真实写入次数。")
        max_decisions_per_cycle: int = Field(default=10, ge=1, le=50, description="每轮最多送入模型的候选数。")
        always_like: bool = Field(default=False, description="好友动态始终点赞；关闭时由模型自主决定。")

    monitor: MonitorSection = Field(default_factory=MonitorSection)

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
        max_image_bytes: int = Field(
            default=10 * 1024 * 1024,
            description="单张本地或 Base64 图片的最大字节数。",
        )
        max_content_chars: int = Field(
            default=2000,
            description="单条说说或评论正文的最大字符数。",
        )
        write_min_interval_seconds: float = Field(
            default=2.0,
            description="相邻真实写操作的最小间隔（秒）。",
        )
        max_command_output_chars: int = Field(
            default=12000,
            description="管理命令输出原始 JSON 的最大字符数。",
        )

    limits: LimitsSection = Field(default_factory=LimitsSection)


__all__ = ["NeoFoxzoneConfig"]
