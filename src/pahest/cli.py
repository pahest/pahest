"""pahest: the command line and the run flow.

Every run: prechecks -> questions (or a saved profile) -> full backup -> verification -> report.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import HOME_URL, SLOGAN, __version__, guard, paths, precheck, profile, readable, regenerate, report, template, verify
from .log import Log, fmt_dur, human, plural
from .result import Ctx, Result
from .sources import claude_code, claude_desktop, codex
from .sources.local import keep_previous_copy
from .store import TMP_MARK, DiskFull, Store, write_checksums, write_deleted_list, write_source_manifest

EXIT_OK, EXIT_PROBLEMS, EXIT_CANCELLED, EXIT_INTERRUPTED = 0, 1, 2, 130
LOCK_NAME = ".pahest.lock"

DESCRIPTION = """\
Make a full local backup of your Claude Code and Codex sessions (and the Claude desktop
app's local data) into a new folder named after the start time.

Every run checks what can be backed up, asks what it needs, makes the backup, verifies
it, and writes report.html and index.html. It only reads the apps' files and never
connects to the internet. Settings and logs live in ~/pahest-backups."""

EPILOG = """\
examples:
  pahest                  ask the questions, then back up everything
  pahest --profile        no questions: use the answers saved as "default"
  pahest --profile work   no questions: use the answers saved as "work"
  pahest --regenerate     rebuild index.html and the readable pages of the newest backup
  pahest --regenerate ~/pahest-backups/2026-11-09-17-29-11
                                  the same for that backup (nothing is backed up again)
"""


def _lock(home: Path) -> Optional[Path]:
    home.mkdir(parents=True, exist_ok=True)
    lock = home / LOCK_NAME
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
                os.kill(pid, 0)
                return None            # another run is alive
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                try:
                    lock.unlink()      # stale lock from a run that was killed
                except OSError:
                    return None
    return None


def _cancelled_record(log: Log, logs_dir: Path, stamp: str, started: datetime, mode: str, why: str) -> int:
    log.line()
    log.line(f"{log.DOT} {why} Nothing was backed up.")
    log.attach(logs_dir / f"{stamp}.log")
    data = {"tool": "pahest", "format": 1, "name": stamp, "status": "cancelled", "mode": mode,
            "started": started.isoformat(timespec="seconds"), "seconds": time.time() - started.timestamp(),
            "backup_folder": "", "results": [], "totals": {}, "note": why}
    (logs_dir / f"{stamp}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    report.write_logs_index(logs_dir)
    log.detach_all()
    return EXIT_CANCELLED


def _finalize_result(r: Result, store: Store, ctx: Ctx) -> None:
    rels = store.rels_under(r.folder)
    r.files = len(rels)
    r.bytes = sum(store.manifest[x].size for x in rels)
    prev = ctx.prev(r.id)
    if prev:
        r.compared_to = prev.name
        for x in rels:
            h = prev.hashes.get(x)
            if h is None:
                if x not in store.deleted:
                    r.new += 1
            elif h != store.manifest[x].sha:
                r.changed += 1
    r.finish_status()


def _print_result(log: Log, r: Result, folder: Path) -> None:
    mark = {"ok": log.OK, "problems": log.WARN, "failed": log.FAIL, "interrupted": log.FAIL}.get(r.status, log.DOT)
    items = f"{plural(r.items, r.item_label)} · " if r.items is not None else ""
    log.line(f"  {mark} {r.part}: {r.status} · {items}{plural(r.files, 'files')} · {human(r.bytes)}")
    log.line(f"    {log.s.dim('→ ' + str(folder / r.folder))}")
    for k, v in r.counts.items():
        if k != "requests":
            log.line(f"    {log.s.dim(f'{k}: {v:,}')}")
    if r.carried_items or r.carried:
        log.line(f"    {log.s.dim(f'kept from earlier backups (deleted at source): {r.carried_items or r.carried:,}')}")
    for n in r.notes:
        log.line(f"    {log.WARN} {n}")
    for p in r.failed[:5]:
        log.line(f"    {log.FAIL} {p}")
    if len(r.failed) > 5:
        log.line(f"    {log.FAIL} … and {len(r.failed) - 5:,} more problems (see the report)")
    if r.unavailable:
        log.line(f"    {log.s.dim(f'{len(r.unavailable):,} items were no longer available on the server (listed in the report)')}")


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while path.with_name(f"{path.name}-{n}").exists():
        n += 1
    return path.with_name(f"{path.name}-{n}")


def run_backup(log: Log, pre: precheck.Pre, answers: profile.Answers, stamp: str, started: datetime,
               mode: str, profile_name: Optional[str]) -> int:
    folder = pre.folder
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    logs_dir = paths.settings_home() / "logs"
    for d in pre.leftovers:
        try:
            d.rename(_unique(d.with_name(d.name.replace("-in-progress", "-interrupted"))))
        except OSError:
            pass
    work = folder / f"{stamp}-in-progress"
    work.mkdir(mode=0o700)
    log.attach(work / "backup.log")
    log.attach(logs_dir / f"{stamp}.log")
    store = Store(work)
    ctx = Ctx(store, log, pre.previous, started.strftime("%Y-%m-%d"), pre.zstd)
    store.add_bytes("app-versions.json", (json.dumps(pre.versions, indent=2) + "\n").encode("utf-8"))

    # (section title, function, the part it produces: id, source, name, part, folder)
    steps = [
        ("Claude Code", lambda: claude_code.run(ctx),
         (claude_code.ID, "claude-code", "Claude Code", "local sessions", claude_code.ROOT)),
        ("Codex", lambda: codex.run(ctx),
         (codex.ID, "codex", "Codex", "local sessions", codex.ROOT)),
        ("Claude desktop", lambda: [claude_desktop.run_local(ctx)],
         (claude_desktop.LOCAL_ID, "claude-desktop", "Claude desktop", "local app data (Cowork)",
          f"{claude_desktop.ROOT}/local")),
        # made from the backup's own copies, after everything else is saved
        ("Readable copies", lambda: [readable.run(ctx, stamp)],
         (readable.ID, "readable", "Readable copies", "chats as Markdown, pictures as files", readable.ROOT)),
    ]
    extra_problems: List[str] = []
    results: List[Result] = []
    ver = None
    interrupted = disk_full = False
    try:
        for title, fn, part in steps:
            log.section(title)
            try:
                part_results = fn()
            except (KeyboardInterrupt, DiskFull):
                raise
            except Exception as e:  # noqa: BLE001 - a bug in one source must not lose the others
                log.fail(f"{title} stopped because of an unexpected error: {type(e).__name__}: {e}")
                log.line("    " + log.s.dim(" ".join(traceback.format_exc().splitlines()[-3:])))
                pid, source, name, part_name, part_folder = part
                r = Result(pid, source, name, part_name, part_folder, status="failed")
                r.problem(f"unexpected error: {type(e).__name__}: {e} — please report this.")
                r.expected += store.rels_under(part_folder)
                keep_previous_copy(ctx, r, ctx.prev(pid), "This part stopped with an unexpected error.")
                part_results = [r]
            for r in part_results:
                _finalize_result(r, store, ctx)
                _print_result(log, r, folder / stamp)
                results.append(r)
        log.section("Verification")
        ver = verify.run(store, results, log, pre.zstd)
        if ver.ok:
            log.ok(verify.summary_line(ver))
        else:
            log.fail(f"{len(ver.problems):,} problems found. " + verify.summary_line(ver))
            for p in ver.problems[:10]:
                log.line(f"    {log.FAIL} {p}")
        if ver.warnings:
            log.line(f"    {log.s.dim(f'{len(ver.warnings):,} warnings (listed in the report)')}")
    except (KeyboardInterrupt, DiskFull) as e:
        interrupted = True
        disk_full = isinstance(e, DiskFull)
        log.line()
        if disk_full:
            log.fail(f"The backup disk is full ({folder}). The backup stopped; free some space and run it again.")
        else:
            log.fail("Interrupted. The files saved so far are kept; this backup is marked as interrupted.")
        for dirpath, _dirs, files in os.walk(work):
            for name in files:
                if TMP_MARK in name:
                    try:
                        os.unlink(os.path.join(dirpath, name))
                    except OSError:
                        pass

    try:
        write_deleted_list(store)
        write_source_manifest(store)
        write_checksums(store)
    except OSError as e:
        log.fail(f"Could not write the checksum list: {e}")
        extra_problems.append(f"checksums.sha256, source-manifest.jsonl or deleted-at-source.txt could not be "
                              f"written: {e}")
    final = _unique(folder / (stamp if not interrupted else f"{stamp}-interrupted"))
    work.rename(final)
    for v in guard.violations:
        extra_problems.append(f"read-only guard refused an action (please report this bug): {v}")

    any_problem = any(r.status in ("failed", "problems") for r in results) or (ver is not None and not ver.ok) \
        or bool(extra_problems)
    status = "interrupted" if interrupted else ("completed with problems" if any_problem else "completed")
    totals = {"files": len(store.manifest), "bytes": sum(e.size for e in store.manifest.values()),
              "new_space": sum(e.size for e in store.manifest.values() if e.how in ("copy", "write")),
              "deleted_at_source": len(store.deleted)}
    prechecks = {
        "clone_ok": pre.clone_ok, "free": pre.free, "needed": pre.needed, "previous": pre.previous_name,
        "warnings": pre.warnings,
    }
    meta = {"name": final.name, "status": status, "mode": mode, "profile": profile_name,
            "started": started.isoformat(timespec="seconds"),
            "finished": datetime.now().isoformat(timespec="seconds"),
            "seconds": round(time.time() - started.timestamp(), 1), "backup_folder": str(final),
            "answers": asdict(answers), "problems": extra_problems,
            "read_only": {"guard": guard.is_armed(), "refused": list(guard.violations),
                          "wrote_only_in": guard.allowed_roots()}}
    data = report.build_data(meta, pre.versions, prechecks, results, ver, totals)
    try:
        out = report.write_report(final, logs_dir, data)
    except OSError as e:
        log.fail(f"Could not write the report: {e}")
        out = {"report": final / "report.html", "index": logs_dir / "index.html"}

    log.section("Done")
    mark = log.FAIL if interrupted else (log.WARN if any_problem else log.OK)
    log.line(f"{mark} Backup {status} in {fmt_dur(meta['seconds'])}: {totals['files']:,} files, "
             f"{human(totals['bytes'])} ({human(totals['new_space'])} written in full, the rest stored as clones).")
    if totals["deleted_at_source"]:
        log.line(f"  {plural(totals['deleted_at_source'], 'files')} that the apps deleted are still kept "
                 "(see deleted-at-source.txt).")
    log.line()
    log.line(f"  Backup folder:  {log.s.bold(str(final))}")
    if (final / "index.html").exists():
        log.line(f"  Your chats:     {(final / 'index.html').as_uri()}")
    log.line(f"  Report:         {Path(out['report']).as_uri()}")
    log.line(f"  All backups:    {Path(out['index']).as_uri()}")
    log.line(log.s.dim("  To open a link, hold Cmd and click it (in Apple's Terminal: hold Cmd and double-click)."))
    log.detach_all()
    if disk_full:
        return EXIT_PROBLEMS
    if interrupted:
        return EXIT_INTERRUPTED
    return EXIT_PROBLEMS if any_problem else EXIT_OK


def _print_backups(log: Log, folder: Path, last: int = 3) -> None:
    """Where the backups are, and the newest ones (date, size, status, folder)."""
    log.line(f"Backups folder: {log.s.bold(str(folder))}")
    found = sorted((d for d in folder.iterdir() if d.is_dir() and precheck.STAMP_RE.match(d.name[:19])
                    and not d.name.endswith("-in-progress")), reverse=True) if folder.is_dir() else []
    if not found:
        log.line("Last backups: none yet.")
        return
    log.line(f"Last backups ({len(found):,} in all):" if len(found) > last else "Last backups:")
    for d in found[:last]:
        try:
            data = json.loads((d / "backup.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        size = human((data.get("totals") or {}).get("bytes", 0)) if data.get("totals") else "?"
        status = data.get("status") or ("interrupted" if d.name.endswith("-interrupted") else "unknown")
        log.line(f"  {log.DOT} {d.name[:10]} {d.name[11:16].replace('-', ':')}   {size:>8}   {status:<12} {d}")


def _system_name() -> str:
    return {"win32": "Windows", "cygwin": "Windows", "linux": "Linux"}.get(sys.platform, sys.platform)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="pahest", description=DESCRIPTION, epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", nargs="?", const="default", metavar="NAME",
                    help="run without questions, using answers saved earlier (default name: default)")
    ap.add_argument("--regenerate", nargs="?", const="", metavar="FOLDER",
                    help="rebuild the web pages and readable copies of a backup that already exists, with this "
                         "version of the tool (default: the newest backup); reads no app")
    ap.add_argument("--templates", action="store_true",
                    help="show the folder with the templates of the web pages and reports (HTML, CSS, script), "
                         "so you can edit them; --regenerate then applies them to a backup")
    ap.add_argument("--version", action="version", version=f"pahest {__version__}")
    args = ap.parse_args(argv)
    if args.regenerate is not None and args.profile is not None:
        ap.error("--regenerate and --profile cannot be used together")
    if args.templates:
        print(f"Templates of the web pages and reports: {template.FOLDER}")
        print("Edit them, then run  pahest --regenerate  to rebuild the pages of the newest backup.")
        return EXIT_OK
    if sys.platform != "darwin":
        print(f"Pahest works only on macOS for now; this computer runs {_system_name()}. Nothing was read or "
              "written. Windows and Linux are not supported yet.")
        return EXIT_CANCELLED

    os.umask(0o077)
    conflict = precheck.app_data_conflict(paths.settings_home())
    if conflict:
        print(f"pahest cannot use its settings folder {paths.settings_home()}: {conflict}.")
        return EXIT_CANCELLED
    guard.arm([paths.settings_home()])     # from here on, writing is possible only in our own folders
    try:
        if args.regenerate is not None:
            return _regenerate(args.regenerate)
        return _main(args)
    finally:
        guard.disarm()


def _regenerate(target: str) -> int:
    log = Log()
    home = paths.settings_home()
    lock = _lock(home)
    if not lock:
        log.line(f"A pahest run is still working (lock file {home / LOCK_NAME}). Try again later.")
        return EXIT_CANCELLED
    try:
        return regenerate.run(target or None, log)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _main(args: argparse.Namespace) -> int:
    log = Log()

    interactive = args.profile is None
    mode = "interactive" if interactive else "profile"
    if interactive and not sys.stdin.isatty():
        log.line("pahest asks questions before it starts, but there is no terminal to ask them in. "
                 "Run it in a terminal, or use --profile to run with saved answers.")
        return EXIT_CANCELLED

    started = datetime.now().replace(microsecond=0)
    stamp = started.strftime("%Y-%m-%d-%H-%M-%S")
    home = paths.settings_home()
    logs_dir = home / "logs"
    lock = _lock(home)
    if not lock:
        log.line(f"Another pahest run is still working (lock file {home / LOCK_NAME}). Try again later.")
        return EXIT_CANCELLED
    try:
        log.line(log.s.bold(f"Pahest {__version__}") + log.s.dim(f"  ·  {SLOGAN}  ·  {HOME_URL}"))
        try:
            answers = profile.load(args.profile) if not interactive else profile.Answers()
        except profile.ProfileError as e:
            log.fail(str(e))
            return EXIT_CANCELLED
        _print_backups(log, Path(os.path.expanduser(answers.backups_folder)))
        if not interactive:
            log.line(f"Profile: {args.profile} ({profile.path_for(args.profile)})")
        try:
            pre = precheck.run(log, answers)
            if interactive:
                answers = precheck.ask(log, pre, answers)
                if answers is None:
                    return _cancelled_record(log, logs_dir, stamp, started, mode, "Cancelled.")
                if answers == precheck.REBUILD:
                    log.line()
                    return regenerate.run(str(precheck.newest_backup(pre.folder)), log, banner=False)
            elif pre.dest_error:
                return _cancelled_record(log, logs_dir, stamp, started, mode,
                                         f"Stopped: the backup folder cannot be used: {pre.dest_error}.")
            elif pre.free < pre.needed + (1 << 30):
                return _cancelled_record(log, logs_dir, stamp, started, mode,
                                         f"Stopped: not enough free space in {pre.folder} "
                                         f"({human(pre.free)} free, about {human(pre.needed)} needed).")
            elif pre.scans["codex"].compressed and not pre.zstd.available and answers.without_zstd == "stop":
                return _cancelled_record(log, logs_dir, stamp, started, mode,
                                         "Stopped: zstd is missing and the profile says to stop (brew install zstd).")
        except KeyboardInterrupt:
            return _cancelled_record(log, logs_dir, stamp, started, mode, "Cancelled.")
        log.line()
        log.line(f"  {log.DOT} The backup starts now. Press Ctrl+C to stop it at any time; what is saved by then is kept.")
        return run_backup(log, pre, answers, stamp, started, mode, args.profile)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
