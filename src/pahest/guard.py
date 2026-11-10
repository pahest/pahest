"""Read-only guard: during a run, this tool can change files only in its own folders.

The tool reads the apps' data. It writes only to:
1. the backup folder you chose,
2. its settings folder ~/pahest-backups,
3. a private temporary folder made for this run and removed at the end
   (copies of cookie databases).

While a run is going on, `arm()` makes Python refuse everything else, through an audit
hook (PEP 578) that sees every file operation the process makes:

- opening a file for writing, creating, renaming, moving or deleting it, changing its
  permissions, owner, times, flags or extended attributes, anywhere else;
- opening an SQLite database anywhere else (the tool only opens its own copies);
- starting any program except `zstd` (to decompress Codex sessions);
- any network use at all: no socket, no name lookup, no web request. The tool works only
  with files on this Mac.

A refused action raises PermissionError and is listed in `violations`, which the report
shows as a problem. The code never tries any of these; the guard makes sure of it.
"""
from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
import threading
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Iterable, List, Optional

PROGRAMS = ("zstd",)
_NETWORK_EVENTS = ("socket.__new__", "socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg",
                   "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr",
                   "socket.getnameinfo", "urllib.Request", "http.client.connect", "ftplib.connect", "smtplib.connect",
                   "webbrowser.open")
DEVICES = ("/dev/null", "/dev/tty")
LOCK_FLAGS = getattr(os, "O_EXLOCK", 0) | getattr(os, "O_SHLOCK", 0)
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND | LOCK_FLAGS

# event -> (indexes of the paths that get changed, index of a dir_fd argument or None)
_CHANGES = {
    "os.remove": ((0,), 1), "os.rmdir": ((0,), 1), "os.mkdir": ((0,), 2),
    "os.chmod": ((0,), 2), "os.chown": ((0,), 3), "os.utime": ((0,), 3),
    "os.rename": ((0, 1), None), "os.link": ((0, 1), None), "os.symlink": ((1,), 2),
    "os.truncate": ((0,), None), "os.setxattr": ((0,), None), "os.removexattr": ((0,), None),
    "os.chflags": ((0,), None), "os.mkfifo": ((0,), 2), "os.mknod": ((0,), 3),
    "shutil.copyfile": ((1,), None), "shutil.copymode": ((1,), None), "shutil.copystat": ((1,), None),
    "shutil.copytree": ((1,), None), "shutil.move": ((0, 1), None), "shutil.rmtree": ((0,), None),
    "shutil.chown": ((0,), None), "sqlite3.connect": ((0,), None),
    "fcntl.flock": ((0,), None), "fcntl.lockf": ((0,), None),
}
_TWO_DIR_FDS = {"os.rename": (2, 3), "os.link": (2, 3)}
_LOCK_CMDS = {getattr(__import__("fcntl"), n) for n in ("F_SETLK", "F_SETLKW", "F_OFD_SETLK", "F_OFD_SETLKW")
              if hasattr(__import__("fcntl"), n)}
_PROGRAM_EVENTS = ("subprocess.Popen", "os.posix_spawn", "os.posix_spawnp", "os.exec", "os.spawn",
                   "os.system", "os.startfile")

_armed = False
_allowed: List[str] = []
_shown: List[str] = []
_temp = {"dir": None, "previous": None}
_hooked = False
_local = threading.local()
violations: List[str] = []


class ReadOnlyViolation(PermissionError):
    pass


def _norm(p: str) -> str:
    """macOS disks ignore letter case and Unicode form, so the guard compares paths the same way."""
    return unicodedata.normalize("NFD", p).casefold()


def allow(*folders: Path) -> None:
    """Let the run write inside these folders (the backup folder, once it is chosen)."""
    for f in folders:
        real = os.path.realpath(os.fspath(f))
        if _norm(real) not in _allowed:
            _allowed.append(_norm(real))
            _shown.append(real)


def allowed_roots() -> List[str]:
    return list(_shown)


def arm(folders: Iterable[Path]) -> None:
    global _armed, _hooked
    _allowed.clear()
    _shown.clear()
    violations.clear()
    _temp["previous"] = tempfile.tempdir
    _temp["dir"] = tempfile.mkdtemp(prefix="pahest-")
    tempfile.tempdir = _temp["dir"]          # every temporary file of this run goes here
    allow(*folders, Path(_temp["dir"]))
    if not _hooked:
        sys.addaudithook(_hook)
        _hooked = True
    _armed = True


def disarm() -> None:
    global _armed
    _armed = False
    if _temp["dir"]:
        tempfile.tempdir = _temp["previous"]
        import shutil
        shutil.rmtree(_temp["dir"], ignore_errors=True)
        _temp["dir"] = None


def is_armed() -> bool:
    return _armed


def _inside_allowed(real: str) -> bool:
    r = _norm(real)
    return any(r == a or r.startswith(a.rstrip(os.sep) + os.sep) for a in _allowed)


