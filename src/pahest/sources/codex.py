"""Codex (CLI, IDE extension and the ChatGPT/Codex desktop app): ~/.codex.

Codex compresses its session files with zstd (.jsonl.zst). The backup keeps each
compressed file as it is (Codex can read it back) and writes a plain .jsonl next to it,
so the backup reads like normal files even without Codex or zstd.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import List, Optional

from .. import paths
from ..log import short_path
from ..result import Ctx, Result
from ..store import DiskFull
from .local import Item, basenames, carry_forward, copy_items, keep_previous_copy

ID = "codex"
ROOT = "codex"
DATA_DIRS = {"sessions": "sessions", "archived_sessions": "archived_sessions", "attachments": "attachments",
             "generated_images": "generated_images", "visualizations": "visualizations",
             ".chatgpt-projects": "chatgpt-projects", "memories": "memories"}
CONFIG_FILES = ["config.toml", "AGENTS.md"]
CONFIG_DIRS = ["rules", "skills", "prompts", "automations"]
DB_PREFIXES = ["state", "goals", "memories"]          # newest <prefix>_<N>.sqlite of each
APP_DBS = ["codex-dev.db", "codex-thread-summaries-dev.db"]   # desktop app, in ~/.codex/sqlite/
SESSION_RE = re.compile(r"/rollout-[^/]+\.jsonl(\.zst)?$")


def is_session(rel: str) -> bool:
    return bool(SESSION_RE.search(rel)) and rel.startswith(f"{ROOT}/")


def session_key(rel: str) -> str:
    return rel[:-4] if rel.endswith(".zst") else rel


def newest_db(prefix: str) -> Optional[Path]:
    best = None
    for p in paths.codex_dir().glob(f"{prefix}_*.sqlite"):
        m = re.match(rf"{prefix}_(\d+)\.sqlite$", p.name)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    return best[1] if best else None


def db_files() -> List[Path]:
    """The databases worth keeping: the newest state/goals/memories and the desktop app's."""
    c = paths.codex_dir()
    out = [db for db in (newest_db(prefix) for prefix in DB_PREFIXES) if db]
    out += [c / "sqlite" / name for name in APP_DBS if (c / "sqlite" / name).exists()]
    return out


def _db_signature(db: Path):
    sig = []
    for f in (db, db.with_name(db.name + "-wal")):
        try:
            st = f.stat()
            sig.append((f.name, st.st_size, st.st_mtime_ns))
        except OSError:
            sig.append((f.name, None, None))
    return tuple(sig)


def copy_databases(ctx: Ctx, res: Result, prev) -> None:
    """Copy each database together with its -wal file, as plain files.

    The two are copied back to back; if either changed meanwhile (Codex wrote to it),
    the pair is copied again, up to three times. The -shm file is not needed: SQLite
    rebuilds it from the -wal file."""
    for db in db_files():
        wal = db.with_name(db.name + "-wal")
        rels = []
        for _attempt in range(3):
            for rel in rels:   # a retry starts clean: an old -wal next to a newer db would corrupt it
                ctx.store.manifest.pop(rel, None)
                try:
                    ctx.store.path(rel).unlink()
                except OSError:
                    pass
            before = _db_signature(db)
            rels = []
            try:
                for f in (db, wal):
                    if f.exists():
                        rel = f"{ROOT}/databases/{f.name}"
                        ctx.store.add_file(f, rel, prev)
                        rels.append(rel)
            except DiskFull:
                raise
            except OSError as e:
                res.problem(f"could not copy {short_path(db)}: {e.strerror or e}")
                for rel in rels:
                    ctx.store.manifest.pop(rel, None)
                    try:
                        ctx.store.path(rel).unlink()
                    except OSError:
                        pass
                rels = []
                res.uncertain += [f"{ROOT}/databases/{db.name}", f"{ROOT}/databases/{db.name}-wal"]
                break
            if _db_signature(db) == before:
                break
            time.sleep(0.5)
        else:
            res.notes.append(f"{db.name} kept changing while it was copied (Codex was busy). The copy may miss "
                             "the very latest change; the session files are complete.")
        res.expected.extend(rels)
        if rels:
            res.sources.append(short_path(db))


def items() -> List[Item]:
    c = paths.codex_dir()
    out = [Item(c / src, f"{ROOT}/{dst}") for src, dst in DATA_DIRS.items()]
    out += [Item(c / "history.jsonl", f"{ROOT}/history.jsonl"),
            Item(c / "session_index.jsonl", f"{ROOT}/session_index.jsonl")]
    out += [Item(c / f, f"{ROOT}/config/{f}") for f in CONFIG_FILES]
    out += [Item(c / d, f"{ROOT}/config/{d}") for d in CONFIG_DIRS]
    return out


