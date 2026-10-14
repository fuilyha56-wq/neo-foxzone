# Neo FoxZone

Neo FoxZone 是 Neo-MoFox 的 QQ 空间插件。它发现当前可用的 QZone Service 或已连接的 QQ Adapter，提供说说读取、发布、评论和反馈轮询。当前插件版本：**0.1.7**。

## 新评论如何交给 MoFox

```text
QQ 空间评论/回复
        ↓ 定时轮询发现新增活动
qzone_feedback Adapter → MoFox 本地消息与未读队列
        ↓
qzone_activity Chatter → LLM 决定回复或忽略
        ↓ 选择回复时重新核对说说与评论关系
向正确的说说或评论线程发送回复
```

- 反馈通过轮询产生，默认每 30 分钟检查一次；它不是 QQ 的实时推送。
- 首轮默认建立历史基线，不把旧评论集中送去回复。后续新评论和回复进入 MoFox；好友新说说只有在 `feedback.include_friend_posts = true` 时才作为消息处理。
- 队列和活动状态持久保存。模型失败会延迟重试；发送结果不确定时会保留状态，避免盲目重复回复。
- 这里的“未读”是 MoFox 本地新消息。当前协议没有可确认的 QQ 原生未读列表、点赞通知或标记已读接口，插件不会声称支持这些能力。

查看队列、适配器和最近投递结果：`/neo-foxzone feedback-status`。立即执行一次轮询：`/neo-foxzone poll-now`。

## 安装与连接

1. 将插件放在 Neo-MoFox 的 `plugins/neo-foxzone` 目录。
2. 启动 Neo-MoFox，并连接支持 QQ 空间操作的 QQ Adapter。
3. 在 `config/plugins/neo-foxzone/config.toml` 检查账号和轮询设置。
4. 执行 `/neo-foxzone status` 确认服务、后端和当前登录账号状态。

协议端按以下顺序发现：

1. `onebot_expand:service:qzone_service`
2. 其他已注册的 `*:service:qzone_service`
3. 已连接且平台为 QQ 的核心 Adapter（通过 OneBot action）

OneBot Expand、SnowLuma、NapCat 和图片生成插件不是安装时的强制依赖。实际读写能力取决于当前连接的后端及其 action 支持。插件不启动本地 Web 服务、不扫描网络，也不把 Cookie 写入磁盘。

## 反馈与模型设置

常用设置如下；未列出的选项保留生成配置中的默认值。

```toml
[security]
write_account_qq = "3693525299"

[polling]
enabled = true
startup_check = true
interval_minutes = 30.0
model_task = "utils_small"
max_replies_per_poll = 5

[feedback]
enabled = true
emit_existing_on_first_poll = false
include_friend_posts = false
max_events_per_poll = 5
max_pending_events = 200

[llm]
model_task = "utils_small"
vision_model_task = "vlm"
multimodal_mode = false
```

`write_account_qq` 是真实写操作的账号保护值。每次发布、评论、回复、点赞、删除、黑名单或可见范围修改前，插件都会核对当前登录账号；未知、不一致或多个 Adapter 报告不一致时会拒绝写入。运行在其他 QQ 账号上时，应先修改该值。

`polling.model_task` 选择自动回复模型任务；评论活动进入核心消息链后，由 MoFox 的 Chatter 和 LLM 决定是否回复。核心任务使用 `[llm].model_task`。`vision_model_task` 控制图片理解；设为空值会关闭视觉理解。直接向支持图片的模型发送图片需启用 `multimodal_mode`。

独立自治流程由 `[general].enabled` 控制，默认关闭。反馈队列与自治流程是分开的开关；可分别配置自身评论、好友动态和外部接力的间隔、年龄与次数限制。

## 命令

### 状态与轮询

| 命令 | 用途 |
| --- | --- |
| `/neo-foxzone status` | 查看后端发现、在线 Adapter、账号核验和写操作状态 |
| `/neo-foxzone feedback-status` | 查看反馈适配器、待处理队列和最近投递结果 |
| `/neo-foxzone poll-now` | 立即检查新增评论与回复 |
| `/neo-foxzone poll-status` | 查看自动回复轮询状态 |
| `/neo-foxzone autopilot-status` | 查看独立自治流程状态 |
| `/neo-foxzone autopilot-now self_comments|friend_monitor|external_followups` | 手动运行指定自治流程 |

### 读取、发布与互动

```text
/neo-foxzone posts [pos] [num]
/neo-foxzone user-posts <QQ号> [pos] [num]
/neo-foxzone detail <tid> <发布者QQ>
/neo-foxzone feeds [page_num] [count]
/neo-foxzone send [主题片段]
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
```

LLM 工具 `neo_foxzone_read_detail` 可读取说说和评论树；`neo_foxzone_reply_comment` 可在核验后生成楼中楼回复。权限值：`1` 所有人、`4` 好友、`16` 部分好友可见、`64` 仅自己可见、`128` 部分好友不可见；`16` 和 `128` 需要 QQ 列表。删除必须提供完整确认串。无法核实目标作者、顶层评论或被回复者时，插件会拒绝操作。

## 图片与写入保护

纯文字发布不依赖图片插件。图片可由 NAI Artist 或实现 `generate_image_for_external(description, style)` 的 Service 提供。插件会校验图片来源、格式和大小；模型或图片生成失败时，不会伪装成成功，也不会用纯文字替代失败的配图发布。

发布、删除、评论树回复和空间设置受账号及目标关系检查保护。具体 action 是否可用由协议端决定；接口报错、缺少必要字段或无法确认写入结果时，插件会返回诊断，不会猜测成功。

## 排错

1. 运行 `/neo-foxzone status`：确认服务已发现、QQ Adapter 在线且账号匹配。
2. 运行 `/neo-foxzone feedback-status`：确认 `qzone_feedback` 已注册、队列没有积压或失败状态。
3. 运行 `/neo-foxzone poll-now`：检查后端是否能读到新评论与回复。
4. 若消息已投递但没有回复，检查 MoFox 的 Chatter 配置、模型任务和模型服务日志。
5. 查看 [兼容性说明](docs/COMPATIBILITY.md) 了解后端差异。

代码检查通过不代表当前 QQ Adapter、模型服务或所有写操作端点都在线。历史验证记录：[核心功能实测](docs/LIVE_TEST_2026-10-14.md)、[反馈链路测试记录](docs/FEEDBACK_TEST_2026-10-14.md)。反馈记录中的结论对应记录时的运行环境；实际可用性应以当前状态命令和日志为准。

## 开发

从 Neo-MoFox 仓库根目录运行插件静态检查：

```powershell
mpdt plugin check plugins/neo-foxzone
.venv\Scripts\python.exe -X utf8 -m pytest plugins/neo-foxzone/tests/ -q -p no:cacheprovider -p no:randomly --no-cov
ruff check --no-cache plugins/neo-foxzone/
```

更多接口信息见 [API 参考](docs/API_REFERENCE.md)。