def may_write(path) -> bool:
    """True if the run may change `path`: both the path itself (with links resolved) and the
    entry in its folder (a link is changed where it is, not where it points) must be inside
    the allowed folders."""
    if not _armed:
        return True
    if isinstance(path, int) and _fd_path(path) is None:
        try:                     # pipes and sockets (talking to `security`, `zstd`) are not files
            mode = os.fstat(path).st_mode
        except OSError:
            return True
        return not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
    p = _as_path(path)
    if p is None:
        return False
    if p in DEVICES:
        return True
    if not os.path.isabs(p):
        return False             # relative to an unknown folder: refuse
    full = os.path.realpath(p)
    entry = os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))
    return _inside_allowed(full) and _inside_allowed(entry)


def check_write(path, what: str = "write") -> None:
    """Raise ReadOnlyViolation unless the run may change `path`."""
    if not may_write(path):
        _refuse(f"{what} {_as_path(path) or path!r}")


def _refuse(msg: str) -> None:
    if msg not in violations:
        violations.append(msg)
    raise ReadOnlyViolation(errno.EPERM, "pahest only reads the apps' data; refused", msg)


def _fd_path(fd: int) -> Optional[str]:
    try:
        import fcntl
        buf = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
        return os.fsdecode(buf.split(b"\0", 1)[0])
    except (ImportError, AttributeError, OSError):
        return None


def _as_path(p) -> Optional[str]:
    if isinstance(p, int):
        return _fd_path(p)       # an open file: check the file it refers to
    if p is None:
        return None
    if hasattr(p, "fileno") and not isinstance(p, (str, bytes)):
        try:
            return _fd_path(p.fileno())
        except (OSError, ValueError):
            return None
    try:
        p = os.fspath(p)
    except TypeError:
        return None
    if isinstance(p, bytes):
        p = os.fsdecode(p)
    return p


def _with_dir_fd(path: Optional[str], dir_fd) -> Optional[str]:
    if path is None or os.path.isabs(path) or not isinstance(dir_fd, int) or dir_fd < 0:
        return path
    base = _fd_path(dir_fd)
    return os.path.join(base, path) if base else path    # unknown folder stays relative: refused


def _sqlite_path(db) -> Optional[str]:
    p = _as_path(db)
    if p is None or p == ":memory:" or p == "":
        return None
    if p.startswith("file:"):
        u = urllib.parse.urlsplit(p)
        return urllib.parse.unquote(u.path) or None
    return p


def _program_ok(event: str, args: tuple) -> bool:
    if event not in ("subprocess.Popen", "os.posix_spawn", "os.posix_spawnp"):
        return False
    executable, argv = args[0], args[1]
    if isinstance(argv, (str, bytes)):
        argv = [argv]
    argv = [os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in (argv or [])]
    prog = os.path.basename(os.fsdecode(executable) if isinstance(executable, bytes) else
                            str(executable or (argv[0] if argv else "")))
    if prog not in PROGRAMS:
        return False
    # decompress one file to standard output, nothing else
    return len(argv) == 5 and argv[1:4] == ["-dcq", "--no-progress", "--"]


def _hook(event: str, args: tuple) -> None:
    if not _armed or getattr(_local, "busy", False):
        return
    if event not in ("open", "fcntl.fcntl") and event not in _CHANGES and \
            event not in _PROGRAM_EVENTS and event not in _NETWORK_EVENTS:
        return
    _local.busy = True
    try:
        if event == "open":
            path, mode, flags = args[0], args[1], args[2]
            writes = (isinstance(flags, int) and flags & WRITE_FLAGS) or \
                (isinstance(mode, str) and any(c in mode for c in "wax+"))
            if writes:
                check_write(path, "open for writing")
        elif event == "fcntl.fcntl":
            if len(args) > 1 and args[1] in _LOCK_CMDS:
                check_write(args[0], "lock")
        elif event in _CHANGES:
            idxs, fd_idx = _CHANGES[event]
            for i in idxs:
                if i >= len(args):
                    continue
                if event in _TWO_DIR_FDS:
                    j = _TWO_DIR_FDS[event][i]
                    dir_fd = args[j] if len(args) > j else None
                else:
                    dir_fd = args[fd_idx] if fd_idx is not None and len(args) > fd_idx else None
                p = _sqlite_path(args[i]) if event == "sqlite3.connect" else _as_path(args[i])
                if event == "sqlite3.connect" and p is None:
                    continue     # an in-memory database
                p = _with_dir_fd(p, dir_fd)
                check_write(p if p is not None else args[i], event)
        elif event in _PROGRAM_EVENTS:
            if not _program_ok(event, args):
                _refuse(f"{event} {args[1] if len(args) > 1 else args[0]!r}")
        elif event in _NETWORK_EVENTS:
            _refuse(f"network use ({event})")
    finally:
        _local.busy = False
