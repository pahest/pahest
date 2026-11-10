"""pahest --regenerate: rebuild the pages of a backup that already exists.

The web pages and Markdown copies (index.html, README.md, readable/) are made from the files
already in the backup, so a newer version of the tool can redo them without a new backup:
no app is read, and nothing is written outside that backup folder, except the copy of its
report in ~/pahest-backups/logs.

Safe if it stops halfway: the old pages are first moved aside (into ASIDE). They are removed
only after the new pages are complete, checked and listed in checksums.sha256. If a run
stopped before that, the next run puts the old pages back first.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__, guard, origins, paths, precheck, readable, report
from .log import Log, fmt_dur, plural
from .result import Ctx, Result
from .store import (CHECKSUMS, DELETED_LIST, Entry, Store, Zstd, read_checksums, read_deleted_list, sha256_file,
                    write_checksums)

ASIDE = ".regenerate-old"          # the old pages, until the new ones are complete
DONE = ".done"                     # inside ASIDE: the new pages are complete; the new checksum list is next to it
TOP_PAGES = ("index.html", "README.md")
EXIT_OK, EXIT_PROBLEMS, EXIT_CANCELLED, EXIT_INTERRUPTED = 0, 1, 2, 130


TOOL_NAMES = ("pahest", "revdoku-backup")     # backups made before the tool was renamed are rebuilt too


def _version(versions) -> str:
    v = versions if isinstance(versions, dict) else {}
    return str(v.get("pahest") or v.get("revdoku_backup") or "?")


def is_page(rel: str) -> bool:
    """Files the readable step makes (and so this command replaces)."""
    return rel in TOP_PAGES or rel == readable.ROOT or rel.startswith(readable.ROOT + "/")


def newest_backup(folder: Path) -> Optional[Path]:
    if not folder.is_dir():
        return None
    found = sorted((d for d in folder.iterdir() if d.is_dir() and precheck.STAMP_RE.match(d.name)), reverse=True)
    return found[0] if found else None


def check_folder(folder: Path) -> str:
    """Why this folder cannot be regenerated, or ""."""
    if not folder.is_dir():
        return "there is no such folder"
    if folder.name.endswith("-in-progress"):
        return "a backup is still being made in it (or was stopped; the next backup marks it as interrupted)"
    try:
        data = json.loads((folder / "backup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "it is not a pahest backup (it has no readable backup.json)"
    if not isinstance(data, dict) or data.get("tool") not in TOOL_NAMES:
        return "it is not a pahest backup (backup.json was made by something else)"
    if not (folder / CHECKSUMS).is_file():
        return f"it has no {CHECKSUMS}, so it cannot be checked afterwards"
    return precheck.app_data_conflict(folder)


def _move(src: Path, dst: Path) -> None:
    if src.exists() or src.is_symlink():
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists() or p.is_symlink():
        p.unlink()


def _put_back(folder: Path) -> None:
    """Undo an unfinished regeneration: remove the new pages, put the old ones back."""
    aside = folder / ASIDE
    for name in (readable.ROOT,) + TOP_PAGES:
        if (aside / name).exists():
            _remove(folder / name)
            _move(aside / name, folder / name)
    _remove(aside)


def _recover(folder: Path, log: Log) -> None:
    """Finish or undo what an earlier run left in ASIDE."""
    aside = folder / ASIDE
    if not aside.exists():
        return
    if (aside / DONE).exists():           # the new pages were complete; only the clean-up was missing
        if (aside / CHECKSUMS).exists():
            os.replace(aside / CHECKSUMS, folder / CHECKSUMS)
        _remove(aside)
    else:
        log.warn("An earlier --regenerate of this backup did not finish. Its old pages are put back first.")
        _put_back(folder)


def _build_and_check(ctx: Ctx, stamp: str, store: Store, log: Log) -> Tuple[Result, List[str], List[str]]:
    """Make the pages, then read every one back and compare it with what was written."""
    res = readable.run(ctx, stamp)
    log.section("Verification")
    pages = sorted(r for r in store.manifest if is_page(r))
    problems: List[str] = []
    for rel in pages:
        try:
            sha, _size = sha256_file(store.path(rel))
        except OSError as e:
            problems.append(f"{rel}: cannot be read again: {e}")
            continue
        if sha != store.manifest[rel].sha:
            problems.append(f"{rel}: differs from what was written")
        elif rel.endswith(".json"):
            try:
                json.loads(store.path(rel).read_bytes().decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                problems.append(f"{rel}: not valid JSON: {str(e)[:120]}")
    problems += [f"readable copies: {p}" for p in res.failed]
    return res, pages, problems


def run(target: Optional[str], log: Log) -> int:
    """Rebuild the pages of the backup in `target` (default: the newest in ~/pahest-backups)."""
    started = time.time()
    log.line(log.s.bold(f"Pahest {__version__}") + log.s.dim("  ·  rebuild the pages of a backup"))
    if target:
        folder = Path(os.path.expanduser(target)).resolve()
        if folder.is_file():              # e.g. its index.html
            folder = folder.parent
    else:
        folder = newest_backup(paths.settings_home())
        if folder is None:
            log.fail(f"No backup found in {paths.settings_home()}. Give the backup folder: "
                     "pahest --regenerate FOLDER")
            return EXIT_CANCELLED
    why = check_folder(folder)
    if why:
        log.fail(f"Cannot rebuild the pages of {folder}: {why}.")
        return EXIT_CANCELLED
    data = json.loads((folder / "backup.json").read_text(encoding="utf-8"))
    log.line(f"Backup: {folder}")
    log.line(log.s.dim(f"  made {str(data.get('started') or '?').replace('T', ' ')} with {data.get('tool')} "
                       f"{_version(data.get('versions'))}; status: {data.get('status', '?')}"))
    guard.allow(folder)                   # from here on, writing is possible only in this backup (and logs)
    log.attach(folder / "backup.log")     # the backup's own log keeps a record of this
    log.section("Rebuild the pages")
    _recover(folder, log)

    hashes = read_checksums(folder / CHECKSUMS)
    store = Store(folder)
    missing: List[str] = []
    for rel, sha in hashes.items():
        if is_page(rel):
            continue
        try:
            size = store.path(rel).lstat().st_size
        except OSError:
            missing.append(rel)
            size = 0
        store.manifest[rel] = Entry(size, sha, "kept")    # stays listed, so a missing file is still noticed
    store.deleted = read_deleted_list(folder / DELETED_LIST)
    store.origins = origins.load(folder / origins.MANIFEST)
    if missing:
        log.warn(f"{plural(len(missing), 'files')} listed in {CHECKSUMS} are missing from the backup; "
                 "pages are made from what is there")

    aside = folder / ASIDE
    aside.mkdir(mode=0o700)
    for name in (readable.ROOT,) + TOP_PAGES:
        _move(folder / name, aside / name)
    stamp = str(data.get("name") or folder.name)
    ctx = Ctx(store, log, {}, str(data.get("started") or stamp)[:10], Zstd())
    try:
        res, pages, problems = _build_and_check(ctx, stamp, store, log)
        write_checksums(store, aside / CHECKSUMS)     # the new list goes into place together with "done"
        (aside / DONE).write_text("new pages complete\n", encoding="utf-8")
    except BaseException as e:  # noqa: BLE001 - put the old pages back, whatever happened
        stop = "Interrupted" if isinstance(e, KeyboardInterrupt) else f"Stopped ({type(e).__name__}: {e})"
        log.fail(f"{stop}. The old pages are put back; the backup is as it was.")
        _put_back(folder)
        log.detach_all()
        return EXIT_INTERRUPTED if isinstance(e, KeyboardInterrupt) else EXIT_PROBLEMS
    _recover(folder, log)                 # "done": the new checksum list goes into place, the old pages go
    if problems:
        log.fail(f"{plural(len(problems), 'problems')} found:")
        for p in problems[:10]:
            log.line(f"    {log.FAIL} {p}")
    else:
        log.ok(f"{plural(len(pages), 'files')} written and read back; {CHECKSUMS} updated")

    # the report: the readable part and the totals as they are now, and a note of this rebuild
    rels = store.rels_under(res.folder)
    res.files, res.bytes = len(rels), sum(store.manifest[r].size for r in rels)
    res.finish_status()
    data["results"] = [r for r in data.get("results") or [] if r.get("id") != readable.ID] + [report.result_dict(res)]
    totals = data.setdefault("totals", {})
    totals["files"] = len(store.manifest)
    totals["bytes"] = sum(e.size for e in store.manifest.values())
    data["backup_folder"] = str(folder)
    data.setdefault("regenerated", []).append({
        "at": datetime.now().isoformat(timespec="seconds"), "version": __version__, "pages": len(pages),
        "seconds": round(time.time() - started, 1), "problems": problems, "missing": len(missing)})
    try:
        report.write_report(folder, paths.settings_home() / "logs", data)
    except OSError as e:
        log.fail(f"Could not write the report: {e}")
        problems.append(f"report.html: {e}")

    log.section("Done")
    mark = log.WARN if problems else log.OK
    log.line(f"{mark} Pages rebuilt in {fmt_dur(time.time() - started)}.")
    log.line(f"  Open:    {log.s.bold(str(folder / 'index.html'))}")
    log.line(f"  Report:  {folder / 'report.html'}")
    log.detach_all()
    return EXIT_PROBLEMS if problems or guard.violations else EXIT_OK
