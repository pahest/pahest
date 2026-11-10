"""Where every backed-up file came from, with all its attributes: source-manifest.jsonl.

A backup is more useful if it can be put back exactly. So for every original file,
folder and symbolic link the tool records, in one JSON Lines file at the top of the
backup:

- the original path (as the app saw it) and, if a link led there, the real path;
- the type, permissions, owner and group (as numbers and names);
- size, and the modified, accessed, changed and created times (in nanoseconds);
- the macOS file flags and the extended attributes (for example where a file was
  downloaded from), with their values;
- for a symbolic link, what it points to; for a file, its SHA-256.

Files the tool makes itself (plain copies of compressed Codex sessions, the readable
pages) have no original; plain copies record which file they were made from.

The first line describes the backup (computer, user, home folder), so a future restore
can also put the files into another user's home folder.
"""
from __future__ import annotations

import base64
import ctypes
import grp
import json
import os
import platform
import pwd
import stat
import sys
import time
from typing import Dict, List, Optional

FORMAT = "pahest source manifest"
VERSION = 1
MANIFEST = "source-manifest.jsonl"
XATTR_VALUE_LIMIT = 1 << 16          # longer values are noted by size only

_names: Dict[tuple, str] = {}
_xattr = {"fns": None}


def _user(uid: int) -> str:
    key = ("u", uid)
    if key not in _names:
        try:
            _names[key] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _names[key] = ""
    return _names[key]


def _group(gid: int) -> str:
    key = ("g", gid)
    if key not in _names:
        try:
            _names[key] = grp.getgrgid(gid).gr_name
        except KeyError:
            _names[key] = ""
    return _names[key]


def _xattr_fns():
    if _xattr["fns"] is None:
        fns = False
        if sys.platform == "darwin":
            try:
                libc = ctypes.CDLL(None, use_errno=True)
                lx, gx = libc.listxattr, libc.getxattr
                lx.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
                lx.restype = ctypes.c_ssize_t
                gx.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
                               ctypes.c_uint32, ctypes.c_int]
                gx.restype = ctypes.c_ssize_t
                fns = (lx, gx)
            except (OSError, AttributeError):
                fns = False
        _xattr["fns"] = fns
    return _xattr["fns"]


def xattrs(path: str, follow: bool = True) -> Dict[str, object]:
    """Extended attributes of a file: {name: base64 value} (or {"size": n} for big values).
    Read only; nothing is changed."""
    fns = _xattr_fns()
    if not fns:
        return {}
    lx, gx = fns
    opts = 0 if follow else 0x0001          # XATTR_NOFOLLOW
    p = os.fsencode(path)
    n = lx(p, None, 0, opts)
    if n <= 0:
        return {}
    buf = ctypes.create_string_buffer(n)
    n = lx(p, buf, n, opts)
    if n <= 0:
        return {}
    out: Dict[str, object] = {}
    for raw in buf.raw[:n].split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8", "replace")
        size = gx(p, raw, None, 0, 0, opts)
        if size < 0:
            continue
        if size > XATTR_VALUE_LIMIT:
            out[name] = {"size": size}
            continue
        val = ctypes.create_string_buffer(max(size, 1))
        got = gx(p, raw, val, size, 0, opts)
        if got >= 0:
            out[name] = base64.b64encode(val.raw[:got]).decode("ascii")
    return out


def attributes(st: os.stat_result, path: Optional[str] = None, follow: bool = True) -> dict:
    """Everything about a file or folder that can be put back later."""
    mode = st.st_mode
    kind = "dir" if stat.S_ISDIR(mode) else "link" if stat.S_ISLNK(mode) else "file"
    a = {
        "type": kind,
        "mode": format(stat.S_IMODE(mode), "04o"),
        "uid": st.st_uid, "user": _user(st.st_uid), "gid": st.st_gid, "group": _group(st.st_gid),
        "mtime_ns": st.st_mtime_ns, "atime_ns": st.st_atime_ns, "ctime_ns": st.st_ctime_ns,
        "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
    }
    if kind == "file":
        a["size"] = st.st_size
    bt = getattr(st, "st_birthtime_ns", None)
    if bt is None and getattr(st, "st_birthtime", None) is not None:
        bt = int(st.st_birthtime * 1_000_000_000)
    if bt is not None:
        a["btime_ns"] = bt
    flags = getattr(st, "st_flags", 0)
    if flags:
        a["flags"] = flags
    if path is not None:
        try:
            x = xattrs(path, follow=follow)
        except (OSError, ValueError):
            x = {}
        if x:
            a["xattrs"] = x
    return a


def file_record(seen: str, real: str, st: os.stat_result) -> dict:
    rec = {"kind": "file", "path": seen}
    real_path = os.path.realpath(real)
    if real_path != os.path.abspath(seen):      # a link (to the file or to a folder above it) led here
        rec["real"] = real_path
    rec.update(attributes(st, real))
    return rec


def dir_record(seen: str, st: os.stat_result) -> dict:
    rec = {"kind": "dir", "path": seen}
    real = os.path.realpath(seen)
    if real != os.path.abspath(seen):
        rec["real"] = real
    rec.update(attributes(st, seen))
    return rec


def link_record(seen: str) -> Optional[dict]:
    try:
        st = os.lstat(seen)
        target = os.readlink(seen)
    except OSError:
        return None
    rec = {"kind": "link", "path": seen, "target": target}
    rec.update(attributes(st, seen, follow=False))
    return rec


def header() -> dict:
    return {"format": FORMAT, "version": VERSION, "computer": platform.node(),
            "user": _user(os.getuid()), "uid": os.getuid(), "home": os.path.expanduser("~"),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def dumps(records: Dict[str, dict], sha: Dict[str, str]) -> bytes:
    """The manifest: a header line, then one line per path (sorted)."""
    lines = [json.dumps(header(), ensure_ascii=False)]
    for rel in sorted(records):
        rec = dict(records[rel])
        rec["rel"] = rel
        if rel in sha:
            rec["sha256"] = sha[rel]
        lines.append(json.dumps(rec, ensure_ascii=False, sort_keys=True))
    return ("\n".join(lines) + "\n").encode("utf-8", "surrogateescape")


def load(path) -> Dict[str, dict]:
    """The records of an earlier backup (empty if it has no manifest)."""
    out: Dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("rel"), str):
                    out[rec.pop("rel")] = rec
    except OSError:
        pass
    return out


def parents(rels: List[str]) -> List[str]:
    out = set()
    for r in rels:
        parts = r.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            out.add("/".join(parts[:i]))
    return sorted(out)
