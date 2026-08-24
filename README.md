# Neo FoxZone

Neo FoxZone 是一个面向 Neo-MoFox 的 QQ 空间说说插件。当前版本为 `0.1.4`。它以
[OneBot Expand](https://github.com/fuilyha56-wq/onebot_expand) 为硬前置，通过
QZone Service 调用 OneBot 协议端，并通过 Account Service 识别当前 Bot QQ。

Neo FoxZone 本身不读取、保存或刷新 QQ 空间 Cookie；为补全 SnowLuma 摘要中的
评论树，OneBot Expand `1.0.17` 的内部 QZone 兼容层会按请求短暂使用协议端已有的
`get_cookies(qzone.qq.com)` 会话。Cookie 不会进入 Neo FoxZone，也不会被持久化或
记录到日志中。

**无浏览器、无本地端口、无 Cookie 管理。** 查询、发布、评论、轮询全部通过进程内
Service 调用和出站 HTTPS 完成。

## 核心能力

### 9 项 OneBot 协议能力

- 获取当前 QQ 的说说列表
- 获取好友空间动态
- 发表说说，可附带图片
- 删除说说
- 点赞说说
- 取消点赞
- 发表评论，可附带图片
- 拉黑或解除拉黑空间用户
- 修改已发布说说的查看权限

### 评论自动回复轮询（默认启用）

- 插件启动后立即检查未回复评论，之后默认每 30 分钟轮询一次。
- 持久记录已处理评论，重启后不会重复回复。
- 对自己的说说处理尚未被 Bot 回复的评论。
- 对他人的说说只恢复能够证明为“直接回复 Bot 评论”的对话。
- 对摘要说说先通过内部详情能力补全评论树，只使用详情确认的顶层全局评论 ID
  发送真正的楼中楼回复；失败时不会退化为普通评论。
- 持久保存 Bot 回复与其顶层评论 ID 的映射，以便详情裁剪旧父评论时仍能安全续聊。

### 三条自治互动任务（默认关闭，配置开启）

- **自己评论回复**：检查 Bot 自己说说下的新评论并回复顶层评论。
- **外部动态接力**：回查 Bot 曾评论过的外部动态，在 Bot 顶层评论下与回复者
  续聊，带每条动态的接力次数上限。
- **好友动态监控**：读取未处理的好友动态，由 LLM 批量决策点赞、评论和已读，
  持久化互动状态避免重复操作。

自治任务受免打扰窗口（DND）约束，深夜自动静默；三条任务异常互相隔离，单条失败
不影响其余任务。

### 统一 LLM 内容服务

内部 `ContentService` 统一封装所有模型请求：

- `generate_story`：按主题生成说说正文
- `generate_batch_replies`：批量生成评论回复
- `generate_feed_decisions`：批量生成好友动态互动决策
- `get_recent_self_feeds_block`：把近期说说压缩为 Prompt 上下文

模型返回的 JSON 统一解析，缺失索引自动归一化，非法输出安全返回空结果，不会让
调度任务崩溃。

### 可替换 AI 配图发布

- 内置 `nai_artist` 适配器（复用 NAI 的配置、tags 转换和衣柜上下文）。
- 通用 Service 适配器：任何实现 `generate_image_for_external` 接口的插件都能当
  图片源。
- 等待图片完全生成后，把图片和正文作为同一条说说一次性发布。

## 为什么使用 Neo FoxZone

旧式 QQ 空间插件通常需要浏览器实例抓取页面、本地端口等待回调、自行存储和续期
Cookie。这条链路部署重、维护难、安全面大。

Neo FoxZone 把协议边界交给 OneBot Expand：

```text
命令 / LLM Tool / 其他插件
            |
            v
neo-foxzone:service:qzone_service
            |
            v
onebot_expand:service:qzone_service
            |
            v
OneBot Adapter -> NapCat / SnowLuma / 兼容实现
```

详情与楼中楼补全链路：

```text
onebot_expand 内部 QZone 兼容层
            |
            v
get_cookies(qzone.qq.com) -> p_skey -> g_tk
            |
            v
h5.qzone.qq.com CGI（emotion_cgi_msgdetail_v6 等，返回 JSON）
            |
            v
归一化 -> 结构化评论树
```

这意味着：

- Neo FoxZone 不接触 QQ Cookie。
- 无浏览器、无本地监听端口、无回调服务。
- Cookie 只在单次请求期间短暂存在于内存，不落盘、不进日志。
- 前置依赖缺失或版本不满足时，Neo-MoFox 会阻止插件加载。
- 协议端失败会保留完整 OneBot 响应，便于定位 `retcode`、`msg` 和 `wording`。
- 其他插件可以复用统一的 Neo FoxZone Service，无需重复实现输入校验。

## 前置要求

- Neo-MoFox `>= 1.0.0`
- Python `>= 3.11`
- OneBot Expand `>= 1.0.16`
- 已连接且实现相应 QZone action 的 OneBot 协议端（推荐 SnowLuma）

插件清单已声明硬依赖：

```json
{
  "dependencies": {
    "plugins": ["onebot_expand>=1.0.16"],
    "components": [
      "onebot_expand:service:qzone_service",
      "onebot_expand:service:account_service"
    ]
  },
  "dependencies_required": true
}
```

## 协议端兼容性

| 功能 | SnowLuma | NapCat v4.18.10+ |
| --- | --- | --- |
| 获取自己的说说 | 支持 | 部分版本未实现 |
| 获取好友动态 | 支持 | 部分版本未实现 |
| 发表说说 | 支持 | 支持 |
| 删除说说 | 支持 | 支持 |
| 点赞 / 取消点赞 | 支持 | 部分版本未实现 |
| 评论 | 支持 | 部分版本未实现 |
| 空间黑名单 / 查看权限 | 支持 | 部分版本未实现 |
| 评论详情（内部） | 兼容层，需有效 QZone Cookie | 未实测 |
| 楼中楼回复（内部） | 兼容层，需有效 QZone Cookie | 未实测 |

需要全部能力实机可用时，推荐使用已实现全部 action 的 SnowLuma。NapCat 未实现
的 action 通常会返回 `failed` 或 `retcode=1404`；Neo FoxZone 会原样报告，不会
伪装成功。

## 安装

### 从插件市场安装

1. 在 Neo-MoFox 插件市场搜索 `neo-foxzone`。
2. 确认详情页的前置依赖包含 `onebot_expand>=1.0.16`。
3. 安装并重启 Neo-MoFox。
4. 执行 `/neo-foxzone status` 检查三个 Service。

### 本地安装

将插件目录放入 Neo-MoFox 的 `plugins/neo-foxzone`，然后执行：

```powershell
uv sync
uv run main.py
```

## 快速开始

以运营者身份发送：

```text
/neo-foxzone status
```

三项就绪后，先执行无副作用查询：

```text
/neo-foxzone posts 0 10
/neo-foxzone feeds 1 10
```

## 管理命令

所有命令均要求 `OPERATOR` 权限。包含空格的正文请用双引号包裹，图片和 QQ 号
列表使用英文逗号分隔。

### 帮助与状态

```text
/neo-foxzone
/neo-foxzone status
```

### 查询

```text
/neo-foxzone posts [pos] [num]        # 自己的说说，pos 从 0 开始
/neo-foxzone feeds [page_num] [count] # 好友动态，page_num 从 1 开始
```

### 发布

```text
/neo-foxzone send [主题片段]          # AI 按主题生成并发布
/neo-foxzone publish "正文" [图片] [权限] [QQ列表]
/neo-foxzone publish-ai "正文" "画面描述" [photo|drawing] [权限] [QQ列表]
```

示例：

```text
/neo-foxzone send 今天天气不错
/neo-foxzone publish "旅途记录" "https://example.com/a.jpg"
/neo-foxzone publish-ai "雨停后的街角" "霓虹倒映在积水里" drawing
```

### 互动

```text
/neo-foxzone like <tid> [发布者QQ]
/neo-foxzone unlike <tid> [发布者QQ]
/neo-foxzone comment <tid> "正文" [发布者QQ] [图片]
/neo-foxzone delete <tid>
```

### 轮询

```text
/neo-foxzone poll-now      # 立即检查一次
/neo-foxzone poll-status   # 查看最近报告
```

### 管理

```text
/neo-foxzone ban <QQ号> [true|false]           # 空间黑名单
/neo-foxzone visibility <tid> <权限> [QQ列表]  # 修改可见范围
```

### 查看权限

| `ugc_right` | 含义 | `target_uins` |
| --- | --- | --- |
| `1` | 所有人可见 | 通常不需要 |
| `4` | 好友可见 | 通常不需要 |
| `16` | 部分好友可见 | 必填，可见 QQ 列表 |
| `64` | 仅自己可见 | 通常不需要 |
| `128` | 部分好友不可见 | 必填，不可见 QQ 列表 |

## LLM Tool

默认注册 10 个 Tool：

| Tool | 功能 |
| --- | --- |
| `neo_foxzone_list_posts` | 获取当前 QQ 的说说列表 |
| `neo_foxzone_list_feeds` | 获取好友动态 |
| `neo_foxzone_publish` | 发表文字或图片说说 |
| `neo_foxzone_publish_generated` | 等待图片生成完成后发表图文说说 |
| `neo_foxzone_delete` | 删除说说 |
| `neo_foxzone_like` | 点赞 |
| `neo_foxzone_unlike` | 取消点赞 |
| `neo_foxzone_comment` | 评论说说 |
| `neo_foxzone_set_blacklist` | 设置空间黑名单 |
| `neo_foxzone_set_visibility` | 修改说说查看权限 |

Tool 返回结构保留完整协议响应，模型可以读取 `tid`、分页数据和扩展字段。

## 供其他插件调用

Neo FoxZone 暴露 Service：

```text
neo-foxzone:service:qzone_service
```

其他插件在 manifest 中声明依赖后，通过 `service_api` 获取：

```python
from src.app.plugin_system.api import service_api

raw_service = service_api.get_service("neo-foxzone:service:qzone_service")
```

完整方法签名见 [docs/API_REFERENCE.md](docs/API_REFERENCE.md)。

## 配置

首次加载后生成 `config/plugins/neo-foxzone/config.toml`：

```toml
[plugin]
enabled = true

[components]
command_enabled = true
read_tools_enabled = true
write_tools_enabled = true

[image]
provider = "nai_artist"        # nai_artist / service / disabled
service_signature = ""
service_method = "generate_image_for_external"
default_style = "drawing"
timeout_seconds = 180.0

[polling]
enabled = true                 # 评论自动回复轮询
startup_check = true
interval_minutes = 30.0
own_posts_count = 20
friend_feeds_count = 20
max_replies_per_poll = 5
max_attempts_per_poll = 10
failure_retry_minutes = 30.0
state_max_entries = 2000
model_task = "utils_small"
max_reply_chars = 180

[general]                      # 三条自治互动任务
enabled = false                # 默认关闭，显式开启
interval_minutes = 30.0
startup_check = false
dnd_start = 0                  # 免打扰开始小时（0-23）
dnd_end = 0                    # 免打扰结束小时（0-23）

[llm]                          # 自治模型
model_task = "utils_small"
max_reply_chars = 180

[monitor]                      # 好友监控与外部回查
enabled = true
feed_count = 10
followup_count = 10
max_external_replies = 3       # 单条动态最多接力次数

[limits]
max_query_count = 50
max_images = 9
max_command_output_chars = 12000
```

### 开启自治互动

```toml
[general]
enabled = true
dnd_start = 23    # 每晚 23 点后静默
dnd_end = 7       # 早上 7 点恢复
```

开启后机器人会自动回复自己说说下的新评论、在评论过的好友动态下接力回复、对新
好友动态点赞评论（LLM 决策）。

## 状态存储

持久化状态位于 `data/json_storage/neo-foxzone/`：

| 文件 | 内容 |
| --- | --- |
| `polling_state.json` | 已处理评论、占用、退避、Bot 评论映射 |
| `reply_tracker.json` | 已回复评论记录 |
| `interaction_log.json` | 点赞、评论、已读互动状态 |
| `vision_cache.json` | 图片描述缓存 |
| `send_history.json` | 最近发布记录 |

## 故障排查

### 前置插件未加载

确认 OneBot Expand 已安装且版本不低于 `1.0.16`。

### `retcode=1404`

当前协议端未实现对应 QZone action。升级协议端或切换到 SnowLuma。

### 轮询运行但没有自动回复

执行 `/neo-foxzone poll-now` 查看报告。列表或动态只有 `comment_num`、HTML 时，
插件会先通过详情兼容层补全评论树；若协议端没有有效 QZone Cookie、详情请求失败
或响应缺少可验证关系，插件会安全跳过而不会从模糊文本猜测后自动发言。

### `publish-ai` 提示图片 Service 未注册

安装 NAI Artist，或把 `image.provider` 改为 `service` 并配置
`image.service_signature`，也可改为 `disabled`。

### `p_skey` 错误

该错误来自 OneBot Expand 的内部 QZone 兼容请求，表示协议端没有返回可用于
QZone CGI 的 Cookie。确认协议端已登录 QQ 空间并支持 `get_cookies(qzone.qq.com)`。

## 开发与验证

```powershell
# 定向测试
$env:PYTHONPATH = (Get-Location).Path
uv run pytest plugins/neo-foxzone/tests/ -q -p no:cacheprovider -p no:randomly --no-cov

# 静态检查
mpdt plugin check plugins/neo-foxzone

# 构建市场包
mpdt plugin build plugins/neo-foxzone
```

测试覆盖：9 个 QZone action 参数转发、评论树归一化、楼中楼回复判据、跨重启
恢复、三条自治流程、批量 LLM 决策解析、DND 窗口、AI 配图发布、manifest 依赖。

## 安全与隐私

- Neo FoxZone 不读取、保存或记录 QQ Cookie；兼容层只在单次请求期间暂存协议端
  返回的 Cookie，不持久化、不写日志。
- 插件不包含 API 密钥、Token 或账号密码。
- 自动回复会把说说正文和评论发送给配置的 LLM 任务；请按模型提供方数据政策
  评估隐私。
- `publish-ai` 会把画面描述发送给配置的图片 Provider。
- 命令返回的是协议端响应，可能包含 QQ 号、说说内容和图片地址。
- 发布、删除、点赞、评论、拉黑和权限修改都是真实写操作，建议先在测试账号上
  验证。
- 自治互动任务默认关闭；开启前请确认风控上限（`max_replies_per_poll`、
  `max_external_replies`）符合预期。

## 版本记录

### 0.1.3

- 完善自动回复轮询、评论详情补全和楼中楼回复链路。
- 对接 OneBot Expand `1.0.17` 的 QZone frame 回调响应兼容。

### 0.1.2

- 新增三条自治互动任务：自己评论回复、外部动态接力、好友动态监控（默认关闭）。
- 新增统一 LLM 内容服务 `ContentService`：批量回复、批量决策、说说生成。
- 新增自治配置分节：`general`（总开关、DND 窗口）、`llm`（模型任务）、
  `monitor`（监控边界与接力上限）。
- `/neo-foxzone send` 改用宿主正式 LLM 请求接口，不再调用不存在的
  `llm_api.generate()`。
- 外部接力改为基于详情确认的 Bot 顶层评论 ID 定位楼中楼 root。
- 存储目录统一为 `data/json_storage/neo-foxzone/`。
- 依赖 OneBot Expand `>= 1.0.17`，通过内部 QZone 兼容层补全完整评论树。
- 自动回复严格使用详情确认的顶层全局评论 ID 发送楼中楼回复。
- 持久保存 Bot 楼中楼回复与顶层评论 ID 的映射。

### 0.1.1

- 完整的轮询决策日志与隐私掩码。
- 新增标准 AGPL-3.0 LICENSE。

### 0.1.0

- 首次发布。完整封装 OneBot Expand 的 9 项 QQ 空间说说能力。

## 许可证

本插件采用 [GNU Affero General Public License v3.0](LICENSE) 许可证。
