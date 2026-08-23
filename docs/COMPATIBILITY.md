# QZone Compatibility

## Capability Boundary

Neo FoxZone 完整覆盖 OneBot Expand `1.0.16` QZone Service 的 9 个公开 action，并额外
使用两个不注册为 OneBot action 或 Tool 的内部 Service 方法：评论详情查询和楼中楼
回复。它们专门解决 SnowLuma 公开摘要响应裁剪评论树的问题。

Neo FoxZone 从不读取、持久化或记录 QQ Cookie。OneBot Expand 的内部兼容客户端会在
单次请求中通过既有 `get_cookies(qzone.qq.com)` 使用协议端当前 QZone 会话；若 Cookie
或 `p_skey` 不可用，方法返回失败，自动回复会跳过对应说说而不会降级为普通评论。

## Action Matrix

| Action | Neo FoxZone | OneBot Expand | SnowLuma | NapCat v4.18.10+ |
| --- | --- | --- | --- | --- |
| `get_qzone_msg_list` | 完整封装 | 已提供 | 已实现 | 部分版本未实现 |
| `get_qzone_feeds` | 完整封装 | 已提供 | 已实现 | 部分版本未实现 |
| `send_qzone_msg` | 完整封装 | 已提供 | 已实现 | 已实现 |
| `delete_qzone_msg` | 完整封装 | 已提供 | 已实现 | 已实现 |
| `like_qzone` | 完整封装 | 已提供 | 已实现 | 部分版本未实现 |
| `unlike_qzone` | 完整封装 | 已提供 | 已实现 | 部分版本未实现 |
| `comment_qzone` | 完整封装 | 已提供 | 已实现 | 部分版本未实现 |
| `set_qzone_ban` | 完整封装 | 已提供 | 已实现 | 部分版本未实现 |
| `set_qzone_msg_right` | 完整封装 | 已提供 | 已实现 | 部分版本未实现 |
| `get_qzone_msg_detail`（内部） | 自动回复使用 | 已提供 | 通过 Cookie 兼容层 | 未实测 |
| `reply_qzone_comment`（内部） | 自动回复使用 | 已提供 | 通过 Cookie 兼容层 | 未实测 |

协议实现持续演进，最终应以实际协议端版本和返回结果为准。

## Known Protocol Limits

### Automatic replies require structured comments

列表与动态响应仅用于发现可能有评论的说说，自动回复不会由 `comment_num` 或 HTML
直接推断评论关系。详情响应至少需要提供：

- 说说 ID：`tid`、`key` 等。
- 评论 ID：明确的 `comment_id`、`commentid`；好友动态适配器还接受 `id`。
- 评论者 QQ 与评论正文。
- 对他人说说恢复对话时，还需要父评论 ID 或明确的被回复 QQ。

Neo FoxZone 会兼容 `commentlist`、`comments`、`list_3` 等明确结构，但不会从模糊
HTML、`children` 等泛化字段或评论计数猜测作者和回复关系，也不会把说说的 `tid`、
`key` 或 `target_uin` 当成评论关系。字段不足或关系冲突时只会得到 0 个候选。

当前 SnowLuma 的公开返回映射中：

- `get_qzone_msg_list` 只保留 `comment_num`，未保留 CGI 返回的评论明细。
- `get_qzone_feeds` 主要提供预渲染 `html`，未规范化评论树。

因此 Neo FoxZone 在发现候选说说后调用内部 `get_qzone_msg_detail(tid, host_uin)` 补全
评论树。楼中楼回复只允许使用该详情返回的顶层全局评论 ID；详情、Cookie 或关系验证
失败时安全跳过，绝不退回 `comment_qzone`。

### No arbitrary-user post-list query

`get_qzone_msg_list` 只有 `pos` 和 `num`，查询当前登录 QQ 的说说。它不接受
`target_uin`，因此不能等价实现“读取任意指定 QQ 的历史说说”。

### Internal detail and nested replies

公开 `comment_qzone` 不接受父评论 ID 或被回复评论 ID，仍然只能发表普通评论。自动
回复不使用它：OneBot Expand 内部的 `get_qzone_msg_detail` 以 `target_uin + tid` 读取
完整详情，`reply_qzone_comment` 则使用详情确认的顶层评论 ID 构造 QZone 楼中楼请求。
这两个方法要求有效 QZone Cookie，且不是可直接暴露给 LLM 的 action。

### Non-empty content on SnowLuma

当前 SnowLuma 的 `send_qzone_msg` 与 `comment_qzone` schema 要求 `content` 非空。
Neo FoxZone 因此要求带图说说和带图评论也提供非空正文，不宣称支持纯图片发布。

### Backend paths differ

本地 `file://` 图片路径由协议端读取。Neo-MoFox 和协议端位于不同机器或容器时，
相同路径通常不可见。跨主机部署应使用 HTTP URL 或 `base64://`。

## Failure Semantics

Neo FoxZone 将以下响应视为成功：

- `status == "ok"`
- 当响应没有 `status` 时，`retcode == 0`

失败信息按以下顺序提取：

1. `msg`
2. `wording`
3. `message`
4. `retcode`

Service 始终返回原始响应；Tool 和 Command 在原始响应之外增加成功状态和可读错误，
不会丢弃协议端数据。

## Verification Strategy

自动测试使用严格替身验证 9 个公开 action、内部详情与楼中楼转发参数均未丢失，并覆盖
评论结构归一化、跨重启的线程根映射、启动任务生命周期、生成后单次发布与可替换图片
Provider。
只读 action 可以在真实协议端直接冒烟测试；发布、删除、点赞、评论、拉黑、权限
修改和自动回复会产生真实副作用，应在测试账号或测试说说上手动验证。