# API Reference

## Service

Component signature:

```text
neo-foxzone:service:qzone_service
```

Neo FoxZone always registers this Service when enabled. At call time it selects a registered QZone Service or an active QQ Adapter. OneBot Expand and OneBot Adapter are optional plugins; there are no optional plugin imports at module load time.

Service results preserve the backend response, including `status`, `retcode`, `data`, `msg`, `wording`, and `message` where present. An unavailable provider produces a failed response or `NeoFoxzoneError`; it is never treated as success.

## Read methods

```python
async def get_qzone_msg_list(pos: int = 0, num: int = 10) -> dict[str, Any]
async def get_qzone_feeds(page_num: int = 1, count: int = 10) -> dict[str, Any]
async def get_qzone_msg_detail(tid: str, host_uin: int) -> dict[str, Any]
async def get_qzone_user_feeds(
    *, host_uin: int, pos: int = 0, num: int = 5,
    self_uin: int | None = None,
) -> dict[str, Any]
```

The detail path returns a structured comment tree when the QZone response contains it. The service does not infer authors or parent relationships from rendered HTML.

## Write methods

Every write first queries a live login endpoint and requires it to match `[security].write_account_qq` (default `3693525299`). Unknown or ambiguous identity blocks the action.

```python
async def send_qzone_msg(
    content: str, images: list[str] | None = None,
    ugc_right: int = 1, target_uins: list[int] | None = None,
) -> dict[str, Any]

async def delete_qzone_msg(
    tid: str, *, expected_author_qq: int, confirmation: str,
) -> dict[str, Any]

async def like_qzone(tid: str, target_uin: int | None = None) -> dict[str, Any]
async def unlike_qzone(tid: str, target_uin: int | None = None) -> dict[str, Any]
async def comment_qzone(
    tid: str, content: str, target_uin: int | None = None,
    images: list[str] | None = None,
) -> dict[str, Any]

async def reply_qzone_comment(
    *, tid: str, host_uin: int, root_comment_id: str,
    target_uin: int, target_name: str, content: str,
    self_uin: int | None = None,
) -> dict[str, Any]

async def set_qzone_ban(user_id: int, enable: bool = True) -> dict[str, Any]
async def set_qzone_msg_right(
    tid: str, ugc_right: int, target_uins: list[int] | None = None,
) -> dict[str, Any]
```

Deletion additionally requires the exact confirmation string:

```text
DELETE <tid> <expected_author_qq> <current_login_qq>
```

Before deletion or visibility changes, the detail endpoint must confirm both the requested `tid` and an explicit author QQ equal to the current account. Before like/comment actions, the detail endpoint must confirm the target post author. Reply requires a matching top-level comment ID and a verified author in that thread.

Visibility values are `1` (everyone), `4` (friends), `16` (selected friends), `64` (only me), and `128` (everyone except selected friends). Values `16` and `128` require `target_uins`.

## Capability status

```python
async def get_capability_status() -> dict[str, Any]
async def get_verified_write_account() -> int
```

`get_capability_status()` reports the selected provider, discovered service and adapter signatures, masked account status, and unavailable capabilities. `get_verified_write_account()` is for trusted internal background tasks; it raises when the current login cannot be confirmed or does not match configuration.

The current known QZone action contract does not expose profile nickname/signature editing, blacklist reads, per-user feed blocking, or a read-back operation for post visibility. These abilities are reported as unsupported. Do not treat an adapter's unknown action as supported.

## Image Service contract

NAI Artist implements the optional public Service method:

```python
async def generate_image_for_external(
    *, description: str, style: Literal["photo", "drawing"]
) -> str | list[str] | dict[str, Any] | None
```

Other plugins can provide the same method. Neo FoxZone accepts URL, `file://`, `base64://`, Base64 data URI, raw Base64, and recognized dictionaries/lists. External URLs are downloaded with a timeout, DNS results must be public addresses, redirects are rejected, and the result must be a supported raster image. Local files are read only after type and size checks and are converted to Base64 before reaching the adapter. `[limits].max_images` and `[limits].max_image_bytes` apply before publication. Provider or image download failure cancels publication rather than publishing text alone.

## Components

Read Tools:

- `neo_foxzone_list_posts`
- `neo_foxzone_list_feeds`
- `neo_foxzone_read_detail` — read the post author and full top-level comment tree before replying.
- `qzone_read_feed`

Write Tools:

- `neo_foxzone_publish`
- `neo_foxzone_publish_generated`
- `neo_foxzone_delete`
- `neo_foxzone_like`
- `neo_foxzone_unlike`
- `neo_foxzone_comment`
- `neo_foxzone_reply_comment`
- `neo_foxzone_set_blacklist`
- `neo_foxzone_set_visibility`
- `qzone_post_comment`
- `qzone_like_feed`

`neo_foxzone_reply_comment` calls the verified `reply_qzone_comment` service method. Its `root_comment_id` must come from the detail tool, and `target_uin` must be an author in that thread. The `/neo-foxzone reply <tid> <host_uin> <root_comment_id> <target_uin> <target_name> <content>` command uses the same checks.

`/neo-foxzone send-private "<topic>"` asks the configured LLM to write a post and publishes it with visibility `64` (only me). LLM request errors, empty content, and malformed image decisions cancel publication; they never publish the input topic as a generated result. Commands send their result back through the core message sender.

All command and tool components depend only on Neo FoxZone's own Service. The provider plugin does not appear in `manifest.json` plugin or component dependencies.

## QZone message feedback

Components: `neo-foxzone:adapter:qzone_feedback` (platform `qzone`) and `neo-foxzone:chatter:qzone_activity` (group threads). Both depend only on this plugin service. Activity types are `comment`, `reply`, and optional new `post`. No native unread counter or mark-read action is inferred.

`plugin.get_feedback_status()` returns enabled, active adapter, pending count, and the last polling report. `/neo-foxzone feedback-status` exposes the same status. Polling defaults to 30 minutes. First observation establishes a historical baseline unless `feedback.emit_existing_on_first_poll=true`. Set `feedback.include_friend_posts=true` to include new friend posts.

The plugin persists `neo-foxzone/feedback_state` before delivery, acknowledges decisions separately from writes, and never automatically replays an unknown platform write. Outgoing text requires the exact incoming activity message ID as reply reference and the matching thread. The target comment is verified again against fresh detail.

`describe_images(references)` uses configured vision models and validated image data; tool `neo_foxzone_describe_images` and command `vision` return successful descriptions only. Generated content inherits core personality by default. Story, comment, and vision tasks are independently configurable. Direct multimodal requests preserve index association and are split at nine images.
