# Neo FoxZone

Neo FoxZone 是一个面向 Neo-MoFox 的 QQ 空间说说插件。它以
[OneBot Expand](https://github.com/fuilyha56-wq/onebot_expand) 为硬前置，
通过 `onebot_expand:service:qzone_service` 调用 OneBot 协议端，不读取、保存或
刷新 QQ 空间 Cookie，也不依赖 `p_skey`、`skey` 或浏览器私有 HTTP 接口。

插件完整封装 OneBot Expand 当前公开的 9 项 QQ 空间能力：

- 获取当前 QQ 的说说列表
- 获取好友空间动态
- 发表文字或图片说说
- 删除说说
- 点赞说说
- 取消点赞
- 发表评论，可附带图片
- 拉黑或解除拉黑空间用户
- 修改已发布说说的查看权限

每项能力都可以通过插件 Service 调用；默认还提供 9 个 LLM Tool 和一套仅
`OPERATOR` 可使用的 `/neofoxzone` 管理命令。

## 为什么使用 Neo FoxZone

旧式 QQ 空间插件通常从 OneBot HTTP 接口获取 Cookie，再自行计算 `g_tk` 并调用
QQ 空间私有接口。这条链路容易因为 Cookie 缺少 `p_skey` 而失效，也会让插件承担
敏感凭据存储、接口兼容和登录态刷新工作。

Neo FoxZone 把协议边界交给 OneBot Expand：

```text
命令 / LLM Tool / 其他插件
            |
            v
neo-foxzone:service:neo_foxzone_service
            |
            v
onebot_expand:service:qzone_service
            |
            v
OneBot Adapter -> NapCat / SnowLuma / 兼容实现
```

这意味着：

- Neo FoxZone 不接触 QQ Cookie。
- 前置依赖缺失或版本不满足时，Neo-MoFox 会阻止插件加载。
- 协议端失败会保留完整 OneBot 响应，便于定位 `retcode`、`msg` 和 `wording`。
- 其他插件可以复用统一的 Neo FoxZone Service，无需重复实现输入校验。

## 前置要求

- Neo-MoFox `>= 1.0.0`
- Python `>= 3.11`
- OneBot Expand `>= 1.0.13`
- OneBot Expand 自身依赖的 `onebot_adapter`
- 已连接且实现相应 QZone action 的 OneBot 协议端

插件清单已经声明硬依赖：

```json
{
  "dependencies": {
    "plugins": [
      "onebot_expand>=1.0.13"
    ],
    "components": [
      "onebot_expand:service:qzone_service"
    ]
  },
  "dependencies_required": true
}
```

本地可用以下命令确认 MPDT 能识别依赖：

```powershell
mpdt depend list .
```

应看到：

```text
onebot_expand>=1.0.13
```

## 协议端兼容性

Neo FoxZone 提供的组件始终完整，但功能是否能成功执行还取决于 OneBot 协议端。

| 功能 | OneBot action | SnowLuma | NapCat v4.18.10+ |
| --- | --- | --- | --- |
| 获取自己的说说 | `get_qzone_msg_list` | 支持 | 部分版本未实现 |
| 获取好友动态 | `get_qzone_feeds` | 支持 | 部分版本未实现 |
| 发表说说 | `send_qzone_msg` | 支持 | 支持 |
| 删除说说 | `delete_qzone_msg` | 支持 | 支持 |
| 点赞 | `like_qzone` | 支持 | 部分版本未实现 |
| 取消点赞 | `unlike_qzone` | 支持 | 部分版本未实现 |
| 评论 | `comment_qzone` | 支持 | 部分版本未实现 |
| 空间黑名单 | `set_qzone_ban` | 支持 | 部分版本未实现 |
| 修改查看权限 | `set_qzone_msg_right` | 支持 | 部分版本未实现 |

需要九项能力全部实机可用时，推荐使用已实现全部 action 的 SnowLuma。NapCat
未实现的 action 通常会返回 `failed` 或 `retcode=1404`；Neo FoxZone 会原样报告，
不会伪装成功，也不会退回 Cookie 私有接口。

更详细的边界说明见 [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)。

## 安装

### 从插件市场安装

1. 在 Neo-MoFox 插件市场搜索 `neo-foxzone`。
2. 确认详情页的前置依赖包含 `onebot_expand>=1.0.13`。
3. 安装并重启 Neo-MoFox。
4. 执行 `/neofoxzone status` 检查两个 Service。

如果市场没有自动安装前置插件，请先安装 OneBot Expand，再安装 Neo FoxZone。

### 本地安装

将插件目录放入 Neo-MoFox 的 `plugins/neo-foxzone`：

```text
neo-mofox/
└── plugins/
    └── neo-foxzone/
        ├── manifest.json
        ├── plugin.py
        └── ...
```

然后在 Neo-MoFox 根目录执行：

```powershell
uv sync
uv run main.py
```

## 快速检查

插件加载后，以运营者身份发送：

```text
/neofoxzone status
```

正常结果应同时显示：

```text
Neo FoxZone Service: 已就绪
OneBot Expand QZone Service: 已就绪
```

接着可以先执行无副作用的查询：

```text
/neofoxzone posts 0 10
/neofoxzone feeds 0 10
```

## 管理命令

所有命令均要求 `OPERATOR` 权限。命令解析使用 shell 风格语法；包含空格的正文
请用双引号包裹，图片和 QQ 号列表使用英文逗号分隔。

### 查看帮助与状态

```text
/neofoxzone
/neofoxzone status
```

### 获取自己的说说

```text
/neofoxzone posts [pos] [num]
```

示例：

```text
/neofoxzone posts 0 20
```

`pos` 从 0 开始，`num` 默认 10，最大值由配置中的 `max_query_count` 决定。

### 获取好友动态

```text
/neofoxzone feeds [page_num] [count]
```

示例：

```text
/neofoxzone feeds 0 10
```

### 发表说说

```text
/neofoxzone publish "正文" [图片逗号列表] [ugc_right] [QQ逗号列表]
```

发表纯文字说说：

```text
/neofoxzone publish "今晚的风很舒服"
```

发表带图说说：

```text
/neofoxzone publish "旅途记录" "https://example.com/a.jpg,https://example.com/b.jpg"
```

发表仅部分好友可见的说说：

```text
/neofoxzone publish "小范围记录" "" 16 "10001,10002"
```

发表纯图片说说时，正文参数仍需保留为空字符串：

```text
/neofoxzone publish "" "file:///D:/Pictures/qzone.jpg"
```

### 删除说说

```text
/neofoxzone delete <tid>
```

示例：

```text
/neofoxzone delete 1234567890
```

### 点赞与取消点赞

```text
/neofoxzone like <tid> [发布者QQ]
/neofoxzone unlike <tid> [发布者QQ]
```

示例：

```text
/neofoxzone like 1234567890 3693525299
/neofoxzone unlike 1234567890 3693525299
```

若协议端能只凭 `tid` 定位说说，可以省略发布者 QQ。

### 评论说说

```text
/neofoxzone comment <tid> "正文" [发布者QQ] [图片逗号列表]
```

纯文字评论：

```text
/neofoxzone comment 1234567890 "拍得很好看" 3693525299
```

带图评论：

```text
/neofoxzone comment 1234567890 "补一张图" 3693525299 "file:///D:/Pictures/reply.jpg"
```

### 空间黑名单

```text
/neofoxzone ban <QQ号> [true|false]
```

拉黑：

```text
/neofoxzone ban 10001 true
```

解除拉黑：

```text
/neofoxzone ban 10001 false
```

### 修改说说查看权限

```text
/neofoxzone visibility <tid> <ugc_right> [QQ逗号列表]
```

示例：

```text
/neofoxzone visibility 1234567890 64
/neofoxzone visibility 1234567890 16 "10001,10002"
/neofoxzone visibility 1234567890 128 "10003,10004"
```

## 查看权限

| `ugc_right` | 含义 | `target_uins` |
| --- | --- | --- |
| `1` | 所有人可见 | 通常不需要 |
| `4` | 好友可见 | 通常不需要 |
| `16` | 部分好友可见 | 必填，可见 QQ 列表 |
| `64` | 仅自己可见 | 通常不需要 |
| `128` | 部分好友不可见 | 必填，不可见 QQ 列表 |

Neo FoxZone 会在调用协议端前校验 `16` 和 `128` 的名单，避免发送明显无效请求。

## 图片参数

图片由 OneBot Expand 和协议端解析。常见形式：

```text
file:///D:/Pictures/qzone.jpg
https://example.com/qzone.jpg
base64://<BASE64_DATA>
```

注意：

- 本地路径必须是协议端可访问的路径。如果 Neo-MoFox 与协议端不在同一台机器，
  建议使用 HTTP URL 或 `base64://`。
- Windows 路径推荐写成标准 `file:///D:/...` URI。
- 默认每条说说或评论最多 9 张图，可在配置中修改。
- 图片引用中的逗号会被管理命令视为分隔符；复杂数据建议通过 Tool 或 Service 调用。

## LLM Tool

默认注册以下 Tool：

| Tool | 功能 |
| --- | --- |
| `neo_foxzone_list_posts` | 获取当前 QQ 的说说列表 |
| `neo_foxzone_list_feeds` | 获取好友动态 |
| `neo_foxzone_publish` | 发表文字或图片说说 |
| `neo_foxzone_delete` | 删除说说 |
| `neo_foxzone_like` | 点赞 |
| `neo_foxzone_unlike` | 取消点赞 |
| `neo_foxzone_comment` | 评论说说 |
| `neo_foxzone_set_blacklist` | 设置空间黑名单 |
| `neo_foxzone_set_visibility` | 修改说说查看权限 |

Tool 返回结构保留完整协议响应：

```json
{
  "action": "send_qzone_msg",
  "response": {
    "status": "ok",
    "retcode": 0,
    "data": {}
  }
}
```

这样模型或调用方可以读取协议端返回的 `tid`、分页数据及扩展字段，而不是只收到
固定的“操作成功”文本。

## 供其他插件调用

Neo FoxZone 暴露 Service：

```text
neo-foxzone:service:neo_foxzone_service
```

其他插件应在自己的 manifest 和组件类中声明依赖，然后通过 `service_api` 获取：

```python
from typing import Any, Protocol, cast

from src.app.plugin_system.api import service_api


class NeoFoxzoneServiceLike(Protocol):
    async def send_qzone_msg(
        self,
        content: str,
        images: list[str] | None = None,
        ugc_right: int = 1,
        target_uins: list[int] | None = None,
    ) -> dict[str, Any]: ...


raw_service = service_api.get_service(
    "neo-foxzone:service:neo_foxzone_service"
)
if raw_service is None:
    raise RuntimeError("Neo FoxZone Service 未注册")

qzone = cast(NeoFoxzoneServiceLike, raw_service)
result = await qzone.send_qzone_msg("来自其他插件的说说")
```

完整方法签名见 [docs/API_REFERENCE.md](docs/API_REFERENCE.md)。

## 配置

首次加载后，配置系统会生成：

```text
config/plugins/neo-foxzone/config.toml
```

默认配置对应以下结构：

```toml
[plugin]
enabled = true
version = "0.1.0"

[components]
command_enabled = true
read_tools_enabled = true
write_tools_enabled = true

[limits]
max_query_count = 50
max_images = 9
max_command_output_chars = 12000
```

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `plugin.enabled` | `true` | 插件总开关 |
| `components.command_enabled` | `true` | 注册管理命令 |
| `components.read_tools_enabled` | `true` | 注册两个查询 Tool |
| `components.write_tools_enabled` | `true` | 注册七个写操作 Tool |
| `limits.max_query_count` | `50` | 单次查询最大条数 |
| `limits.max_images` | `9` | 单次调用最大图片数 |
| `limits.max_command_output_chars` | `12000` | 命令原始 JSON 输出上限 |

修改组件注册开关后建议重启 Neo-MoFox，使组件注册表按新配置重建。

## 从旧 FoxZone 迁移

Neo FoxZone 与基于 Cookie 的 FoxZone 可以同时存在，但不建议同时向模型暴露重名或
相似的 QQ 空间工具。迁移建议：

1. 安装并启用 OneBot Expand `>=1.0.13`。
2. 确认协议端实现需要的 QZone action。
3. 安装 Neo FoxZone 并执行 `/neofoxzone status`。
4. 先测试 `posts`、`feeds` 两个只读命令。
5. 用测试说说验证发布、点赞、评论和删除。
6. 确认功能正常后，禁用旧 FoxZone。
7. 按你的隐私策略处理旧插件留下的 Cookie 文件。

Neo FoxZone 不会读取或自动删除旧插件的 Cookie 数据，避免越权修改其他插件目录。

## 故障排查

### 前置插件未加载

错误示例：

```text
前置服务 onebot_expand:service:qzone_service 未注册
```

检查：

```powershell
mpdt depend list .
```

然后确认 OneBot Expand 已安装、版本不低于 `1.0.13`，并且它依赖的
`onebot_adapter` 已成功加载。

### `retcode=1404` 或 action 不支持

这通常表示当前协议端未实现对应 QZone action。Neo FoxZone 无法在插件层补出协议端
不存在的能力。请升级协议端，或切换到实现完整 QZone action 的 SnowLuma。

### 发布成功但图片不可见

确认图片 URI 能由协议端访问。容器、远程协议端和宿主机之间的本地文件路径并不
天然互通；优先使用可访问的 HTTP URL 或 `base64://`。

### 无法获取任意指定 QQ 的历史说说

OneBot Expand 当前的 `get_qzone_msg_list` 只查询当前登录 QQ，没有 `target_uin`
参数。好友内容通过 `get_qzone_feeds` 获取。插件不会伪造“任意 QQ 详情查询”能力。

### 无法回复指定评论或获取完整评论树

当前 `comment_qzone` 只有 `tid`、`content`、`target_uin` 和 `images`，没有父评论
ID 参数；现有 OneBot 契约也未提供完整评论树查询。Neo FoxZone 只暴露协议实际具备
的能力。

### 仍看到 `p_skey` 错误

Neo FoxZone 本身不读取 Cookie。若日志来源仍是 `foxzone.service` 或旧插件名，说明
旧 FoxZone 仍在运行。禁用旧插件后重启 Neo-MoFox，并确认调用的是
`neo-foxzone` 组件。

## 开发与验证

在 Neo-MoFox 根目录运行定向测试：

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run pytest plugins/neo-foxzone/tests/test_neo_foxzone.py `
  -o addopts="" -p no:cacheprovider -p no:randomly -q
```

静态检查：

```powershell
mpdt plugin check plugins/neo-foxzone
```

构建市场包：

```powershell
mpdt plugin build plugins/neo-foxzone
```

测试覆盖：

- 9 个 QZone action 的参数转发
- 图片-only 说说与评论
- 查看权限和 QQ 名单校验
- 前置 Service 缺失错误
- Tool 与命令调用路径
- 默认组件注册
- manifest 插件级与组件级依赖

## 安全与隐私

- 插件不读取、保存或记录 QQ Cookie。
- 插件不包含 API 密钥、Token 或账号密码。
- 命令返回的是协议端响应，可能包含 QQ 号、说说内容和图片地址；不要把日志公开到
  不可信环境。
- 发布、删除、点赞、评论、拉黑和权限修改都是真实写操作。建议先在测试账号或测试
  说说上验证。
- `OPERATOR` 权限只保护聊天命令；LLM Tool 是否暴露由配置和 Neo-MoFox 的模型工具
  策略共同决定。

## 许可证

本插件采用 AGPL-3.0 许可证。