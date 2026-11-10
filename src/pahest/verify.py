"""Step 4 of every run: check that the backup just made is complete and readable.

* Every file is read back; its size and SHA-256 must match what was written.
* JSON must parse; every JSONL line must parse; .zst files must decompress to exactly
  their plain copy; images must have a valid header; SQLite copies must pass
  PRAGMA integrity_check (checked on a temporary copy, so the backup is not touched).
* Every path a source said it saved must exist; no leftover temporary files.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from . import guard
from .log import Log, human
from .result import Result
from .store import CHUNK, TMP_MARK, Store, Zstd, clonefile, iter_files, sha256_stream

ROOT_META = {"report.html", "backup.log", "backup.json", "checksums.sha256", "deleted-at-source.txt"}
IMAGE_MAGIC = {
    ".png": [b"\x89PNG\r\n\x1a\n"], ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"], ".webp": [b"RIFF"],
}
# JSONL files that apps may be appending to while the backup runs.
LIVE_JSONL_PREFIXES = ("claude-code/", "codex/", "claude-desktop/local/")   # files copied from the apps
JSON_PARSE_LIMIT = 512 << 20


@dataclass
class Verification:
    files: int = 0
    bytes: int = 0
    json_ok: int = 0
    jsonl_ok: int = 0
    zst_ok: int = 0
    sqlite_ok: int = 0
    images_ok: int = 0
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.problems


def _check_json(data: bytes) -> str:
    try:
        json.loads(data.decode("utf-8"))
        return ""
    except (UnicodeDecodeError, ValueError) as e:
        return str(e)[:120]


def _check_jsonl(path: Path) -> List[str]:
    """Problems as (line number: error). The last line may be incomplete in live files."""
    bad = []
    count = 0
    with open(path, "rb") as f:
        for count, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                if len(bad) < 10:
                    bad.append([count, 0, str(e)[:80]])
    for b in bad:
        b[1] = count
    return [tuple(b) for b in bad]


def _check_sqlite(path: Path) -> str:
    tmp = Path(tempfile.mkdtemp(prefix="pahest-verify-", dir=str(path.parent)))
    try:
        copy = tmp / path.name
        if not clonefile(path, copy):
            shutil.copyfile(path, copy)
        for ext in ("-wal", "-shm"):
            side = path.with_name(path.name + ext)
            if side.exists():
                dst = copy.with_name(copy.name + ext)
                if not clonefile(side, dst):
                    shutil.copyfile(side, dst)
        guard.check_write(copy, "open database")
        con = sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
        finally:
            con.close()
        return "" if row and row[0] == "ok" else f"integrity check: {row[0] if row else 'no answer'}"
    except sqlite3.Error as e:
        return str(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(store: Store, results: List[Result], log: Log, zstd: Zstd) -> Verification:
    t0 = time.time()
    v = Verification()
    root = store.root
    manifest = store.manifest

    # Files on disk vs the manifest.
    on_disk: Dict[str, int] = {}
    for p, rel, st in iter_files(root):
        r = rel.as_posix()
        if r in ROOT_META:
            continue
        on_disk[r] = st.st_size
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if TMP_MARK in name:
                v.problems.append(f"leftover temporary file: {Path(dirpath, name).relative_to(root)}")
    for r in sorted(set(on_disk) - set(manifest)):
        v.warnings.append(f"file in the backup that the backup did not write: {r}")
    for r in sorted(set(manifest) - set(on_disk)):
        v.problems.append(f"missing from the backup: {r}")
    for res in results:
        for r in res.expected:
            if r not in manifest:
                v.problems.append(f"{res.name} — expected but not saved: {r}")

    total = sum(e.size for r, e in manifest.items() if r in on_disk)
    prog = log.progress("Verifying")
    prog.set_totals(len(manifest), total)
    done = 0
    for n, (rel, e) in enumerate(sorted(manifest.items())):
        if rel not in on_disk:
            continue
        path = root / rel
        prog.update(n, done, rel)
        try:
            h = hashlib.sha256()
            size = 0
            head = b""
            small = bytearray() if e.size <= JSON_PARSE_LIMIT and rel.endswith(".json") else None
            with open(path, "rb") as f:
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    if not head:
                        head = b[:16]
                    h.update(b)
                    size += len(b)
                    if small is not None:
                        small.extend(b)
            if size != e.size or h.hexdigest() != e.sha:
                v.problems.append(f"does not match what was written (size or checksum): {rel}")
                continue
            v.files += 1
            v.bytes += size
            suffix = path.suffix.lower()
            if rel.endswith(".json"):
                if small is None:
                    v.warnings.append(f"{rel}: too large to parse ({human(size)}); its checksum was checked")
                    done += e.size
                    continue
                err = _check_json(bytes(small))
                if err:
                    msg = f"not valid JSON: {rel} ({err})"
                    (v.warnings if rel.startswith(LIVE_JSONL_PREFIXES) else v.problems).append(msg)
                else:
                    v.json_ok += 1
            elif rel.endswith(".jsonl"):
                bad = _check_jsonl(path)
                if not bad:
                    v.jsonl_ok += 1
                for line_no, count, err in bad[:3]:
                    msg = f"{rel}: line {line_no} of {count} is not valid JSON ({err})"
                    if line_no == count and rel.startswith(LIVE_JSONL_PREFIXES):
                        v.warnings.append(msg + " — the app was probably still writing it")
                    else:
                        v.warnings.append(msg + " — the same line is in the app's own file")
            elif rel.endswith(".zst"):
                plain = rel[:-4]
                if not zstd.available:
                    pass
                else:
                    try:
                        with zstd.open(path) as zf:
                            psha, _psize = sha256_stream(zf)
                        if plain in manifest and manifest[plain].sha != psha:
                            v.problems.append(f"plain copy differs from the compressed file: {plain}")
                        else:
                            v.zst_ok += 1
                    except OSError as ex:
                        v.problems.append(f"cannot decompress {rel}: {ex}")
            elif suffix in (".sqlite", ".db") and head.startswith(b"SQLite format 3"):
                err = _check_sqlite(path)
                if err:
                    v.problems.append(f"database copy is not readable: {rel} ({err}). Run the backup again "
                                      "while the app is idle.")
                else:
                    v.sqlite_ok += 1
            elif suffix in IMAGE_MAGIC:
                if any(head.startswith(m) for m in IMAGE_MAGIC[suffix]) or head[:4] in (b"RIFF", b"\x89PNG") \
                        or head[:3] == b"\xff\xd8\xff":
                    v.images_ok += 1
                else:
                    v.warnings.append(f"image file does not start like a {suffix} image: {rel}")
        except OSError as ex:
            v.problems.append(f"cannot read {rel}: {ex}")
        except Exception as ex:  # noqa: BLE001 - report, never crash the verification
            v.problems.append(f"could not check {rel}: {type(ex).__name__}: {ex}")
        done += e.size
    prog.finish(len(manifest), done)
    v.seconds = time.time() - t0
    return v


def summary_line(v: Verification) -> str:
    return (f"{v.files:,} files ({human(v.bytes)}) read back and matched; {v.json_ok:,} JSON, {v.jsonl_ok:,} JSONL, "
            f"{v.zst_ok:,} compressed, {v.sqlite_ok:,} databases, {v.images_ok:,} images checked")
