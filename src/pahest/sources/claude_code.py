"""Claude Code: local session transcripts and the files around them (~/.claude)."""
from __future__ import annotations

import json
import re
import time
from typing import List, Optional

from .. import paths
from ..result import Ctx, Result
from .local import Item, carry_forward, copy_items, keep_previous_copy

ID = "claude-code"
ROOT = "claude-code"
DATA_DIRS = ["projects", "plans", "todos", "file-history", "paste-cache"]
CONFIG_FILES = ["settings.json", "settings.local.json", "CLAUDE.md", "keybindings.json"]
CONFIG_DIRS = ["skills", "agents", "commands", "output-styles", "hooks"]
PLUGIN_FILES = ["installed_plugins.json", "known_marketplaces.json", "config.json"]
SESSION_RE = re.compile(r"^claude-code/projects/[^/]+/(?!agent-)[^/]+\.jsonl$")


def is_session(rel: str) -> bool:
    return bool(SESSION_RE.match(rel))


def items() -> List[Item]:
    c = paths.claude_dir()
    out = [Item(c / d, f"{ROOT}/{d}") for d in DATA_DIRS]
    out.append(Item(c / "history.jsonl", f"{ROOT}/history.jsonl"))
    out.append(Item(paths.claude_app_data() / "claude-code-sessions", f"{ROOT}/desktop-sessions"))
    out += [Item(c / f, f"{ROOT}/config/{f}") for f in CONFIG_FILES]
    out += [Item(c / d, f"{ROOT}/config/{d}") for d in CONFIG_DIRS]
    out += [Item(c / "plugins" / f, f"{ROOT}/config/plugins/{f}") for f in PLUGIN_FILES]
    out.append(Item(paths.claude_json(), f"{ROOT}/config/claude.json"))
    return out


def found() -> bool:
    return (paths.claude_dir() / "projects").is_dir() or (paths.claude_dir() / "history.jsonl").exists()


def retention_warning() -> Optional[str]:
    days = None
    for name in ("settings.json", "settings.local.json"):
        try:
            d = json.loads((paths.claude_dir() / name).read_text())
            if isinstance(d, dict) and "cleanupPeriodDays" in d:
                days = d["cleanupPeriodDays"]
        except (OSError, ValueError):
            pass
    target = paths.claude_dir() / "settings.json"
    if days is None:
        return ("Claude Code deletes sessions older than 30 days by default. Backups keep them, but to stop "
                f"the deletion add  \"cleanupPeriodDays\": 3650  to {target}")
    if isinstance(days, (int, float)) and days < 365:
        return (f"cleanupPeriodDays is {days}: Claude Code deletes older sessions. Back up more often than every "
                f"{days} days, or raise it to 3650 in {target}")
    return None


def run(ctx: Ctx) -> List[Result]:
    t0 = time.time()
    res = Result(ID, "claude-code", "Claude Code", "local sessions", ROOT, item_label="sessions")
    prev = ctx.prev(ID)
    if not found():
        res.status = "not found"
        keep_previous_copy(ctx, res, prev, "Claude Code data was not found on this Mac.")
        res.seconds = time.time() - t0
        return [res]
    copy_items(ctx, res, items(), prev)
    carry_forward(ctx, res, prev, [f"{ROOT}/{d}" for d in DATA_DIRS] + [f"{ROOT}/desktop-sessions"],
                  is_item=is_session)
    res.items = sum(1 for r in ctx.store.rels_under(ROOT) if is_session(r))
    res.info.append("projects/<project>/<session>.jsonl are the full transcripts, one JSON event per line. "
                    "Subagent transcripts and large tool outputs sit in a folder named after the session.")
    res.info.append("Credentials (.credentials.json, sessions/*.key), shell-snapshots/ and session-env/ are "
                    "deliberately not copied. Files in config/ may contain API keys of MCP servers.")
    w = retention_warning()
    if w:
        res.info.append(w)
    res.seconds = time.time() - t0
    return [res]
