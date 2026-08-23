"""把不同 OneBot QZone 响应归一化为可安全回复的评论候选。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ReplySource = Literal["own_post", "friend_feed"]

_OWN_POST_COMMENT_KEYS = (
    "commentlist",
    "comment_list",
)
_FRIEND_FEED_COMMENT_KEYS = (
    "comments",
    "commentlist",
    "comment_list",
)
_CHILD_COMMENT_KEYS = (
    "list_3",
    "reply_list",
    "sub_comments",
)


@dataclass(frozen=True, slots=True)
class ReplyCandidate:
    """一条具备足够上下文、可安全交给自动回复器处理的评论。"""

    source: ReplySource
    post_id: str
    post_owner_uin: int | None
    post_content: str
    comment_id: str
    commenter_uin: int
    commenter_name: str
    comment_content: str
    parent_comment_id: str | None
    root_comment_id: str | None
    detail_verified: bool
    parent_content: str
    target_uin: int | None

    @property
    def identity(self) -> str:
        """返回适合持久去重的稳定标识。"""
        owner = self.post_owner_uin or 0
        return f"{self.source}:{owner}:{self.post_id}:{self.comment_id}"


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    """把未知值收敛为字典列表。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """返回一组字段别名中的首个非空值。"""
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _string_value(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    """读取并清理字符串字段。"""
    value = _first_value(item, keys)
    return str(value).strip() if value is not None else ""


def _int_value(item: dict[str, Any], keys: tuple[str, ...]) -> int:
    """兼容字符串和整数形式的 QQ 号。"""
    value = _first_value(item, keys)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _comment_lists(
    item: dict[str, Any],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    """只从明确的评论容器读取字典列表。"""
    children: list[dict[str, Any]] = []
    for key in keys:
        children.extend(_as_dict_list(item.get(key)))
    return children


def _child_comments(comment: dict[str, Any]) -> list[dict[str, Any]]:
    """读取协议中明确标识为回复列表的嵌套评论。"""
    return _comment_lists(comment, _CHILD_COMMENT_KEYS)


def _post_comments(
    post: dict[str, Any],
    source: ReplySource,
) -> list[dict[str, Any]]:
    """读取说说上的顶层评论列表。"""
    keys = (
        _OWN_POST_COMMENT_KEYS
        if source == "own_post"
        else _FRIEND_FEED_COMMENT_KEYS
    )
    return _comment_lists(post, keys)


def _comment_id(comment: dict[str, Any], source: ReplySource) -> str:
    """读取评论 ID。"""
    keys = ("comment_id", "commentid", "commentId")
    if source == "friend_feed":
        keys = (*keys, "id")
    return _string_value(comment, keys)


def _comment_uin(comment: dict[str, Any]) -> int:
    """读取评论者 QQ 号。"""
    return _int_value(
        comment,
        ("uin", "user_id", "userId", "qq"),
    )


def _comment_content(comment: dict[str, Any]) -> str:
    """读取评论正文。"""
    return _string_value(comment, ("content", "text", "comment"))


def _parent_comment_id(comment: dict[str, Any]) -> str | None:
    """读取明确的父评论 ID。"""
    value = _string_value(
        comment,
        (
            "parent_comment_id",
            "parentCommentId",
            "reply_comment_id",
            "replyCommentId",
        ),
    )
    return value or None


def _reply_to_uin(comment: dict[str, Any]) -> int:
    """读取评论明确回复的 QQ 号。"""
    return _int_value(
        comment,
        (
            "reply_to_uin",
            "reply_uin",
            "replyuin",
            "to_uin",
        ),
    )


@dataclass(slots=True)
class _CommentGraph:
    """单条说说中已由明确字段证明的评论关系图。"""

    ordered_ids: list[str]
    by_id: dict[str, dict[str, Any]]
    parent_by_id: dict[str, str]
    children_by_parent: dict[str, list[dict[str, Any]]]


def _build_comment_graph(
    post: dict[str, Any],
    source: ReplySource,
) -> _CommentGraph:
    """合并嵌套与平铺评论，并在关系冲突时关闭该说说的候选。"""
    ordered_ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    parent_by_id: dict[str, str] = {}
    invalid = False

    def visit(comment: dict[str, Any], structural_parent_id: str | None) -> None:
        nonlocal invalid
        comment_id = _comment_id(comment, source)
        if not comment_id or comment_id in by_id:
            invalid = True
            return
        explicit_parent_id = _parent_comment_id(comment)
        if (
            structural_parent_id
            and explicit_parent_id
            and structural_parent_id != explicit_parent_id
        ):
            invalid = True
            return
        parent_id = explicit_parent_id or structural_parent_id
        ordered_ids.append(comment_id)
        by_id[comment_id] = comment
        if parent_id:
            parent_by_id[comment_id] = parent_id
        for child in _child_comments(comment):
            visit(child, comment_id)

    for root in _post_comments(post, source):
        visit(root, None)
    if invalid:
        return _CommentGraph([], {}, {}, {})

    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for comment_id, parent_id in parent_by_id.items():
        children_by_parent.setdefault(parent_id, []).append(by_id[comment_id])
    return _CommentGraph(
        ordered_ids=ordered_ids,
        by_id=by_id,
        parent_by_id=parent_by_id,
        children_by_parent=children_by_parent,
    )


def _build_candidate(
    *,
    source: ReplySource,
    post: dict[str, Any],
    comment: dict[str, Any],
    parent: dict[str, Any] | None,
    comment_id: str,
    parent_comment_id: str | None,
    root_comment_id: str | None,
    detail_verified: bool,
    target_uin: int | None,
) -> ReplyCandidate | None:
    """从已通过安全判据的原始对象构造候选。"""
    post_id = _string_value(post, ("tid", "key", "id", "feedskey"))
    commenter_uin = _comment_uin(comment)
    comment_content = _comment_content(comment)
    if not post_id or not comment_id or commenter_uin <= 0 or not comment_content:
        return None
    return ReplyCandidate(
        source=source,
        post_id=post_id,
        post_owner_uin=(
            _int_value(post, ("uin", "user_id", "owner_uin", "ownerUin")) or None
        ),
        post_content=_string_value(post, ("content", "text", "summary")),
        comment_id=comment_id,
        commenter_uin=commenter_uin,
        commenter_name=_string_value(comment, ("nickname", "name", "nick")),
        comment_content=comment_content,
        parent_comment_id=parent_comment_id,
        root_comment_id=root_comment_id,
        detail_verified=detail_verified,
        parent_content=_comment_content(parent or {}),
        target_uin=target_uin,
    )


def _root_comment_id(graph: _CommentGraph, comment_id: str) -> str | None:
    """解析评论所在线程的顶层评论 ID，关系不完整时拒绝猜测。"""
    current_id = comment_id
    visited: set[str] = set()
    while True:
        if current_id in visited or current_id not in graph.by_id:
            return None
        visited.add(current_id)
        parent_id = graph.parent_by_id.get(current_id)
        if parent_id is None:
            return current_id
        current_id = parent_id


def _own_post_candidates(
    posts: list[dict[str, Any]],
    bot_uin: int,
    detail_verified: bool,
) -> list[ReplyCandidate]:
    """找出自己说说中线程末尾尚未被 Bot 回复的评论。"""
    candidates: list[ReplyCandidate] = []
    for post in posts:
        graph = _build_comment_graph(post, "own_post")
        for comment_id in graph.ordered_ids:
            comment = graph.by_id[comment_id]
            if _comment_uin(comment) in {0, bot_uin}:
                continue
            if any(
                _comment_uin(child) == bot_uin
                for child in graph.children_by_parent.get(comment_id, [])
            ):
                continue
            parent_id = graph.parent_by_id.get(comment_id)
            candidate = _build_candidate(
                source="own_post",
                post=post,
                comment=comment,
                parent=graph.by_id.get(parent_id or ""),
                comment_id=comment_id,
                parent_comment_id=parent_id,
                root_comment_id=_root_comment_id(graph, comment_id),
                detail_verified=detail_verified,
                target_uin=None,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _friend_feed_candidates(
    feeds: list[dict[str, Any]],
    bot_uin: int,
    known_bot_comment_ids: dict[str, set[str]],
    known_bot_comment_roots: dict[str, dict[str, str]],
    detail_verified: bool,
) -> list[ReplyCandidate]:
    """找出好友说说中可证明为直接回复 Bot 的未处理评论。"""
    candidates: list[ReplyCandidate] = []
    for post in feeds:
        owner_uin = _int_value(post, ("uin", "user_id", "owner_uin", "ownerUin"))
        if owner_uin <= 0 or owner_uin == bot_uin:
            continue
        graph = _build_comment_graph(post, "friend_feed")
        bot_comment_ids = {
            comment_id
            for comment_id, item in graph.by_id.items()
            if _comment_uin(item) == bot_uin
        }
        post_id = _string_value(post, ("tid", "key", "id", "feedskey"))
        post_key = f"{owner_uin}:{post_id}"
        bot_comment_ids.update(known_bot_comment_ids.get(post_key, set()))
        persisted_roots = known_bot_comment_roots.get(post_key, {})
        for comment_id in graph.ordered_ids:
            comment = graph.by_id[comment_id]
            if _comment_uin(comment) in {0, bot_uin}:
                continue
            parent_id = graph.parent_by_id.get(comment_id)
            directly_replies_to_bot = (
                parent_id in bot_comment_ids if parent_id else False
            ) or _reply_to_uin(comment) == bot_uin
            if not directly_replies_to_bot:
                continue
            if any(
                _comment_uin(reply) == bot_uin
                for reply in graph.children_by_parent.get(comment_id, [])
            ):
                continue
            root_comment_id = _root_comment_id(graph, comment_id)
            if root_comment_id is None and parent_id in bot_comment_ids:
                persisted_root = str(persisted_roots.get(parent_id, "")).strip()
                root_comment_id = persisted_root or None
            if root_comment_id is None:
                continue
            candidate = _build_candidate(
                source="friend_feed",
                post=post,
                comment=comment,
                parent=graph.by_id.get(parent_id or ""),
                comment_id=comment_id,
                parent_comment_id=parent_id,
                root_comment_id=root_comment_id,
                detail_verified=detail_verified,
                target_uin=owner_uin,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def extract_reply_candidates(
    response: dict[str, Any],
    *,
    bot_uin: int,
    known_bot_comment_ids: dict[str, set[str]] | None = None,
    known_bot_comment_roots: dict[str, dict[str, str]] | None = None,
    detail_verified: bool = False,
) -> list[ReplyCandidate]:
    """从 OneBot 响应中提取可安全自动回复的评论。"""
    if bot_uin <= 0 or not isinstance(response, dict):
        return []
    data = response.get("data")
    payload = data if isinstance(data, dict) else response
    posts = _as_dict_list(payload.get("msglist"))
    feeds = _as_dict_list(payload.get("feeds"))
    return [
        *_own_post_candidates(posts, bot_uin, detail_verified),
        *_friend_feed_candidates(
            feeds,
            bot_uin,
            known_bot_comment_ids or {},
            known_bot_comment_roots or {},
            detail_verified,
        ),
    ]


__all__ = ["ReplyCandidate", "ReplySource", "extract_reply_candidates"]