# QZone Compatibility

## Capability Boundary

Neo FoxZone 的“全功能”指完整覆盖 OneBot Expand `1.0.13` 的 QZone Service 公共
接口，共 9 个 action。插件不会通过 Cookie 私有接口填补协议端缺失的 action。

这个边界是有意设计的：缺失能力会以可观察的 OneBot 失败响应呈现，而不是切换到
需要 `p_skey` 的不稳定备用链路。

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

协议实现持续演进，最终应以实际协议端版本和返回结果为准。

## Known Protocol Limits

### No arbitrary-user post-list query

`get_qzone_msg_list` 只有 `pos` 和 `num`，查询当前登录 QQ 的说说。它不接受
`target_uin`，因此不能等价实现“读取任意指定 QQ 的历史说说”。

### No complete feed-detail API

当前公共接口没有按 `target_uin + tid` 获取完整说说详情和评论树的方法。动态流返回
多少评论信息由协议端决定。

### No nested-comment target

`comment_qzone` 不接受父评论 ID 或被回复评论 ID，无法保证定向回复某条评论。

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

自动测试使用一个严格记录参数的 OneBot Expand 替身，验证 9 个 action 均被调用且
参数未丢失。只读 action 可以在真实协议端直接冒烟测试；发布、删除、点赞、评论、
拉黑和权限修改会产生真实副作用，应在测试账号或测试说说上手动验证。