def all_items() -> List[Item]:
    """Everything, databases included (used by the prechecks to count files and sizes)."""
    return items() + [Item(db, f"{ROOT}/databases/{db.name}") for db in db_files()]


def found() -> bool:
    c = paths.codex_dir()
    return (c / "sessions").is_dir() or (c / "history.jsonl").exists()


def run(ctx: Ctx) -> List[Result]:
    t0 = time.time()
    res = Result(ID, "codex", "Codex", "local sessions", ROOT, item_label="sessions")
    prev = ctx.prev(ID)
    if not found():
        res.status = "not found"
        keep_previous_copy(ctx, res, prev, "Codex data was not found on this Mac.")
        res.seconds = time.time() - t0
        return [res]

    written = copy_items(ctx, res, items(), prev)
    copy_databases(ctx, res, prev)
    # A compressed session that could not be read keeps its earlier plain copy as well.
    res.uncertain += [u[:-4] for u in res.uncertain if u.endswith(".jsonl.zst")]

    # Plain copies of compressed sessions, made from the copy now in the backup.
    zst = [r for r in written if r.endswith(".jsonl.zst")]
    present = set(written)
    if zst and not ctx.zstd.available:
        kept = 0
        for rel in zst:  # an unchanged session's plain copy from the previous backup is still exact
            plain = rel[:-4]
            if prev and plain not in present and plain in prev.hashes and \
                    prev.hashes.get(rel) == ctx.store.manifest[rel].sha:
                try:
                    ctx.store.carry(prev, plain, ctx.today, deleted=False)
                    res.expected.append(plain)
                    kept += 1
                except OSError:
                    pass
        res.notes.append(f"{len(zst):,} Codex sessions are zstd-compressed and no decompressor was found. "
                         f"{kept:,} unchanged sessions have their plain copy from the previous backup; the others are "
                         "saved compressed only. Install zstd (brew install zstd) and run again.")
    elif zst:
        prog = ctx.log.progress("Codex plain copies")
        prog.set_totals(len(zst), 0)
        made = 0
        for n, rel in enumerate(zst):
            plain = rel[:-4]
            prog.update(n, 0, plain.rsplit("/", 1)[-1])
            if plain in present:
                continue  # the source already had a plain copy
            path = ctx.store.path(rel)
            try:
                ctx.store.add_stream(plain, lambda p=path: ctx.zstd.open(p), prev,
                                     mtime=path.stat().st_mtime)
                ctx.store.origins[plain] = {"kind": "derived", "from": rel,
                                            "how": "decompressed with zstd; not a file of the app"}
                res.expected.append(plain)
                made += 1
            except DiskFull:
                raise
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the backup
                res.problem(f"could not decompress {rel}: {e}")
        prog.finish(len(zst))
        res.counts["plain copies of compressed sessions"] = made

    # Sessions Codex deleted. A session moved to archived_sessions is not "deleted".
    names = basenames(list(ctx.store.manifest))

    def not_deleted(rel: str) -> bool:
        if is_session(rel) and rel.rsplit("/", 1)[-1] in names:
            return True                             # moved, e.g. to archived_sessions
        z = ctx.store.manifest.get(rel + ".zst")
        return rel.endswith(".jsonl") and z is not None and z.how != "carried"  # plain copy of a session read now

    carry_forward(ctx, res, prev, [f"{ROOT}/{d}" for d in DATA_DIRS.values()],
                  skip=not_deleted,
                  is_item=lambda rel: is_session(rel) and not rel.endswith(".zst"))

    res.items = len({session_key(r) for r in ctx.store.rels_under(ROOT) if is_session(r)})
    res.info.append("sessions/YYYY/MM/DD/rollout-*.jsonl are the full transcripts, one JSON event per line; "
                    "the .jsonl.zst next to each is Codex's original compressed file.")
    res.info.append("databases/ holds Codex's thread list (titles, projects, archived flags), goals and memories. "
                    "thread_history_*.sqlite and logs_*.sqlite are skipped: the first is rebuilt by Codex from the "
                    "session files, the second only has logs.")
    res.info.append("Credentials (~/.codex/auth.json) are deliberately not copied. config/config.toml may contain "
                    "API keys of MCP servers.")
    res.seconds = time.time() - t0
    return [res]
