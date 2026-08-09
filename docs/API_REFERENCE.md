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
    page_num: int = 0,
    count: int = 10,
) -> dict[str, Any]
```

获取当前登录 QQ 可见的好友空间动态。

### `send_qzone_msg`

```python
async def send_qzone_msg(
    content: str,
    images: list[str] | None = None,
    ugc_right: int = 1,
    target_uins: list[int] | None = None,
) -> dict[str, Any]
```

发表说说。`content` 与 `images` 至少提供一项。`ugc_right` 为 `16` 或 `128`
时必须提供 `target_uins`。

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

发表评论。`content` 与 `images` 至少提供一项。当前契约不支持父评论 ID，因此不能
保证楼中楼定向回复。

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