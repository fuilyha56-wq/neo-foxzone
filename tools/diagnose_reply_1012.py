"""只读检查 Neo FoxZone 运行时能力和当前 Bot 登录状态。

旧版本会假定 NapCat 监听端口，并发送真实评论来比较传输方式。该行为
无法安全地自动化，因此此脚本现在只读取 Neo-MoFox 当前 Service、Adapter
和实时登录接口，不会发布、评论、点赞、删除或修改任何数据。

用法（在 Neo-MoFox 根目录且核心运行时已启动时）：
    uv run python plugins/neo-foxzone/tools/diagnose_reply_1012.py
"""

from __future__ import annotations

import asyncio
import importlib

providers = importlib.import_module("plugins.neo-foxzone.providers")


def mask_qq(value: object) -> str:
    """仅显示账号首尾数字。"""
    text = str(value or "").strip()
    if len(text) < 7:
        return "未知"
    return f"{text[:4]}****{text[-4:]}"


async def main() -> int:
    """读取并打印当前进程可发现的协议能力和登录身份。"""
    snapshot = providers.discover_qzone_provider(refresh=True)
    login = await providers.get_current_login_info()
    print(f"QZone Provider: {snapshot.source or '未发现'}")
    print(f"诊断: {snapshot.diagnostic}")
    print(f"实时账号: {mask_qq(login.get('qq'))}")
    print(f"账号校验: {login.get('status', 'unknown')}")
    if login.get("message"):
        print(f"说明: {login['message']}")
    return 0 if login.get("status") == "confirmed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
