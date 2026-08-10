# Neo FoxZone API Reference

## Service

组件签名：

```text
neo-foxzone:service:neo_foxzone_service
```

所有方法返回 OneBot 原始响应 `dict[str, Any]`。常见结构：

```json
{
  "status": "ok",
  "retcode": 0,
  "data": {},
  "message": "",
  "wording": "",
  "echo": null
}
```

协议端可能省略其中部分字段，也可能在 `data` 中增加实现专属字段。

## Methods

### `get_qzone_msg_list`

```python
async def get_qzone_msg_list(
    pos: int = 0,
    num: int = 10,
) -> dict[str, Any]
```

获取当前登录 QQ 的说说列表。

### `get_qzone_feeds`

```python
async def get_qzone_feeds(
    page_num: int = 1,
    count: int = 10,
) -> dict[str, Any]
```

获取当前登录 QQ 可见的好友空间动态。`page_num` 从 1 开始。

### `send_qzone_msg`

```python
async def send_qzone_msg(
    content: str,
    images: list[str] | None = None,
    ugc_right: int = 1,
    target_uins: list[int] | None = None,
) -> dict[str, Any]
```

发表说说，可附带图片。当前适配的 SnowLuma 后端要求 `content` 非空；
`ugc_right` 为 `16` 或 `128` 时必须提供 `target_uins`。

### `send_generated_qzone_msg`

```python
async def send_generated_qzone_msg(
    content: str,
    image_description: str,
    image_style: Literal["photo", "drawing"] | None = None,
    ugc_right: int = 1,
    target_uins: list[int] | None = None,
) -> dict[str, Any]
```

调用配置的图片 Provider，等待图片完整生成并归一化为 QZone 图片引用，然后只调用
一次 `send_qzone_msg`，把正文与图片作为同一条说说发表。Provider 失败时抛出
`NeoFoxzoneError`，不会先发布纯文字说说。

### `delete_qzone_msg`

```python
async def delete_qzone_msg(tid: str) -> dict[str, Any]
```

删除当前登录 QQ 发布的指定说说。

### `like_qzone`

```python
async def like_qzone(
    tid: str,
    target_uin: int | None = None,
) -> dict[str, Any]
```

点赞说说。部分协议端需要 `target_uin` 才能定位发布者。

### `unlike_qzone`

```python
async def unlike_qzone(
    tid: str,
    target_uin: int | None = None,
) -> dict[str, Any]
```

取消点赞说说。

### `comment_qzone`

```python
async def comment_qzone(
    tid: str,
    content: str,
    target_uin: int | None = None,
    images: list[str] | None = None,
) -> dict[str, Any]
```

发表评论，可附带图片。当前适配的 SnowLuma 后端要求 `content` 非空。当前契约不
支持父评论 ID，因此不能保证楼中楼定向回复。

### `set_qzone_ban`

```python
async def set_qzone_ban(
    user_id: int,
    enable: bool = True,
) -> dict[str, Any]
```

把用户加入或移出当前 QQ 的空间黑名单。

### `set_qzone_msg_right`

```python
async def set_qzone_msg_right(
    tid: str,
    ugc_right: int,
    target_uins: list[int] | None = None,
) -> dict[str, Any]
```

修改已发布说说的查看权限。

## Errors

插件输入校验失败或前置 Service 缺失时抛出：

```python
NeoFoxzoneError
```

协议端返回失败响应时，Service 不抛异常，而是保留原始响应。调用方可使用：

```python
service.response_succeeded(response)
service.response_error(response)
```

## Components

### Read Tools

- `neo_foxzone_list_posts`
- `neo_foxzone_list_feeds`

### Write Tools

- `neo_foxzone_publish`
- `neo_foxzone_publish_generated`
- `neo_foxzone_delete`
- `neo_foxzone_like`
- `neo_foxzone_unlike`
- `neo_foxzone_comment`
- `neo_foxzone_set_blacklist`
- `neo_foxzone_set_visibility`

### Command

- `neofoxzone`

所有 Tool 和 Command 依赖：

```text
neo-foxzone:service:neo_foxzone_service
```

Neo FoxZone Service 依赖：

```text
onebot_expand:service:qzone_service
```

Neo FoxZone 插件生命周期还依赖以下 Service 获取当前 Bot QQ：

```text
onebot_expand:service:account_service
```

## Image Provider Contract

当 `image.provider = "service"` 时，配置的 Service 默认实现：

```python
async def generate_image_for_external(
    *,
    description: str,
    style: Literal["photo", "drawing"],
) -> str | list[str] | dict[str, Any] | None
```

Neo FoxZone 接受 URL、`file://`、`base64://`、Base64 data URI、裸 Base64、图片列表，
以及包含 `images`、`image_refs`、`urls`、`image`、`image_ref`、`base64`、`url`
或 `path` 的字典。方法名可通过 `image.service_method` 修改。Provider 的整个生成
过程受 `image.timeout_seconds` 限制；超时会抛出 `ImageProviderError`，不会进入
QZone 发布步骤。

## Polling Runtime

自动回复轮询不额外暴露组件签名，由插件生命周期使用 TaskManager 管理。启动时加载
JSON 状态并按配置立即检查，之后按 `polling.interval_minutes` 重复执行。

轮询在远端写入前持久化 `in_flight`，成功后逐条提交。明确失败会释放占用并按
`polling.failure_retry_minutes` 退避；远端结果不明时保留占用，防止重启后重复回复。
单轮成功数和尝试数分别由 `polling.max_replies_per_poll` 与
`polling.max_attempts_per_poll` 限制。

运营者命令：

- `neofoxzone poll-now`：复用当前轮询器执行一次检查。
- `neofoxzone poll-status`：查看最近一次报告。
- `neofoxzone publish-ai`：调用 `send_generated_qzone_msg`。

轮询只会处理响应中可证明关系的结构化评论。所需字段及协议限制见
[COMPATIBILITY.md](COMPATIBILITY.md)。