"""Every location the tool reads or writes, in one place.

v1 is macOS only. Other platforms will add their own versions of these functions.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


def home() -> Path:
    return Path.home()


def settings_home() -> Path:
    """The permanent folder: profiles/, logs/ and (by default) the backups themselves."""
    return home() / "pahest-backups"


def app_support() -> Path:
    return home() / "Library" / "Application Support"


# ── Claude Code ──────────────────────────────────────────────────────────────

def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or home() / ".claude").expanduser()


def claude_json() -> Path:
    """Claude Code's main state file (projects, MCP servers). Lives next to ~/.claude."""
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return claude_dir() / ".claude.json"
    return home() / ".claude.json"


def app_data_roots() -> List[Path]:
    """Folders and files where the apps keep their own data. A backup folder may not be
    inside any of them, nor contain them. ~/Library holds the data of every Mac app
    (Claude, ChatGPT, Chrome, ...)."""
    h = home()
    roots = [claude_dir(), claude_json(), codex_dir(), h / ".claude", h / ".claude.json", h / ".agents",
             h / ".local" / "share" / "claude", h / ".local" / "state" / "claude", h / ".cache" / "claude",
             h / "Library", Path("/Applications"), Path(f"/private/tmp/claude-{os.getuid()}")]
    out: List[Path] = []
    for r in roots:
        if r not in out:
            out.append(r)
    return out


def cloud_folders() -> List[Path]:
    """Folders inside ~/Library that are meant for your own files (iCloud Drive, Dropbox, ...)."""
    h = home()
    return [h / "Library" / "Mobile Documents", h / "Library" / "CloudStorage"]


def credential_paths() -> List[Path]:
    """Login files and folders that must never be copied, whatever link leads to them."""
    c = claude_dir()
    return [c / ".credentials.json", c / "sessions", c / "session-env", c / "shell-snapshots",
            codex_dir() / "auth.json"]


# ── Codex ────────────────────────────────────────────────────────────────────

def codex_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or home() / ".codex").expanduser()


# ── Desktop apps ─────────────────────────────────────────────────────────────

def claude_app_data() -> Path:
    return app_support() / "Claude"


def app_bundle(name: str) -> Optional[Path]:
    for base in (Path("/Applications"), home() / "Applications"):
        p = base / name
        if (p / "Contents" / "Info.plist").exists():
            return p
    return None
