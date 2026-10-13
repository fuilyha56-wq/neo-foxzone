# 协议兼容性

## 自动发现

Neo FoxZone 不依赖特定插件的导入路径。启动后从核心 Service Registry 查找 QZone Service，再回退到已启动的平台为 QQ 的 Adapter。通过核心 Adapter API 调用标准 OneBot action；不扫描网络、不启动本地 Web 服务，也不要求端口配置。

SnowLuma 或 NapCat 是否可用，取决于它是否通过当前运行的 QQ Adapter 暴露相应 OneBot action。Neo FoxZone 不直接读取 SnowLuma/NapCat 的私有配置，也不会仅凭进程名或配置文件推断已登录账号。

## 能力矩阵

| 能力 | OneBot Expand QZone Service | 标准 QQ Adapter 回退 | 说明 |
| --- | --- | --- | --- |
| 登录账号 | 可选 Account Service | `get_login_info` | 写操作逐次核验 |
| 自己的说说 / 好友动态 | QZone Service action | `get_qzone_msg_list` / `get_qzone_feeds` | 依协议端支持情况 |
| 发布 / 删除 / 点赞 / 评论 | QZone Service action | 对应 OneBot action | 不根据 HTTP 200 推断业务成功 |
| 说说详情 / 评论树 | Service 或 QZone 兼容读取 | 经核验账号 Cookie 的只读 CGI | 作者和 ID 字段不明确则拒绝写操作 |
| 楼中楼回复 | 内部 Service 或兼容路径 | 已验证顶层评论后尝试兼容回复 | 不退回普通评论 |
| 图片发布 | QZone Service action | `send_qzone_msg` | 图片格式由协议端决定 |
| 黑名单设置 / 权限修改 | QZone Service action | 对应 action | 仅写入能力；目标说说需确认属于本人 |
| 资料修改 / 黑名单读取 / 权限读取 | 未确认 | 未确认 | 当前没有可依赖的公开契约 |

## 当前环境验证记录

插件代码适配的是核心注册表和 OneBot action 运行时接口。仅当对应应用进程实际运行、Adapter 已连接且实时接口返回结果时，才可把协议能力记为“已验证”。在测试报告中应分别记录 SnowLuma、NapCat 和 OneBot Expand 的发现与 action 结果；没有运行中的环境时标记“未验证”。

OneBot Expand Service 的存在不会证明其底层 Adapter 已连接；Adapter 存在也不会证明账号已登录或具备 QZone 权限。`/neo-foxzone status` 与各 action 的实际响应是运行时判断依据。

## 统一数据约束

说说详情至少需要明确返回目标 `tid` 和作者 QQ。评论必须保留评论 ID、顶层评论 ID、父评论 ID、作者 QQ 和子评论结构。只有详情中确认的顶层评论 ID可用于楼中楼回复；任何缺字段或关系冲突都会阻止回复。

## 失败处理

后端返回的 `status`、`retcode`、`msg`、`wording` 和 `message` 会保留。缺少服务、未连接、未登录、action 不存在、账号不匹配和请求超时都会报告为失败或未知，不会转换为成功。

详情和 Cookie 失败不会自动切换到不受信任的本地端口或其他账号。Cookie 只留在短期内存缓存，不写日志或磁盘。多个 Adapter 登录到不同账号时，身份结果视为有歧义；Cookie 查询必须锁定到确认的账号。

## 核心消息兼容与当前验证边界

QZone Adapter 直接使用核心为适配器配置的进程内 CoreSink。标准信封声明 message_type=message、platform=qzone，进入核心未读和会话历史；专用 Chatter 不要求其他聊天插件存在。回复使用核心 send_api 和引用活动 ID，通过本插件 Adapter 绑定实际说说线程。

SnowLuma 本轮已验证读取 31 条评论并建立基线、发布好友可见测试说说，以及真实核心接收受控说说消息重放。当前模型服务连接失败，图片描述和新消息回复完整链路尚未通过。NapCat 本轮未运行。完整记录见 FEEDBACK_TEST_2026-10-14.md。

原生未读通知箱、点赞通知、已读标记接口未确认，状态明确返回 native_unread_supported=false；新增评论差分作为 MoFox 本地未读消息处理。
