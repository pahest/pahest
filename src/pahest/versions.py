"""Versions of the AI apps and command-line tools whose data is backed up.

Saved into every backup as app-versions.json, so you know which app version wrote
the files (formats change between versions).
"""
from __future__ import annotations

import json
import os
import platform
import plistlib
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__, paths
from .store import Zstd


def app_info(bundle_name: str) -> Optional[Dict[str, str]]:
    p = paths.app_bundle(bundle_name)
    if not p:
        return None
    try:
        with open(p / "Contents" / "Info.plist", "rb") as f:
            info = plistlib.load(f)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {"path": str(p), "version": "unknown"}
    return {
        "path": str(p),
        "version": str(info.get("CFBundleShortVersionString", "unknown")),
        "build": str(info.get("CFBundleVersion", "")),
        "bundle_id": str(info.get("CFBundleIdentifier", "")),
    }


def _find_program(name: str, extra: List[Path]) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    for p in extra:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+[0-9A-Za-z.+]*?)(?:-(?:aarch64|x86_64|arm64|universal).*)?$")


def cli_version(name: str, extra: List[Path]) -> Optional[Dict[str, str]]:
    """The installed version of a command-line tool, read from its install folder.

    The program itself is never run: running another app's program could change its files.
    Installers keep the version in the path (…/claude/versions/2.1.319,
    …/releases/0.162.0-aarch64-apple-darwin/bin/codex, Homebrew's Caskroom/<name>/<version>)
    or in a package.json next to it (npm)."""
    prog = _find_program(name, extra)
    if not prog:
        return None
    real = Path(os.path.realpath(prog))
    for d in list(real.parents)[:5]:
        for meta in ("package.json", f"{name}-package.json"):
            try:
                data = json.loads((d / meta).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and isinstance(data.get("version"), str):
                return {"path": prog, "version": data["version"], "read_from": str(d / meta)}
    for part in reversed(real.parts):
        m = VERSION_RE.match(part)
        if m:
            return {"path": prog, "version": m.group(1), "read_from": str(real)}
    return {"path": prog, "version": "unknown", "read_from": str(real)}


def claude_code_cli() -> Optional[Dict[str, str]]:
    h = paths.home()
    return cli_version("claude", [h / ".claude" / "local" / "claude", h / ".local" / "bin" / "claude",
                                  Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")])


def codex_cli() -> Optional[Dict[str, str]]:
    h = paths.home()
    return cli_version("codex", [Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex"),
                                 h / ".local" / "bin" / "codex"])


def claude_code_version_in_data() -> Optional[str]:
    """The Claude Code version written into the newest session transcript."""
    proj = paths.claude_dir() / "projects"
    newest = None
    try:
        for p in proj.glob("*/*.jsonl"):
            m = p.stat().st_mtime
            if newest is None or m > newest[0]:
                newest = (m, p)
    except OSError:
        return None
    if not newest:
        return None
    try:
        with open(newest[1], "rb") as f:
            f.seek(max(0, os.path.getsize(newest[1]) - 65536))
            tail = f.read().decode("utf-8", "replace").splitlines()
        for line in reversed(tail):
            try:
                v = json.loads(line).get("version")
            except (ValueError, AttributeError):
                continue
            if v:
                return str(v)
    except OSError:
        pass
    return None


def codex_version_in_data(zstd: Zstd) -> Optional[str]:
    """The Codex CLI version in the newest session's first line (session_meta)."""
    sess = paths.codex_dir() / "sessions"
    newest = None
    try:
        for p in sess.rglob("rollout-*"):
            m = p.stat().st_mtime
            if newest is None or m > newest[0]:
                newest = (m, p)
    except OSError:
        return None
    if not newest:
        return None
    p = newest[1]
    try:
        if p.name.endswith(".zst"):
            if not zstd.available:
                return None
            with zstd.open(p) as f:
                first = f.readline(1 << 20)
        else:
            with open(p, "rb") as f:
                first = f.readline(1 << 20)
        meta = json.loads(first.decode("utf-8", "replace"))
        payload = meta.get("payload") or meta
        v = payload.get("cli_version")
        return str(v) if v else None
    except (OSError, ValueError, AttributeError):
        return None


def collect(zstd: Zstd) -> Dict[str, object]:
    mac = platform.mac_ver()[0]
    out: Dict[str, object] = {
        "pahest": __version__,
        "python": platform.python_version(),
        "python_path": sys.executable,
        "os": f"macOS {mac}" if mac else platform.platform(),
        "machine": platform.machine(),
        "apps": {
            "Claude desktop (Claude.app)": app_info("Claude.app"),
            "ChatGPT desktop (ChatGPT.app)": app_info("ChatGPT.app"),
            "Codex desktop (Codex.app)": app_info("Codex.app"),
        },
        "cli": {
            "Claude Code": claude_code_cli(),
            "Codex CLI": codex_cli(),
        },
        "in_data": {
            "Claude Code (newest session)": claude_code_version_in_data(),
            "Codex (newest session)": codex_version_in_data(zstd),
        },
        "zstd": zstd.label,
    }
    out["apps"] = {k: v for k, v in out["apps"].items() if v}  # type: ignore[union-attr]
    return out


def short(v: Optional[Dict[str, str]]) -> str:
    return v.get("version", "unknown") if v else "not installed"
