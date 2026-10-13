"""Temporary client; credentials stay in memory and all post writes use the service."""

import json
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path.cwd()
STATE = Path(__file__).with_name("test_state.json")
config = tomllib.loads((ROOT / "config/core.toml").read_text(encoding="utf-8"))["http_router"]
keys = [key for key in config.get("api_keys", []) if key]
headers = {"Content-Type": "application/json"}
if keys:
    headers["X-API-Key"] = keys[0]
BASE = f"http://127.0.0.1:{config['http_router_port']}"
snow = json.loads(Path("E:/SnowLuma-v1.9.7-win-x64/config/onebot_3693525299.json").read_text(encoding="utf-8"))
ONEBOT = f"http://127.0.0.1:{snow['networks']['httpServers'][0]['port']}"


def call(path, body=None, base=BASE):
    request = urllib.request.Request(
        base + path, headers=headers if base == BASE else {"Content-Type": "application/json"},
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read().decode()[:500]}") from None


def emit(data):
    print(json.dumps(data, ensure_ascii=False))


def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def read():
    return json.loads(STATE.read_text(encoding="utf-8"))


def detail(state):
    return call("/_foxzone_live_probe/post", {"tid": state["tid"]})["detail"]


def send(text):
    return call("/_foxzone_live_probe/message", {"text": text})


phase = sys.argv[1]
if phase == "reload":
    for name in ("neo-foxzone", "neo-foxzone-live-probe"):
        result = call(f"/webui/api/plugin/{name}/reload", {})
        emit({"reload": name, "success": result.get("data", {}).get("success")})
elif phase == "status":
    emit(send("/neo-foxzone status"))
    time.sleep(2)
    emit(call("/_foxzone_live_probe/events"))
elif phase == "probe-reload":
    result = call("/webui/api/plugin/neo-foxzone-live-probe/reload", {})
    emit({"probe_reload": result.get("data", {}).get("success")})
elif phase == "runtime-status":
    emit(call("/_foxzone_live_probe/status"))
elif phase == "refresh-config":
    emit(call("/_foxzone_live_probe/refresh-config", {}))
elif phase == "restore":
    path = ROOT / "config/plugins/neo-foxzone/config.toml"
    original = tomllib.loads(Path(__file__).with_name("original_config.toml").read_text(encoding="utf-8"))
    expected = original["polling"]["enabled"]
    current = path.read_text(encoding="utf-8")
    snapshot = tomllib.loads(current)
    cooldown = json.loads((ROOT / "data/json_storage/neo-foxzone/polling_state.json").read_text(encoding="utf-8"))
    assert float(cooldown.get("rate_limit_cooldown_until", 0)) > time.time() + 60, "do not resume startup writes during test cleanup"
    if snapshot["polling"]["enabled"] != expected:
        match = re.search(r"(?ms)^\[polling\]\s*\n.*?(?=^\[|\Z)", current)
        assert match
        section, count = re.subn(r"(?m)^enabled\s*=\s*(?:true|false)\s*$", "enabled = " + str(expected).lower(), match.group(0), count=1)
        assert count == 1
        updated = current[:match.start()] + section + current[match.end():]
        updated_config = tomllib.loads(updated)
        snapshot["polling"]["enabled"] = expected
        assert updated_config == snapshot, "restore must change only polling.enabled"
        path.write_text(updated, encoding="utf-8")
    result = call("/webui/api/plugin/neo-foxzone/reload", {})
    emit({"polling_restored": expected, "plugin_reload_success": result.get("data", {}).get("success"), "startup_writes_guarded_by_existing_cooldown": True})
elif phase == "final-verify":
    state = read()
    assert state.get("cleaned") and state.get("generated_cleaned")
    response = call("/get_login_info", {}, ONEBOT)
    assert response["status"] == "ok" and str(response["data"]["user_id"]) == "3693525299"
    response = call("/get_qzone_msg_list", {"pos": 0, "num": 20}, ONEBOT)
    assert response["status"] == "ok"
    marks = (state["marker"], state["generated_marker"])
    remaining = [post for post in response["data"]["msglist"] if any(mark in str(post.get("content", "")) for mark in marks)]
    assert not remaining
    emit({"live_account_verified": True, "all_current_test_posts_absent": True})
