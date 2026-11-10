"""Claude desktop: what the app keeps on this Mac.

Your claude.ai chats are not on this Mac: the app shows them from Anthropic's servers, and
this tool never connects to the internet. Use Claude's own export (Settings → Privacy →
Export data) to keep a copy of them. What the app does keep locally is backed up here:
the Cowork (local agent) files, the Cowork session disk image, and the app's MCP settings.
"""
from __future__ import annotations

import time
from typing import List

from .. import paths
from ..result import Ctx, Result
from .local import Item, carry_forward, copy_items, keep_previous_copy

LOCAL_ID = "claude-desktop-local"
ROOT = "claude-desktop"


def local_items() -> List[Item]:
    app = paths.claude_app_data()
    # Cowork runs its sessions in a small virtual machine. Their data is in sessiondata.img, a
    # disk image in the app's own format: kept as it is, so it can be put back into the app.
    # (The 10 GB system image next to it is the app's own software and is not copied.)
    return [Item(app / "local-agent-mode-sessions", f"{ROOT}/local/cowork-sessions"),
            Item(app / "vm_bundles" / "claudevm.bundle" / "sessiondata.img",
                 f"{ROOT}/local/cowork-vm/sessiondata.img"),
            Item(app / "claude_desktop_config.json", f"{ROOT}/local/claude_desktop_config.json")]


def run_local(ctx: Ctx) -> Result:
    t0 = time.time()
    res = Result(LOCAL_ID, "claude-desktop", "Claude desktop", "local app data (Cowork)", f"{ROOT}/local")
    prev = ctx.prev(LOCAL_ID)
    its = local_items()
    if not any(i.src.exists() for i in its):
        res.status = "not found"
        keep_previous_copy(ctx, res, prev, "No local Claude desktop data on this Mac.")
    else:
        copy_items(ctx, res, its, prev)
        carry_forward(ctx, res, prev, [f"{ROOT}/local/cowork-sessions", f"{ROOT}/local/cowork-vm"])
        res.info.append("cowork-sessions/ holds the Cowork (local agent) files and scheduled tasks; cowork-vm/ the "
                        "Cowork session disk image, kept as it is so it can be put back into the app. "
                        "claude_desktop_config.json is the MCP server setup and may contain API keys.")
    res.seconds = time.time() - t0
    return res
