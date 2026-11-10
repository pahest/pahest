"""Console output that is also written, without colours, to the backup's log files.

Every line printed through `Log` goes to the terminal and to each open log file with a
time stamp. Until the backup folder exists, lines are kept in memory and written out
as soon as a log file is attached.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, TextIO

ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _use_color(stream) -> bool:
    return stream.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


class Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, t: str) -> str: return self._c("1", t)
    def dim(self, t: str) -> str: return self._c("2", t)
    def green(self, t: str) -> str: return self._c("32", t)
    def yellow(self, t: str) -> str: return self._c("33", t)
    def red(self, t: str) -> str: return self._c("31", t)
    def cyan(self, t: str) -> str: return self._c("36", t)


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def looks_secret(s: str) -> bool:
    """A session key, cookie or token pasted where it does not belong."""
    s = s.strip()
    if s.startswith(("sk-ant-", "eyJ")):
        return True
    return len(s) >= 40 and " " not in s and "/" not in s and "~" not in s


def plural(n: int, word: str) -> str:
    """'1 session', '2 sessions' (word is given in plural)."""
    if n == 1 and word.endswith("s"):
        word = word[:-1]
    return f"{n:,} {word}"


def short_path(p) -> str:
    s = str(p)
    h = str(Path.home())
    return "~" + s[len(h):] if s == h or s.startswith(h + os.sep) else s


class Log:
    def __init__(self, out: TextIO = None):
        self.out = out or sys.stdout
        self.tty = self.out.isatty()
        self.s = Style(_use_color(self.out))
        self.files: List[TextIO] = []
        self.pending: List[str] = []
        self._progress_open = False
        self.OK = self.s.green("✓")
        self.WARN = self.s.yellow("!")
        self.FAIL = self.s.red("✗")
        self.DOT = self.s.dim("•")

    # ── files ──
    def attach(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "a", encoding="utf-8", errors="replace")
        for line in self.pending:
            f.write(line)
        f.flush()
        self.files.append(f)

    def detach_all(self) -> None:
        for f in self.files:
            f.close()
        self.files = []

    def _to_files(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        lines = "".join(f"[{stamp}] {strip_ansi(l)}\n" for l in text.split("\n"))
        if self.files:
            for f in self.files:
                try:
                    f.write(lines)
                    f.flush()
                except OSError:
                    pass  # e.g. the disk is full: the terminal still shows everything
        else:
            self.pending.append(lines)

    # ── printing ──
    def _end_progress(self) -> None:
        if self._progress_open:
            self.out.write("\n")
            self._progress_open = False

    def line(self, text: str = "") -> None:
        self._end_progress()
        print(text, file=self.out, flush=True)
        self._to_files(text)

    def detail(self, text: str = "") -> None:
        """A line for the log file only: detail that would crowd the screen."""
        self._to_files(text)

    def ok(self, text: str) -> None: self.line(f"  {self.OK} {text}")
    def warn(self, text: str) -> None: self.line(f"  {self.WARN} {text}")
    def fail(self, text: str) -> None: self.line(f"  {self.FAIL} {text}")
    def note(self, text: str) -> None: self.line(f"  {self.DOT} {text}")

    def section(self, title: str) -> None:
        self.line()
        head = f"── {title} "
        width = min(max(60, shutil.get_terminal_size((100, 24)).columns), 100)
        self.line(self.s.bold(head + "─" * max(4, width - len(head))))

    # ── questions (interactive mode only) ──
    def ask(self, question: str, default: str = "", choices: str = "") -> str:
        """Ask a question. With `choices` (e.g. "ps"), only the first letter counts; anything
        else is refused. An answer that looks like a password or token is never logged."""
        self._end_progress()
        prompt = f"  {self.s.cyan('?')} {question} "
        while True:
            try:
                answer = input(prompt).strip()
            except EOFError:
                answer = ""
            if looks_secret(answer):
                self._to_files(f"  ? {question} (something that looked like a password or token was typed; "
                               "not logged)")
                print(f"  {self.WARN} That looks like a password or token. It was not saved or logged. "
                      "Please answer the question.", file=self.out, flush=True)
                continue
            if choices and answer and answer[0].lower() not in choices:
                print(f"  {self.WARN} Please answer with one of: {', '.join(choices)}", file=self.out, flush=True)
                continue
            self._to_files(f"  ? {question} {answer}")
            if choices and answer:
                return answer[0].lower()
            return answer or default

    def progress(self, label: str) -> "Progress":
        return Progress(self, label)


class Progress:
    """Redrawn bar in a terminal; in the log a line every 10 s or every 5 %."""

    def __init__(self, log: Log, label: str):
        self.log, self.label = log, label
        self.start = time.time()
        self.last_draw = 0.0
        self.last_log = 0.0
        self.last_pct = -1
        self.total_files = 0
        self.total_bytes = 0

    def set_totals(self, files: int, nbytes: int) -> None:
        self.total_files, self.total_bytes = files, nbytes

    def _text(self, files: int, nbytes: int) -> str:
        frac = self._frac(files, nbytes)
        elapsed = time.time() - self.start
        eta = (elapsed / frac - elapsed) if 0 < frac < 1 and elapsed > 2 else 0
        txt = f"{frac*100:3.0f}%  {files:,}/{self.total_files:,}"
        if self.total_bytes:
            txt += f"  {human(nbytes)}/{human(self.total_bytes)}"
        if eta:
            txt += f"  ETA {fmt_dur(eta)}"
        return txt

    def _frac(self, files: int, nbytes: int) -> float:
        if self.total_bytes:
            f = nbytes / self.total_bytes
        elif self.total_files:
            f = files / self.total_files
        else:
            f = 1.0
        return min(1.0, max(0.0, f))

    def update(self, files: int, nbytes: int = 0, current: str = "", force: bool = False) -> None:
        now = time.time()
        frac = self._frac(files, nbytes)
        pct = int(frac * 100)
        text = self._text(files, nbytes)
        # log file: every 10 s or 5 % step
        if force or now - self.last_log >= 10 or pct >= self.last_pct + 5:
            self.last_log, self.last_pct = now, pct
            self.log._to_files(f"  {self.label}: {text}")
        # terminal
        if self.log.tty:
            if not force and now - self.last_draw < 0.1:
                return
            self.last_draw = now
            width = shutil.get_terminal_size((100, 24)).columns
            bar_w = 24
            filled = int(bar_w * frac)
            bar = "█" * filled + "░" * (bar_w - filled)
            line = f"  {self.label:<18} {self.log.s.cyan(bar)} {text}"
            room = width - len(strip_ansi(line)) - 3
            if current and room > 10:
                cur = current if len(current) <= room else "…" + current[-(room - 1):]
                line += "  " + self.log.s.dim(cur)
            self.log.out.write("\r\033[K" + line)
            self.log.out.flush()
            self.log._progress_open = True
        elif force or now - self.last_draw >= 10:
            self.last_draw = now
            print(f"  {self.label}: {text}", file=self.log.out, flush=True)

    def finish(self, files: int, nbytes: int = 0) -> None:
        self.update(files, nbytes, force=True)
        self.log._end_progress()