elif phase == "events":
    emit(call("/_foxzone_live_probe/events"))
elif phase == "flow":
    emit(call("/_foxzone_live_probe/flow"))
elif phase == "wake":
    emit(call("/_foxzone_live_probe/wake", {}))
elif phase == "publish":
    marker = "[FZLIVE-" + uuid.uuid4().hex[:8] + "]"
    content = marker + " 私密联调测试：请用一句话回复测试评论。"
    emit(send("/neo-foxzone publish " + json.dumps(content, ensure_ascii=False) + ' "" 64'))
    time.sleep(2)
    result = call("/get_qzone_msg_list", {"pos": 0, "num": 20}, ONEBOT)
    assert result["status"] == "ok"
    matches = [post for post in result["data"]["msglist"] if marker in str(post.get("content", ""))]
    assert len(matches) == 1, "expected one own test post"
    state = {"marker": marker, "tid": matches[0]["tid"], "created_at": time.time()}
    save(state)
    post = detail(state)
    assert str(post["uin"]) == "3693525299"
    emit({"command_publish_verified": True, "private": True, "marker": marker, "author_verified": True})
elif phase == "comment":
    state = read()
    comment = state["marker"] + " 今天的测试完成后，你想说什么？"
    emit(send('/neo-foxzone comment ' + state["tid"] + ' ' + json.dumps(comment, ensure_ascii=False) + ' 3693525299'))
    time.sleep(2)
    post = detail(state)
    matches = [item for item in post.get("commentlist", []) if state["marker"] in str(item.get("content", "")) and str(item.get("uin")) == "3693525299"]
    assert len(matches) == 1, "top-level test comment not confirmed"
    root = matches[0]
    state.update(root_id=str(root["comment_id"]), target_name=root.get("name") or root.get("nickname") or "FZLIVE", baseline_children=len(root.get("list_3", [])))
    save(state)
    emit({"root_comment_verified": True, "author_verified": True, "children_before": state["baseline_children"]})
elif phase == "ask":
    state = read()
    text = (
        "FZLIVE受控联调：仅针对你的私密测试说说 tid=" + state["tid"] +
        "，说说作者 QQ=3693525299。请先调用 neo_foxzone_read_detail 读取并核验评论树，"
        "找到顶层 comment_id=" + state["root_id"] + "、作者 QQ=3693525299 的测试评论。"
        "根据那条评论自主决定一句自然的回复，保留 FZLIVE 测试标记，然后调用 "
        "neo_foxzone_reply_comment 回复到该顶层评论下。目标昵称从详情读取。"
        "执行成功后告诉我结果。只操作这个测试评论，不要删除说说。"
    )
    emit(send(text))
elif phase == "verify":
    state = read()
    post = detail(state)
    root = next(item for item in post.get("commentlist", []) if str(item.get("comment_id")) == state["root_id"])
    children = root.get("list_3", [])
    replies = [item for item in children if str(item.get("uin")) == "3693525299"]
    emit({"root_present": True, "children": len(children), "new_bot_reply": len(children) > state["baseline_children"] and bool(replies), "reply_preview": str(replies[-1].get("content", ""))[:160] if replies else ""})
