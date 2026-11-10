"""Writing files into a backup folder.

Every file that goes into a backup passes through `Store`, which:
  * writes atomically (temporary file, then rename),
  * records the size and SHA-256 of what it wrote (the manifest, later used for
    verification and checksums.sha256),
  * saves disk space without skipping anything: on APFS a file is stored as a clone
    (a complete, independent copy that shares disk blocks until either one changes),
    either of the source file or of a byte-identical file in the previous backup.

There is no database: the previous backup is just a folder plus its checksums.sha256.
"""
from __future__ import annotations

import bisect
import ctypes
import errno
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Dict, Iterator, List, NamedTuple, Optional, Set, Tuple

from . import guard, origins

SKIP_NAMES = {".DS_Store"}
# Linked folders that hold installed software, not your data (they can be reinstalled).
DEPENDENCY_LINK_NAMES = {"node_modules", ".venv", "venv", "site-packages", "__pycache__"}
CHUNK = 1 << 20
TMP_MARK = ".rb-tmp"
DELETED_LIST = "deleted-at-source.txt"
CHECKSUMS = "checksums.sha256"


# ── reading source trees ────────────────────────────────────────────────────

def iter_files(src: Path, exclude: Callable[[Path], bool] = lambda rel: False, follow: bool = False,
               avoid: Optional[List[Path]] = None, skipped: Optional[List[str]] = None,
               avoid_quietly: Optional[List[Path]] = None, unreadable: Optional[List[Path]] = None,
               dirs: Optional[List[Tuple[Path, Path, os.stat_result]]] = None,
               found_links: Optional[List[Tuple[Path, Path]]] = None
               ) -> Iterator[Tuple[Path, Path, os.stat_result]]:
    """Yield (path, relpath, stat) for regular files under src.

    follow=False: symlinks are ignored (used for reading backups).
    follow=True:  symlinked files and folders are followed. All real folders are walked
                  first; a linked folder is walked afterwards, and only if it is not
                  already in the backup. Never into `avoid_quietly` (the backups
                  themselves), nor into `avoid` (caches, installed software) or linked
                  dependency folders such as node_modules; those and broken links are
                  added to `skipped`. A followed file is yielded with its real path.
    Folders that cannot be read are added to `unreadable` (relative paths), so the
    caller can report them instead of losing them silently. `dirs` collects every folder
    walked (path as seen, relative path, stat) and `found_links` every symbolic link found
    (path, relative path), for the record of original paths and attributes."""
    quiet_real = [os.path.realpath(a) for a in (avoid_quietly or [])]
    avoid_real = [os.path.realpath(a) for a in (avoid or [])] + quiet_real

    def under(real: str, roots: List[str]) -> bool:
        return any(real == a or real.startswith(a + os.sep) for a in roots)

    try:
        if src.is_symlink() and not follow:
            return
        st = src.stat()
    except OSError:
        if skipped is not None and src.is_symlink():
            skipped.append(f"{src} (broken link)")
        return
    if stat.S_ISREG(st.st_mode):
        yield Path(os.path.realpath(src)) if src.is_symlink() else src, Path(src.name), st
        return
    # The starting folder is the app's own data (even when it is a link): only links found
    # inside it are judged. It must never be one of the backups, though.
    if not stat.S_ISDIR(st.st_mode) or under(os.path.realpath(src), quiet_real):
        return

    seen: Set[Tuple[int, int]] = set()
    links: List[Tuple[Path, Path]] = []      # linked folders, walked after every real folder
    root_real = os.path.realpath(src)

    def walk(start: Path, rel_start: Path, via_link: bool):
        stack: List[Tuple[Path, Path]] = [(start, rel_start)]
        while stack:
            d, rel_d = stack.pop()
            # Inside a linked folder every folder is checked: the link may lead to a place
            # that contains the backups themselves.
            if via_link and under(os.path.realpath(d), quiet_real):
                continue
            try:
                dst = os.stat(d)
                key = (dst.st_dev, dst.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                entries = sorted(os.scandir(d), key=lambda e: e.name)
                if dirs is not None:
                    dirs.append((d, rel_d, dst))
            except OSError:
                if unreadable is not None:
                    unreadable.append(rel_d)
                continue
            subdirs = []
            for ent in entries:
                name = ent.name
                if name in SKIP_NAMES or TMP_MARK in name:
                    continue
                rel = rel_d / name
                if exclude(rel):
                    continue
                try:
                    is_link = ent.is_symlink()
                except OSError:
                    continue
                if is_link and found_links is not None:
                    found_links.append((Path(ent.path), rel))
                if is_link and not follow:
                    continue
                try:
                    est = os.stat(ent.path) if is_link else ent.stat(follow_symlinks=False)
                except OSError as e:
                    if is_link and e.errno == errno.ENOENT:
                        if skipped is not None:
                            skipped.append(f"{ent.path} (broken link)")
                    elif e.errno != errno.ENOENT and unreadable is not None:
                        unreadable.append(rel)        # exists, but cannot be checked (permissions)
                    continue
                if stat.S_ISDIR(est.st_mode):
                    if is_link:
                        real = os.path.realpath(ent.path)
                        if under(real, quiet_real):
                            continue                  # the backups themselves: never, nothing to report
                        why = ""
                        if real == root_real or root_real.startswith(real + os.sep):
                            why = "link loop: it points to a folder that contains it"
                        elif name in DEPENDENCY_LINK_NAMES:
                            why = "link to installed software, not your data"
                        elif under(real, avoid_real):
                            why = "link into a cache or system folder"
                        if why:
                            if skipped is not None:
                                skipped.append(f"{ent.path} ({why})")
                        else:
                            links.append((Path(ent.path), rel))
                        continue
                    subdirs.append((Path(ent.path), rel))
                elif stat.S_ISREG(est.st_mode):
                    yield (Path(os.path.realpath(ent.path)) if is_link else Path(ent.path)), rel, est
            stack.extend(reversed(subdirs))

    yield from walk(src, Path(), via_link=src.is_symlink())
    while links:
        lp, lrel = links.pop(0)
        try:
            lst = os.stat(lp)
        except OSError:
            continue
        if (lst.st_dev, lst.st_ino) in seen:
            if skipped is not None:
                skipped.append(f"{lp} (link to a folder that is already in the backup)")
            continue
        yield from walk(lp, lrel, via_link=True)


# ── clonefile (APFS) ────────────────────────────────────────────────────────

_CLONE_NOFOLLOW = 0x0001
_CLONE_NOOWNERCOPY = 0x0002
_clonefile_fn = None


def _clone_fn():
    global _clonefile_fn
    if _clonefile_fn is None:
        fn = False
        if sys.platform == "darwin":
            try:
                libc = ctypes.CDLL(None, use_errno=True)
                f = libc.clonefile
                f.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
                f.restype = ctypes.c_int
                fn = f
            except (OSError, AttributeError):
                fn = False
        _clonefile_fn = fn
    return _clonefile_fn


def clonefile(src: Path, dst: Path) -> bool:
    """Clone src to dst (dst must not exist). False if cloning is not possible here."""
    fn = _clone_fn()
    if not fn:
        return False
    guard.check_write(dst, "clone into")
    r = fn(os.fsencode(str(src)), os.fsencode(str(dst)), _CLONE_NOFOLLOW | _CLONE_NOOWNERCOPY)
    if r == 0:
        return True
    e = ctypes.get_errno()
    if e in (errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL, errno.ENOSYS):
        return False
    raise OSError(e, os.strerror(e), str(src))


def clone_or_copy(src: Path, dst: Path) -> None:
    """A copy of a file: an APFS clone when possible (instant, no extra space), else an ordinary copy."""
    if not clonefile(src, dst):
        shutil.copyfile(src, dst)


def can_clone(src_dir: Path, dst_dir: Path) -> bool:
    """True if files from src_dir can be cloned into dst_dir (same APFS volume)."""
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        probe_src = None
        for p, _rel, _st in iter_files(src_dir):
            probe_src = p
            break
        if probe_src is None:
            return False
        tmp = dst_dir / f"{TMP_MARK}-probe-{os.getpid()}"
        if tmp.exists():
            tmp.unlink()
        ok = clonefile(probe_src, tmp)
        if tmp.exists():
            tmp.unlink()
        return ok
    except OSError:
        return False


# ── hashing ─────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> Tuple[str, int]:
    with open(path, "rb") as f:
        return sha256_stream(f)


def sha256_stream(f: BinaryIO) -> Tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    while True:
        b = f.read(CHUNK)
        if not b:
            break
        h.update(b)
        n += len(b)
    return h.hexdigest(), n


# ── zstd (Codex compresses its sessions) ────────────────────────────────────

class Zstd:
    """Decompress .zst files with Python 3.14+'s compression.zstd, or the zstd program."""

    def __init__(self):
        self.module = None
        self.program = None
        try:
            from compression import zstd as _z  # type: ignore  # Python 3.14+
            self.module = _z
        except ImportError:
            pass
        for cand in (shutil.which("zstd"), "/opt/homebrew/bin/zstd", "/usr/local/bin/zstd"):
            if cand and os.path.exists(cand):
                self.program = cand
                break

    @property
    def available(self) -> bool:
        return bool(self.module or self.program)

    @property
    def label(self) -> str:
        if self.module:
            return "Python compression.zstd"
        if self.program:
            return self.program
        return "not found"

    def open(self, path: Path) -> "ZstdReader":
        return ZstdReader(self, path)


class ZstdReader:
    def __init__(self, z: Zstd, path: Path):
        self.z, self.path = z, path
        self.proc = None
        self.f = None

    def __enter__(self) -> BinaryIO:
        if self.z.module:
            self.f = self.z.module.open(str(self.path), "rb")
            return self.f
        if not self.z.program:
            raise OSError("no zstd decompressor available")
        self.proc = subprocess.Popen([self.z.program, "-dcq", "--no-progress", "--", str(self.path)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self.proc.stdout

    def __exit__(self, exc_type, exc, tb):
        if self.f:
            try:
                self.f.close()
            except Exception:  # noqa: BLE001 - closing a broken stream
                pass
            if exc is not None and not isinstance(exc, (OSError, KeyboardInterrupt, DiskFull)) \
                    and isinstance(exc, Exception):
                raise OSError(f"zstd: {exc}") from exc
        if self.proc:
            self.proc.stdout.close()
            err = self.proc.stderr.read().decode("utf-8", "replace").strip()
            self.proc.stderr.close()
            rc = self.proc.wait()
            if rc != 0 and exc_type is None:
                raise OSError(f"zstd failed ({rc}): {err[:200]}")
        return False


# ── the previous backup ─────────────────────────────────────────────────────

class Previous(NamedTuple):
    root: Path                  # the previous backup folder
    name: str                   # its folder name (start time)
    hashes: Dict[str, str]      # rel path -> sha256, from its checksums.sha256
    deleted: Dict[str, str]     # rel path -> date first missing, from its deleted-at-source.txt
    origins: Dict[str, dict] = {}   # rel path -> original path and attributes (source-manifest.jsonl)


def read_checksums(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if len(line) > 66 and line[64:66] == "  " and safe_rel(line[66:]):
                    out[line[66:]] = line[:64]
    except OSError:
        pass
    return out


def read_deleted_list(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t", 1)
                if len(parts) == 2 and not line.startswith("#") and safe_rel(parts[1]):
                    out[parts[1]] = parts[0]
    except OSError:
        pass
    return out


def load_previous(folder: Path) -> Previous:
    return Previous(folder, folder.name, read_checksums(folder / CHECKSUMS),
                    read_deleted_list(folder / DELETED_LIST), origins.load(folder / origins.MANIFEST))


# ── the store ───────────────────────────────────────────────────────────────

class DiskFull(Exception):
    """The backup disk is full. Not an OSError on purpose: sources must not swallow it."""


def _stop_when_full(fn):
    """Turn "disk full" into DiskFull, and remove this call's temporary files on any error."""
    def wrapper(self, *args, **kwargs):
        first = self._n
        try:
            return fn(self, *args, **kwargs)
        except BaseException as e:
            for n in range(first + 1, self._n + 1):
                for d in self._tmp_dirs:
                    self._discard(d / f"{TMP_MARK}-{os.getpid()}-{n}")
            if isinstance(e, OSError) and e.errno in (errno.ENOSPC, errno.EDQUOT):
                raise DiskFull(str(e)) from e
            raise
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class UnsafePath(OSError):
    pass


def safe_rel(rel: str) -> bool:
    """A relative path made only of ordinary names: no "..", no leading "/", no backslash."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


@dataclass
class Entry:
    size: int
    sha: str
    how: str            # clone-source | clone-previous | copy | write | carried


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.manifest: Dict[str, Entry] = {}
        self.deleted: Dict[str, str] = {}      # rel -> date first missing
        self.origins: Dict[str, dict] = {}     # rel -> original path and attributes
        self.saved_bytes_by_clone = 0
        self._clone_from: Dict[Tuple[int, int], bool] = {}
        self._n = 0
        self._tmp_dirs: List[Path] = []

    # helpers
    def path(self, rel: str) -> Path:
        """The file for `rel` inside this backup. Paths come partly from servers (chat and file
        ids) and from older backups' checksum lists, so anything that could point outside the
        backup is refused."""
        if not safe_rel(rel):
            raise UnsafePath(errno.EINVAL, "refused a path that could lead outside the backup", rel)
        return self.root / rel

    def _tmp(self, dst: Path) -> Path:
        self._n += 1
        tmp = dst.parent / f"{TMP_MARK}-{os.getpid()}-{self._n}"
        if tmp.exists():
            tmp.unlink()
        return tmp

    @staticmethod
    def _discard(*paths: Path) -> None:
        for p in paths:
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
            except OSError:
                pass

    def _prepare(self, rel: str) -> Path:
        dst = self.path(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        self._tmp_dirs = [dst.parent]
        return dst

    def _finish(self, tmp: Path, dst: Path, mtime: Optional[float]) -> None:
        os.chmod(tmp, 0o600)
        if mtime is not None:
            os.utime(tmp, (mtime, mtime))
        os.replace(tmp, dst)

    def _try_clone(self, src: Path, tmp: Path) -> bool:
        try:
            key = (os.stat(src).st_dev, os.stat(tmp.parent).st_dev)
        except OSError:
            return False
        if self._clone_from.get(key) is False:
            return False
        ok = clonefile(src, tmp)
        self._clone_from[key] = ok
        return ok

    def _reuse_previous(self, prev: Optional[Previous], rel: str, sha: str, tmp: Path) -> bool:
        """If the previous backup has a byte-identical file, replace tmp with a clone of it."""
        if not prev or prev.hashes.get(rel) != sha:
            return False
        old = prev.root / rel
        if not old.is_file():
            return False
        alt = self._tmp(tmp)
        try:
            if not self._try_clone(old, alt):
                return False
            osha, _ = sha256_file(alt)
            if osha != sha:
                return False
            os.replace(alt, tmp)
            return True
        finally:
            self._discard(alt)

    # public API
    @_stop_when_full
    def add_file(self, src: Path, rel: str, prev: Optional[Previous] = None, seen: Optional[Path] = None) -> Entry:
        """Copy a local source file (clone when possible) and record its hash, its original
        path (`seen`: the path as the app sees it, when a link led to `src`) and attributes."""
        dst = self._prepare(rel)
        tmp = self._tmp(dst)
        st = src.stat()
        record = origins.file_record(str(seen or src), str(src), st)
        how = "copy"
        if self._try_clone(src, tmp):
            how = "clone-source"
            sha, size = sha256_file(tmp)
        else:
            h = hashlib.sha256()
            size = 0
            with open(src, "rb") as fi, open(tmp, "wb") as fo:
                while True:
                    b = fi.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
                    fo.write(b)
                    size += len(b)
            sha = h.hexdigest()
            if self._reuse_previous(prev, rel, sha, tmp):
                how = "clone-previous"
        if how != "copy":
            self.saved_bytes_by_clone += size
        self._finish(tmp, dst, st.st_mtime)
        e = Entry(size, sha, how)
        self.manifest[rel] = e
        self.origins[rel] = record
        return e

    @_stop_when_full
    def add_bytes(self, rel: str, data: bytes, prev: Optional[Previous] = None,
                  mtime: Optional[float] = None) -> Entry:
        """Write generated or downloaded content."""
        dst = self._prepare(rel)
        tmp = self._tmp(dst)
        sha = hashlib.sha256(data).hexdigest()
        how = "write"
        if self._reuse_previous(prev, rel, sha, tmp):
            how = "clone-previous"
            self.saved_bytes_by_clone += len(data)
        else:
            with open(tmp, "wb") as f:
                f.write(data)
        self._finish(tmp, dst, mtime)
        e = Entry(len(data), sha, how)
        self.manifest[rel] = e
        return e

    @_stop_when_full
    def add_stream(self, rel: str, reader: Callable[[], BinaryIO], prev: Optional[Previous] = None,
                   mtime: Optional[float] = None) -> Entry:
        """Write content produced by a stream (download, decompression).

        `reader()` opens a fresh stream each time it is called; it may be called twice
        when the previous backup has a candidate file to compare against first."""
        dst = self._prepare(rel)
        tmp = self._tmp(dst)
        if prev and rel in prev.hashes:
            with reader() as f:
                sha, size = sha256_stream(f)
            if self._reuse_previous(prev, rel, sha, tmp):
                self.saved_bytes_by_clone += size
                self._finish(tmp, dst, mtime)
                e = Entry(size, sha, "clone-previous")
                self.manifest[rel] = e
                return e
        h = hashlib.sha256()
        size = 0
        with reader() as fi, open(tmp, "wb") as fo:
            while True:
                b = fi.read(CHUNK)
                if not b:
                    break
                h.update(b)
                fo.write(b)
                size += len(b)
        self._finish(tmp, dst, mtime)
        e = Entry(size, h.hexdigest(), "write")
        self.manifest[rel] = e
        return e

    @_stop_when_full
    def carry(self, prev: Previous, rel: str, today: str, deleted: bool = True) -> Optional[Entry]:
        """Bring a file from the previous backup into this one.

        deleted=True: the source no longer has it. deleted=False: the source could not be read
        this time; the file keeps whatever "deleted at source" date it already had."""
        src = prev.root / rel
        if not src.is_file():
            return None
        dst = self._prepare(rel)
        tmp = self._tmp(dst)
        if self._try_clone(src, tmp):
            sha, size = sha256_file(tmp)
            self.saved_bytes_by_clone += size
        else:
            shutil.copyfile(src, tmp)
            sha, size = sha256_file(tmp)
        expected = prev.hashes.get(rel)
        if expected and expected != sha:
            raise OSError(f"previous backup copy of {rel} does not match its checksum")
        self._finish(tmp, dst, src.stat().st_mtime)
        e = Entry(size, sha, "carried")
        self.manifest[rel] = e
        for r in [rel] + origins.parents([rel]):          # where it came from, as recorded back then
            if r in prev.origins and r not in self.origins:
                self.origins[r] = dict(prev.origins[r])
        if deleted:
            self.deleted[rel] = prev.deleted.get(rel, today)
        elif rel in prev.deleted:
            self.deleted[rel] = prev.deleted[rel]
        return e

    def carry_missing(self, prev: Optional[Previous], prefixes: List[str], today: str,
                      skip: Callable[[str], bool] = lambda rel: False, deleted: bool = True,
                      errors: Optional[List[str]] = None) -> List[str]:
        """Carry every file under `prefixes` that the previous backup has and this one lacks.

        A file that cannot be carried is added to `errors` (or raises if errors is None)."""
        if not prev:
            return []
        carried = []
        rels = sorted(prev.hashes.keys() if prev.hashes else _walk_rels(prev.root))
        wanted: Set[str] = set()
        for p in prefixes:
            p = p.rstrip("/")
            i = bisect.bisect_left(rels, p)
            if i < len(rels) and rels[i] == p:
                wanted.add(p)
            lo = bisect.bisect_left(rels, p + "/")
            hi = bisect.bisect_left(rels, p + "0")     # "0" sorts right after "/"
            wanted.update(rels[lo:hi])
        for rel in sorted(wanted):
            if rel in self.manifest or skip(rel):
                continue
            try:
                if self.carry(prev, rel, today, deleted=deleted):
                    carried.append(rel)
            except OSError as e:
                if errors is None:
                    raise
                errors.append(f"{rel}: {e}")
        return carried

    def rels_under(self, prefix: str) -> List[str]:
        p = prefix.rstrip("/") + "/"
        return [r for r in self.manifest if r.startswith(p) or r == prefix]


def _walk_rels(root: Path) -> Set[str]:
    out = set()
    for _p, rel, _st in iter_files(root):
        out.add(rel.as_posix())
    return out


def write_checksums(store: Store, path: Optional[Path] = None) -> Path:
    path = path or store.root / CHECKSUMS
    lines = [f"{e.sha}  {rel}\n" for rel, e in sorted(store.manifest.items())]
    path.write_text("".join(lines), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def write_source_manifest(store: Store) -> Entry:
    """source-manifest.jsonl: the original path and attributes of every file, folder and link
    that came from the apps. Written through the store, so checksums.sha256 covers it."""
    keep = {rel: rec for rel, rec in store.origins.items()
            if rec.get("kind") in ("dir", "link") or rel in store.manifest}
    for rel, d in store.deleted.items():
        if rel in keep:
            keep[rel] = dict(keep[rel], deleted_at_source=d)
    data = origins.dumps(keep, {rel: e.sha for rel, e in store.manifest.items()})
    return store.add_bytes(origins.MANIFEST, data)


def write_deleted_list(store: Store) -> Optional[Path]:
    if not store.deleted:
        return None
    path = store.root / DELETED_LIST
    lines = ["# date first missing at the source <TAB> path in this backup\n"]
    lines += [f"{d}\t{rel}\n" for rel, d in sorted(store.deleted.items())]
    path.write_text("".join(lines), encoding="utf-8")
    os.chmod(path, 0o600)
    return path
