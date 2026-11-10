"""Copying local folders and files into the backup (used by every source)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple

from .. import origins, paths
from ..log import short_path
from ..result import Ctx, Result
from ..store import DiskFull, Previous, iter_files


@dataclass
class Item:
    src: Path                   # file or folder at the source
    dest: str                   # path inside the backup ("codex/sessions")
    exclude: Callable[[Path], bool] = lambda rel: False


def not_data_roots() -> List[Path]:
    """Places a link may point to that hold caches or installed software, not your data."""
    home = paths.home()
    return [home / ".cache", home / "Library" / "Caches", Path("/Applications"), Path("/System"),
            Path("/Library"), Path("/usr"), Path("/opt"), Path("/private/var"), Path("/var")]


def plan_files(items: List[Item], avoid: Optional[List[Path]] = None, skipped: Optional[List[str]] = None,
               unreadable: Optional[List[Tuple[Path, str]]] = None, records: Optional[dict] = None,
               seen: Optional[dict] = None):
    """[(src path, rel path in backup, size)] for every existing file.

    `records` (optional) receives the original path and attributes of every folder and
    symbolic link, and `seen` the path as the app sees it for every file (it differs from
    the real path when a link led there).

    Symlinked files and folders are followed (dotfile managers often link ~/.claude
    files), but never into the backups themselves."""
    backups = list(avoid or []) + [paths.settings_home()]
    not_data = not_data_roots()
    secret_roots = [os.path.realpath(x) for x in paths.credential_paths()]

    def is_secret(path: Path) -> bool:
        real = os.path.realpath(path)
        return any(real == r or real.startswith(r + os.sep) for r in secret_roots)

    plan = []
    for it in items:
        if not it.src.exists():
            if it.src.is_symlink() and skipped is not None:
                skipped.append(f"{it.src} (broken link)")
            continue
        is_dir = it.src.is_dir()
        bad: List[Path] = []
        dirs: List[tuple] = []
        links: List[tuple] = []
        want = records is not None
        for p, rel, st in iter_files(it.src, it.exclude, follow=True, avoid=not_data, skipped=skipped,
                                     avoid_quietly=backups, unreadable=bad, dirs=dirs if want else None,
                                     found_links=links if want else None):
            if is_secret(p):          # a link led to a login file: never copy it
                if skipped is not None:
                    skipped.append(f"{p} (login file, never copied)")
                continue
            dest = f"{it.dest}/{rel.as_posix()}" if is_dir else it.dest
            plan.append((p, dest, st.st_size))
            if seen is not None:
                seen[dest] = it.src / rel if is_dir else it.src
        if want:
            if it.src.is_symlink():
                rec = origins.link_record(str(it.src))
                if rec:
                    records[it.dest + "#link"] = rec      # the item itself is a link (e.g. a linked skills folder)
            for d, rel, st in dirs:
                r = rel.as_posix()
                records[it.dest if r in ("", ".") else f"{it.dest}/{r}"] = origins.dir_record(str(d), st)
            for lp, rel in links:
                rec = origins.link_record(str(lp))
                if rec:
                    records[f"{it.dest}/{rel.as_posix()}#link"] = rec
        if unreadable is not None:
            for rel in bad:
                r = rel.as_posix()
                unreadable.append((it.src / rel, it.dest if r in ("", ".") else f"{it.dest}/{r}"))
    return plan


def copy_items(ctx: Ctx, res: Result, items: List[Item], prev: Optional[Previous],
               after_file: Optional[Callable[[str], None]] = None) -> List[str]:
    """Copy every file; returns the backup paths written. Never stops on one bad file."""
    skipped: List[str] = []
    unreadable: List[Tuple[Path, str]] = []
    seen: dict = {}
    plan = plan_files(items, [ctx.store.root.parent], skipped, unreadable, records=ctx.store.origins, seen=seen)
    for folder, dest in unreadable:
        res.problem(f"could not read the folder {short_path(folder)} (no permission?); its files from earlier "
                    "backups are kept")
        res.uncertain.append(dest)
    for it in items:
        if it.src.exists():
            res.sources.append(short_path(it.src))
    if skipped:
        res.info.append(f"{len(skipped):,} symbolic links were not followed: "
                        + "; ".join(short_path(x) for x in skipped[:5]) + (" …" if len(skipped) > 5 else ""))
    total = sum(s for _p, _r, s in plan)
    prog = ctx.log.progress(res.name)
    prog.set_totals(len(plan), total)
    done_bytes = 0
    written: List[str] = []
    for n, (src, rel, size) in enumerate(plan):
        prog.update(n, done_bytes, short_path(src))
        try:
            ctx.store.add_file(src, rel, prev, seen=seen.get(rel))
            written.append(rel)
            res.expected.append(rel)
            if after_file:
                after_file(rel)
        except FileNotFoundError:
            res.unavailable.append(f"{short_path(src)} disappeared during the backup")
        except DiskFull:
            raise
        except OSError as e:
            res.problem(f"could not copy {short_path(src)}: {e.strerror or e}")
            res.uncertain.append(rel)
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the backup
            res.problem(f"could not copy {short_path(src)}: {type(e).__name__}: {e}")
            res.uncertain.append(rel)
        done_bytes += size
    prog.finish(len(plan), done_bytes)
    return written


def keep_uncertain(ctx: Ctx, res: Result, prev: Optional[Previous]) -> int:
    """Files that could not be read or downloaded this run: keep the earlier copy, NOT marked deleted."""
    if not prev or not res.uncertain:
        return 0
    errors: List[str] = []
    kept = ctx.store.carry_missing(prev, sorted(set(res.uncertain)), ctx.today, deleted=False, errors=errors)
    res.expected.extend(kept)
    _report_errors(res, prev, errors)
    if kept:
        res.info.append(f"{len(kept):,} files that could not be read this time were kept from {prev.name}.")
    return len(kept)


def _report_errors(res: Result, prev: Previous, errors: List[str], limit: int = 20) -> None:
    for e in errors[:limit]:
        res.problem(f"could not carry a file forward from {prev.name}: {e}")
    if len(errors) > limit:
        res.problem(f"… and {len(errors) - limit:,} more files could not be carried forward")


def carry_forward(ctx: Ctx, res: Result, prev: Optional[Previous], prefixes: List[str],
                  skip: Callable[[str], bool] = lambda rel: False,
                  is_item: Callable[[str], bool] = lambda rel: False, deleted: bool = True) -> List[str]:
    """Carry files the source no longer has. Uncertain ones go first, without the deleted mark."""
    if not prev:
        return []
    keep_uncertain(ctx, res, prev)
    errors: List[str] = []
    carried = ctx.store.carry_missing(prev, prefixes, ctx.today, skip, deleted=deleted, errors=errors)
    _report_errors(res, prev, errors)
    res.expected.extend(carried)
    if not deleted:
        if carried:
            res.info.append(f"{len(carried):,} files could not be checked at the source this time; "
                            f"kept from {prev.name}.")
        return carried
    res.carried += len(carried)
    res.carried_items += sum(1 for r in carried if is_item(r))
    if carried:
        res.info.append(f"{len(carried):,} files no longer exist at the source; kept from earlier backups "
                        f"(listed in deleted-at-source.txt).")
    return carried


def keep_previous_copy(ctx: Ctx, res: Result, prev: Optional[Previous], why: str) -> None:
    """The part could not be backed up this run: bring its whole previous copy over."""
    if not prev:
        if res.status == "failed":
            res.notes.append(f"{why} No earlier backup of this part exists to fall back on.")
        else:
            res.info.append(why)
        return
    prefix = res.folder.rstrip("/") + "/"
    rels = [r for r in prev.hashes if r.startswith(prefix)]
    count = 0
    for rel in sorted(rels):
        if rel in ctx.store.manifest:
            continue
        try:
            src = prev.root / rel
            if src.is_file():
                ctx.store.carry(prev, rel, ctx.today, deleted=False)  # not deleted; just not refreshed
                res.expected.append(rel)
                count += 1
        except OSError as e:
            res.problem(f"could not keep previous copy of {rel}: {e}")
    if count:
        res.kept_previous = True
        res.notes.append(f"{why} Kept the copy from the backup of {prev.name} ({count:,} files) "
                         f"so this backup is still complete.")
    else:
        res.notes.append(f"{why} The earlier backup ({prev.name}) has no files for this part.")


def basenames(rels: List[str]) -> Set[str]:
    return {r.rsplit("/", 1)[-1] for r in rels}
