# Neo FoxZone

## 核心消息反馈与模型能力

默认 `[feedback].enabled = true`。插件注册 `qzone_feedback` Adapter 和 `qzone_activity` Chatter，复用核心进程内 CoreSink；轮询发现的新评论、回复进入 MoFox 的未读消息和会话历史，由 LLM 决定回复正文或忽略。`/neo-foxzone feedback-status` 查看真实队列、适配器和最近投递结果；`/neo-foxzone poll-now` 立即检查。

首次读取默认只建立历史基线，避免集中回复旧评论。活动保存后才投递；重启继续待处理队列；模型失败会退避；远端写入结果不明时保留占用，阻止自动重复发送。每个会话绑定作者、说说和顶层评论，发送必须引用保存的活动，并重新读取评论 ID、作者和线程关系。外部正文添加固定消息标签，避免被核心当成管理命令执行。

当前 SnowLuma/OneBot 契约没有可核验的原生未读通知箱、点赞通知或已读标记接口。此处的“未读”是轮询发现的新活动进入 **MoFox 本地未读队列**，状态显示 `native_unread_supported=false`。不会声称读取了 QQ 原生未读数量，也不会清除 QQ 的未读提醒。

`feedback.include_friend_posts=true` 可把新好友说说也交给核心模型决定评论或忽略；默认关闭。基础检查仍使用 `[polling]` 的间隔与查询上限，默认 30 分钟。`general.dnd_start/dnd_end` 在免打扰期间保留消息，延后模型处理。`feedback.enabled=false` 可回到原自动回复轮询和三条独立自治流程。

生成说说、评论、模型回复默认继承核心人格。`llm.story_model_task`、`comment_model_task` 分别选择任务，空值沿用 `llm.model_task`；`vision_model_task` 默认 `vlm`，空值关闭视觉理解。图片先验证大小、格式和 URL，再调用视觉模型；只有成功描述会缓存，缓存有数量与每日有效期边界。`llm.multimodal_mode=true` 可直接向支持图片的评论模型传入验证后的图片，每批最多九张，附件按候选索引关联。模型没有有效输出时不发送。

三条自治流程可用 `/neo-foxzone autopilot-now self_comments|friend_monitor|external_followups` 手动验证，`autopilot-status` 查看结果。`general.enabled` 控制后台自治；自身评论、外部接力和好友动态各有开关、间隔、年龄与次数上限。在反馈模式下，自身评论和接力由核心消息链处理；未开启好友说说反馈时，独立好友点赞/评论任务仍可启用。

最新验证与已知运行障碍见 [消息反馈验证记录](docs/FEEDBACK_TEST_2026-10-14.md)。代码检查通过并不代表当前模型服务或所有协议端完整可用。

Neo FoxZone 为 Neo-MoFox 提供 QQ 空间说说读取、发布和互动能力。OneBot Expand、OneBot Adapter、NAI Artist 都是运行时可选能力。缺少这些插件时，Neo FoxZone 仍可被发现、加载并注册 Service、命令和 Tool；相应功能会返回明确的不可用诊断。

## 协议端发现

插件按以下顺序发现后端：

1. `onebot_expand:service:qzone_service`
2. 其他已注册的 `*:service:qzone_service`
3. 已启动且平台为 QQ 的核心 Adapter，通过 OneBot action 调用

SnowLuma 和 NapCat 由运行中的 QQ Adapter 提供 OneBot action。插件不要求用户配置端口、不启动 Web 服务、不扫描公网或局域网，也不保存 Cookie。详情和楼中楼兼容请求只会在需要时通过账号已核验的在线 Adapter 获取短期 Cookie，并在内存中缓存。

运行 `/neo-foxzone status` 可查看发现结果、在线 Adapter、实时账号校验和写操作状态。Adapter 的 action 支持依协议端版本而异；接口返回失败、缺字段或无法确认身份时，插件会保留错误响应并拒绝相关操作。

## 账号与写操作安全

配置项 `[security].write_account_qq` 默认是 `3693525299`。每次发布、评论、回复、点赞、取消点赞、删除、空间黑名单和权限修改前，插件都会查询当前登录接口并要求账号与配置完全相同。账号未知、多个 Adapter 返回不同账号或账号不匹配时，写操作会被阻止。若要在其他账号上运行，必须先明确修改此设置。

对说说执行删除或权限修改前，插件还会读取详情并确认 tid 与作者 QQ。删除必须提供：

```text
expected_author_qq = 当前账号
confirmation = DELETE <tid> <作者QQ> <当前账号>
```

楼中楼回复必须来自详情中明确存在的顶层评论 ID，并且被回复 QQ 必须出现在该评论线程中。关系无法确认时不会降级成普通评论。自动回复同样经过这些检查。

## 能力范围

当前统一 Service 封装了说说列表、好友动态、单条详情和评论树、发布、删除、点赞、取消点赞、评论、楼中楼回复、空间黑名单设置及发布权限设置。具体 action 是否可用由后端决定。

当前协议契约没有可确认的资料昵称/个性签名修改、黑名单查询、逐条动态屏蔽或说说权限读取接口；插件会明确报告不支持，不会猜测接口或伪造成功。相册、日志、访客等 QZone 产品功能不在实现范围内。

