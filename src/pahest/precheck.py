"""Step 1 and 2 of every run: find out what can be backed up, then ask what is needed.

Prechecks write nothing except a tiny probe file that tests whether the backup folder
supports clones (removed at once).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import guard, paths, profile, versions
from .log import Log, human, plural, short_path
from .sources import claude_code, claude_desktop, codex
from .sources.local import plan_files
from .store import TMP_MARK, Previous, Zstd, can_clone, load_previous

STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")
LEFTOVER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})-in-progress$")
PART_IDS = [claude_code.ID, codex.ID, claude_desktop.LOCAL_ID, "readable"]
ONLINE_NOTE = ("Your claude.ai and chatgpt.com chats are not on this Mac, and this tool never goes online. "
               "To keep them, use each app's own export: Claude: Settings → Privacy → Export data; "
               "ChatGPT: Settings → Data controls → Export data.")
CODEX_PLAIN_RATIO = 3.0   # measured: plain sessions are ~2.9x their .zst size
READABLE_RATIO = 0.15     # measured: Markdown + pictures + web pages are ~15% of the transcripts

@dataclass
class Scan:
    key: str
    name: str
    found: bool
    where: str = ""
    items: int = 0
    item_label: str = "files"
    files: int = 0
    bytes: int = 0
    compressed: int = 0         # bytes of .zst files (Codex)
    note: str = ""


@dataclass
class Pre:
    versions: dict
    zstd: Zstd
    scans: Dict[str, Scan]
    folder: Path = None                         # backups folder
    clone_ok: bool = False
    free: int = 0
    needed: int = 0
    previous: Dict[str, Optional[Previous]] = field(default_factory=dict)
    previous_name: str = ""
    dest_error: str = ""
    leftovers: List[Path] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── detection ────────────────────────────────────────────────────────────────

def _scan_local(key: str, name: str, its, is_item, item_label: str) -> Scan:
    plan = plan_files(its)
    sc = Scan(key, name, bool(plan), item_label=item_label)
    sc.files = len(plan)
    sc.bytes = sum(s for _p, _r, s in plan)
    sc.items = len({codex.session_key(r) if key == "codex" else r for _p, r, _s in plan if is_item(r)})
    sc.compressed = sum(s for _p, r, s in plan if r.endswith(".zst"))
    return sc


def scan_sources(vers: dict) -> Dict[str, Scan]:
    out: Dict[str, Scan] = {}
    sc = _scan_local("claude-code", "Claude Code", claude_code.items(), claude_code.is_session, "sessions")
    sc.where = short_path(paths.claude_dir())
    out["claude-code"] = sc
    sc = _scan_local("codex", "Codex", codex.all_items(), codex.is_session, "sessions")
    sc.where = short_path(paths.codex_dir())
    out["codex"] = sc
    apps = vers.get("apps") or {}
    cd = _scan_local("claude-desktop", "Claude desktop", claude_desktop.local_items(), lambda r: False, "files")
    cd.where = "local Cowork data and app settings"
    if not cd.found and "Claude desktop (Claude.app)" in apps:
        cd.note = "installed, but it keeps no local data to back up"
    out["claude-desktop"] = cd
    return out


def find_previous(folder: Path) -> Dict[str, Optional[Previous]]:
    """For each part, the newest finished backup in which that part succeeded."""
    out: Dict[str, Optional[Previous]] = {pid: None for pid in PART_IDS}
    if not folder.is_dir():
        return out
    cache: Dict[Path, Previous] = {}
    candidates = sorted((d for d in folder.iterdir() if d.is_dir() and STAMP_RE.match(d.name)), reverse=True)
    for d in candidates:
        try:
            data = json.loads((d / "backup.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (d / "checksums.sha256").is_file() or data.get("problems"):
            continue  # without its file list a backup cannot be the base for carrying items forward
        for r in data.get("results") or []:
            pid = r.get("id")
            if pid in out and out[pid] is None and r.get("status") in ("ok", "problems"):
                if d not in cache:
                    cache[d] = load_previous(d)
                if not cache[d].hashes:
                    break
                out[pid] = cache[d]
        if all(out.values()):
            break
    return out


def find_leftovers(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(d for d in folder.iterdir() if d.is_dir() and LEFTOVER_RE.match(d.name))


def _file_id(p: Path):
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def _ids_up(p: Path) -> list:
    """The file ids of p and of each of its existing parent folders. Comparing ids (not names)
    is right on macOS, where ~/.CLAUDE and ~/.claude are one folder and firmlinks give one
    folder two paths."""
    out = []
    given = os.path.abspath(os.path.expanduser(str(p)))
    for base in (Path(given), Path(os.path.realpath(given))):    # as typed, and with links resolved
        for q in [base] + list(base.parents):
            i = _file_id(q)
            if i and i not in out:
                out.append(i)
    return out


def _name_inside(a: str, b: str) -> bool:
    a, b = guard._norm(a), guard._norm(b)
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def app_data_conflict(folder: Path) -> str:
    """Why a folder may not hold backups because of the apps' data, or "".

    Checked twice: by file id (right for existing folders whatever the letter case or
    firmlink) and by name, ignoring case (right for app folders that do not exist yet)."""
    real = os.path.realpath(os.path.expanduser(str(folder)))
    own = _file_id(folder)
    if guard._norm(real) == guard._norm(os.path.realpath(paths.home())) or (own and own == _file_id(paths.home())):
        return "it is your home folder; choose a folder of its own, for example ~/pahest-backups"
    for data in paths.app_data_roots():
        d = os.path.realpath(data)
        if _name_inside(d, real):
            return f"it contains {short_path(data)}, where the apps keep their data; choose a folder of its own, " \
                   "for example ~/pahest-backups"
        if _name_inside(real, d) and not any(_name_inside(real, os.path.realpath(c)) for c in paths.cloud_folders()):
            return f"it is inside {short_path(data)}, where the apps keep their data (this tool never writes " \
                   "there); choose a folder of its own, for example ~/pahest-backups"
    ups = _ids_up(folder)
    clouds = {_file_id(c) for c in paths.cloud_folders()} - {None}
    for data in paths.app_data_roots():
        d = _file_id(data)
        if d is None:
            continue
        if own and own in _ids_up(data):
            return f"it contains {short_path(data)}, where the apps keep their data; choose a folder of its own, " \
                   "for example ~/pahest-backups"
        if d in ups and not (clouds & set(ups)):
            return f"it is inside {short_path(data)}, where the apps keep their data (this tool never writes " \
                   "there); choose a folder of its own, for example ~/pahest-backups"
    return ""


def destination_error(folder: Path) -> str:
    """Why this folder cannot hold backups, or "" if it can."""
    conflict = app_data_conflict(folder)
    if conflict:
        return conflict
    parts = folder.parts
    if len(parts) >= 3 and parts[1] == "Volumes" and not Path("/Volumes", parts[2]).is_dir():
        return f"the disk “{parts[2]}” is not connected ({folder})"
    guard.allow(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f"{TMP_MARK}-write-test-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
        next(iter(folder.iterdir()), None)
    except OSError as e:
        hint = " (macOS may need you to allow access to this disk or folder)" if \
            isinstance(e, PermissionError) else ""
        return f"cannot write to {folder}: {e.strerror or e}{hint}"
    return ""


def check_destination(pre: Pre) -> None:
    folder = pre.folder
    pre.dest_error = destination_error(folder)
    if pre.dest_error:
        pre.previous, pre.previous_name, pre.leftovers = {}, "", []
        pre.clone_ok, pre.free, pre.needed = False, 0, 0
        return
    probe_src = None
    for cand in (paths.claude_dir() / "projects", paths.codex_dir() / "sessions", paths.claude_dir()):
        if cand.exists():
            probe_src = cand
            break
    pre.previous = find_previous(folder)
    names = sorted({p.name for p in pre.previous.values() if p}, reverse=True)
    pre.previous_name = names[0] if names else ""
    pre.leftovers = find_leftovers(folder)
    pre.clone_ok = bool(probe_src) and can_clone(probe_src, folder)
    base = folder
    while not base.exists() and base != base.parent:
        base = base.parent
    pre.free = shutil.disk_usage(base).free
    local = sum(s.bytes for s in pre.scans.values())
    comp = pre.scans["codex"].compressed
    plain = int(comp * CODEX_PLAIN_RATIO) if pre.zstd.available else 0
    # readable copies (Markdown + pictures): measured at about 10% of the transcripts' size
    readable_new = int((pre.scans["claude-code"].bytes + int(comp * CODEX_PLAIN_RATIO)) * READABLE_RATIO)
    if pre.previous.get("readable"):
        readable_new = int(readable_new * 0.1)       # unchanged files are clones of the previous backup
    if pre.clone_ok:
        # clones of the sources take no space; plain copies only for new/changed sessions
        pre.needed = (plain if not pre.previous.get(codex.ID) else int(plain * 0.1)) + readable_new
    else:
        pre.needed = local + plain + readable_new


def run(log: Log, answers: profile.Answers) -> Pre:
    """Detection. Prints everything; asks nothing."""
    log.section("Prechecks")
    zstd = Zstd()
    vers = versions.collect(zstd)
    pre = Pre(versions=vers, zstd=zstd, scans=scan_sources(vers))
    pre.folder = answers.folder()

    log.line(log.s.bold("  Apps and data found"))
    apps = vers.get("apps") or {}
    cli = vers.get("cli") or {}
    in_data = vers.get("in_data") or {}

    def cli_ver(name: str, data_key: str) -> str:
        if cli.get(name):
            return versions.short(cli.get(name))
        return f"{in_data[data_key]} (data)" if in_data.get(data_key) else "CLI not found"

    rows = [
        ("Claude Code", cli_ver("Claude Code", "Claude Code (newest session)"), pre.scans["claude-code"]),
        ("Codex", cli_ver("Codex CLI", "Codex (newest session)"), pre.scans["codex"]),
        ("Claude desktop", versions.short(apps.get("Claude desktop (Claude.app)")), pre.scans["claude-desktop"]),
    ]
    for label, ver, sc in rows:
        mark = log.OK if sc.found else log.DOT
        size = ""
        if sc.files:
            size = (f"{plural(sc.items, sc.item_label)} · " if sc.items else "") + \
                f"{plural(sc.files, 'files')} · {human(sc.bytes)}"
        status = "" if sc.found else log.s.dim("not found")
        log.line(f"  {mark} {label:<16} {ver:<16} {size or status}")
        if sc.files:
            log.line(f"      {log.s.dim(sc.where)}")
        if sc.note:
            log.line(f"      {log.s.dim(sc.note)}")
    comp = pre.scans["codex"].compressed
    if comp:
        if zstd.available:
            log.line(f"      {log.s.dim(f'Codex sessions are zstd-compressed; plain copies will be added (≈ {human(comp * CODEX_PLAIN_RATIO)}).')}")
        else:
            log.warn("Codex sessions are zstd-compressed and no decompressor was found (brew install zstd).")

    log.line()
    log.line(log.s.bold("  Tools"))
    log.line(f"  {log.OK if zstd.available else log.WARN} zstd: {zstd.label}")

    check_destination(pre)
    _print_destination(log, pre)

    log.line()
    log.line(f"  {log.DOT} {log.s.dim(ONLINE_NOTE)}")

    w = claude_code.retention_warning()
    if w:
        pre.warnings.append(w)
    for d in pre.leftovers:
        pre.warnings.append(f"An earlier backup did not finish: {d.name} (it will be renamed to "
                            f"{LEFTOVER_RE.match(d.name).group(1)}-interrupted).")
    if pre.warnings:
        log.line()
        log.line(log.s.bold("  Warnings"))
        for w in pre.warnings:
            log.warn(w)
    return pre


def _print_destination(log: Log, pre: Pre) -> None:
    log.line()
    log.line(log.s.bold("  Backup folder"))
    if pre.dest_error:
        log.fail(f"This folder cannot be used: {pre.dest_error}")
        return
    log.line(f"  {log.OK} {pre.folder}")
    how = "same disk as the apps: files are stored as clones (fast, almost no extra space)" if pre.clone_ok \
        else "files are copied in full (clones need the same APFS disk as the apps)"
    log.line(f"      {log.s.dim(how)}")
    mark = log.OK if pre.free > pre.needed * 1.1 + (1 << 30) else log.FAIL
    log.line(f"  {mark} Free space: {human(pre.free)} · this backup needs about {human(pre.needed)} of new space")
    if pre.previous_name:
        log.line(f"  {log.DOT} Previous backup: {pre.previous_name} (used to keep items the apps deleted)")
    else:
        log.line(f"  {log.DOT} No previous backup: this is the first one.")


# ── questions (interactive mode) ─────────────────────────────────────────────

def _yes(ans: str, default: bool) -> bool:
    a = ans.strip().lower()
    if not a:
        return default
    return a.startswith("y")


def ask(log: Log, pre: Pre, answers: profile.Answers) -> Optional[profile.Answers]:
    """Interactive questions. Returns the final answers, or None if the user cancels."""
    log.section("Questions")

    # 1. Backup folder.
    while True:
        ans = log.ask(f"Backup folder [{short_path(pre.folder)}] (Enter to keep):", "")
        if not ans and pre.dest_error:
            log.warn("That folder cannot be used. Type another full path, or press Ctrl-C to stop.")
            continue
        if not ans:
            break
        p = Path(os.path.expanduser(ans))
        if not p.is_absolute():
            log.warn("Please give a full path, for example ~/pahest-backups or /Volumes/Backup/pahest-backups.")
            continue
        answers.backups_folder = ans
        pre.folder = p.resolve()
        check_destination(pre)
        _print_destination(log, pre)
        if not pre.dest_error:
            break

    # 2. zstd.
    if pre.scans["codex"].compressed and not pre.zstd.available:
        a = log.ask("Codex sessions are compressed and zstd is missing. [c] continue with compressed files only, "
                    "[s] stop so you can run  brew install zstd  [c]:", "c", choices="cs")
        if a == "s":
            return None
        answers.without_zstd = "continue"

    # 3. Summary, profile, start.
    log.line()
    log.line(log.s.bold("  The backup will include"))
    for key, sc in pre.scans.items():
        what = f"{plural(sc.files, 'files')} ({sc.where})" if key == "claude-desktop" else \
            f"{plural(sc.items, sc.item_label)}, {plural(sc.files, 'files')}"
        log.line(f"  {log.OK if sc.found else log.DOT} {sc.name}: " + (what if sc.found else "not found"))
    log.line(f"  {log.DOT} Into: {pre.folder}/<date-time>/")

    if _yes(log.ask("Save these answers as a profile for automated runs? [y/N]", "n", choices="yn"), False):
        while True:
            name = log.ask("Profile name [default]:", "default")
            try:
                p = profile.save(name, answers)
                log.ok(f"Saved {p}")
                log.line(f"      {log.s.dim('Run it later with:  pahest --profile' + ('' if name == 'default' else ' ' + name))}")
                break
            except profile.ProfileError as e:
                log.warn(str(e))
    if not _yes(log.ask("Start the backup now? [Y/n]", "y", choices="yn"), True):
        return None
    return answers