elif phase == "requests":
    response = call("/_inspector/api/requests")
    emit({"summary_type": type(response).__name__, "keys": list(response) if isinstance(response, dict) else [], "count": len(response) if isinstance(response, list) else None})
    items = response if isinstance(response, list) else response.get("requests", response.get("data", []))
    for item in items:
        if not isinstance(item, dict) or item.get("request_name") not in {"neo_fatum_chatter", "neo_foxzone_content"}:
            continue
        record = call("/_inspector/api/requests/" + str(item["id"]))
        serialized = json.dumps(record, ensure_ascii=False)
        if "FZLIVE" in serialized:
            emit({"request_name": item.get("request_name"), "model": item.get("model"), "msg_count": item.get("msg_count"), "tool_count": item.get("tool_count"), "record_keys": list(record), "includes_detail_tool": "neo_foxzone_read_detail" in serialized, "includes_reply_tool": "neo_foxzone_reply_comment" in serialized})
            def tool_calls(value):
                found = []
                if isinstance(value, dict):
                    for invocation in value.get("tool_calls", []):
                        function = invocation.get("function", {})
                        name = function.get("name", "")
                        if "foxzone" in name:
                            found.append(name)
                    for nested in value.values():
                        found.extend(tool_calls(nested))
                elif isinstance(value, list):
                    for nested in value:
                        found.extend(tool_calls(nested))
                return found
            emit({"actual_tool_calls_in_history": sorted(set(tool_calls(record.get("params", {}))))})
elif phase == "generated":
    marker = "[FZLIVE-" + uuid.uuid4().hex[:8] + "]"
    state = read()
    state["generated_marker"] = marker
    save(state)
    topic = marker + "是今天的联调暗号，请原样保留这个暗号，写一句简短的测试结束感想。"
    emit(send("/neo-foxzone send-private " + json.dumps(topic, ensure_ascii=False)))
    time.sleep(2)
    result = call("/get_qzone_msg_list", {"pos": 0, "num": 20}, ONEBOT)
    assert result["status"] == "ok"
    matches = [post for post in result["data"]["msglist"] if marker in str(post.get("content", ""))]
    assert len(matches) == 1, "expected one generated marked test post"
    state["generated_tid"] = matches[0]["tid"]
    save(state)
    post = call("/_foxzone_live_probe/post", {"tid": state["generated_tid"]})["detail"]
    assert str(post["uin"]) == "3693525299"
    emit({"generated_command_verified": True, "author_verified": True, "generated_preview": str(post.get("content", ""))[:180], "echoed_input": str(post.get("content", "")) == topic})
elif phase == "generated-verify":
    state = read()
    result = call("/get_qzone_msg_list", {"pos": 0, "num": 20}, ONEBOT)
    assert result["status"] == "ok"
    matches = [post for post in result["data"]["msglist"] if state["generated_marker"] in str(post.get("content", ""))]
    assert matches, "generated marked test post missing"
    state["generated_tids"] = [post["tid"] for post in matches]
    save(state)
    for tid in state["generated_tids"]:
        post = call("/_foxzone_live_probe/post", {"tid": tid})["detail"]
        assert str(post["uin"]) == "3693525299"
        emit({"generated_command_verified": True, "author_verified": True, "generated_preview": str(post.get("content", ""))[:180]})
    emit({"generated_test_posts": len(matches)})
elif phase == "cleanup-generated":
    state = read()
    tids = state.get("generated_tids") or [state["generated_tid"]]
    for tid in tids:
        result = call("/_foxzone_live_probe/post", {"tid": tid, "delete": True})
        assert result["success"], result
        time.sleep(2)
    time.sleep(2)
    response = call("/get_qzone_msg_list", {"pos": 0, "num": 20}, ONEBOT)
    assert not any(str(post.get("tid")) in tids for post in response["data"]["msglist"])
    state["generated_cleaned"] = True
    save(state)
    emit({"generated_test_post_absent": True})
elif phase == "cleanup":
    state = read()
    result = call("/_foxzone_live_probe/post", {"tid": state["tid"], "delete": True})
    assert result["success"], result
    time.sleep(2)
    result = call("/get_qzone_msg_list", {"pos": 0, "num": 20}, ONEBOT)
    remaining = [post for post in result["data"]["msglist"] if str(post.get("tid")) == state["tid"] or state["marker"] in str(post.get("content", ""))]
    assert not remaining, "test post still visible"
    state["cleaned"] = True
    save(state)
    emit({"registered_delete_succeeded": True, "test_post_absent": True})
elif phase == "finish":
    emit(call("/_foxzone_live_probe/finish", {}))
else:
    raise ValueError("unknown phase")