### 图片

- 纯文字发布不需要任何生图插件。
- NAI Artist 是可选图片 Service；其 `generate_image_for_external` 接口在生图完成后返回图片。
- 其他图片插件可通过配置指定 Service 签名和 `generate_image_for_external(description, style)` 方法。
- 支持图片 URL、`file://`、`base64://`、Base64 data URI、裸 Base64 和结构化图片结果。URL 由插件以限时请求下载，DNS 解析到非公网地址时拒绝，不跟随重定向；本地文件和 Base64 会校验常见图片签名。
- 图片数量受 `[limits].max_images` 限制；生成超时或失败时不会发布纯文字替代结果。
- 单张本地或 Base64 图片大小受 `[limits].max_image_bytes` 限制。图片发送给协议端前会统一转换成 Base64。
- URL 图片只接受标准 HTTP/HTTPS 端口；外部服务器返回非图片内容或超限时会拒绝。

协议端只接受正文和图片引用时，颜文字与 Unicode Emoji 可作为正文文本发送；协议端专属表情段并未跨实现验证，不会报告完整支持。调用方应检查适配器返回结果。

## 安装与配置

把插件目录放入 `plugins/neo-foxzone` 并启动 Neo-MoFox。无需安装 OneBot Expand，也无需在 Neo FoxZone 中配置协议端端口。配置文件位于 `config/plugins/neo-foxzone/config.toml`。

关键项：

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `[plugin].enabled` | `true` | 插件总开关 |
| `[security].write_account_qq` | `3693525299` | 允许写操作的 Bot QQ |
| `[image].provider` | `nai_artist` | `disabled`、`nai_artist` 或 `service` |
| `[image].service_signature` | 空 | `provider=service` 时的图片 Service |
| `[image].auto_decision_enabled` | `false` | 允许 `/send` 由 LLM 选择是否配图 |
| `[limits].max_images` | `9` | 单条内容的图片数量上限 |
| `[limits].max_image_bytes` | `10485760` | 单张本地或 Base64 图片的字节数上限 |
| `[limits].write_min_interval_seconds` | `2.0` | 相邻真实写操作的最小间隔 |
| `[polling].enabled` | `true` | 启用自动评论检查与回复 |
| `[polling].startup_check` | `true` | 启动时立即检查一次 |

## 命令

```text
/neo-foxzone status
/neo-foxzone posts [pos] [num]
/neo-foxzone user-posts <QQ号> [pos] [num]
/neo-foxzone detail <tid> <发布者QQ>
/neo-foxzone feeds [page_num] [count]
/neo-foxzone send [主题片段(最多6个)]
/neo-foxzone send-private "主题"
/neo-foxzone publish "正文" [图片逗号列表] [权限] [QQ逗号列表]
/neo-foxzone publish-ai "正文" "画面描述" [photo|drawing] [权限] [QQ逗号列表]
/neo-foxzone like <tid> [发布者QQ]
/neo-foxzone unlike <tid> [发布者QQ]
/neo-foxzone comment <tid> "正文" [发布者QQ] [图片逗号列表]
/neo-foxzone reply <tid> <发布者QQ> <顶层评论ID> <被回复QQ> "昵称" "正文"
/neo-foxzone delete <tid> <作者QQ> "DELETE <tid> <作者QQ> <当前QQ>"
/neo-foxzone ban <QQ号> [true|false]
/neo-foxzone visibility <tid> <权限> [QQ逗号列表]
/neo-foxzone poll-now
/neo-foxzone poll-status
```

`send` 和 `send-private` 使用配置的 LLM 生成正文，后者固定为仅自己可见。启用 `[image].auto_decision_enabled` 后，LLM 可决定是否配图。生成失败、正文为空或配图决策格式错误会取消发布。命令结果会发送回触发命令的聊天。

LLM 可以调用 `neo_foxzone_read_detail` 核验说说作者和评论树，再用 `neo_foxzone_reply_comment` 自主生成楼中楼回复。顶层评论 ID、被回复者 QQ 和昵称必须来自实际详情；无法核验的目标会被拒绝。

发布权限取值：`1` 所有人、`4` 好友、`16` 部分好友可见、`64` 仅自己、`128` 部分好友不可见。`16` 和 `128` 必须提供 QQ 列表。黑名单和权限写入也要求账号校验；建议先在协议端状态和说说详情中确认目标。

## 开发与验证

运行插件测试：

```powershell
$env:PYTHONPATH="$PWD"
.\.venv\Scripts\python.exe -m pytest plugins/neo-foxzone/tests/ -q -p no:cacheprovider -p no:randomly --no-cov
```

检查当前实际能力，不应根据代码测试推断 SnowLuma、NapCat 或特定账号具备全部功能。真实写测试只可在 `/neo-foxzone status` 明确确认当前登录账号为配置账号后进行，并且应使用可识别的测试说说。

当前环境的命令、真实 LLM 工具回复、QQ 反馈发送和测试数据清理记录见 [2026-10-14 实测报告](docs/LIVE_TEST_2026-10-14.md)。
