"""Readable copies: every local session as a Markdown file, every picture as an image file.

The apps keep their sessions as JSON Lines transcripts and SQLite databases. These are
complete, but hard to read without the apps. After all parts are saved, this step reads
the backup's own copies (never the apps' files) and writes:

  README.md                                   start here: what is where
  readable/claude-code/index.md               every session, by project, newest first
  readable/claude-code/<project>/<date> <title> (<id>).md
  readable/claude-code/<project>/images/      pictures from the sessions
  readable/claude-code/prompt-history.md      everything typed into Claude Code
  readable/claude-desktop/...                 the Claude desktop app's local sessions
  readable/codex/index.md, readable/codex/<yyyy-mm>/<date> <title> (<id>).md, images/
  readable/codex/prompt-history.md
  readable/codex/databases/<db>/<table>.json  the Codex databases as plain JSON

  readable/images.html                        every picture of every session

The readable copies are made again in every backup from the saved files, so they also
cover sessions kept from earlier backups after an app deleted them. Nothing is shortened;
the raw transcript is linked at the top of every file.
"""
from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import json
import posixpath
import re
import shlex
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from . import HOME_URL, __version__, guard, htmlview, paths
from .render import human_month, human_time, jdump, parse_time, safe_name, utf8
from .result import Ctx, Result
from .store import DiskFull, clone_or_copy

ID = "readable"
ROOT = "readable"
# Everything that is part of a conversation is shown in full, never shortened, on the web page and in
# the Markdown copy: your messages, the model's text, thinking and tool calls (every input), every tool
# result, and what the app added to the conversation (instructions, reminders, attached files, hook
# output, notes), which is folded. Only bookkeeping stays in the raw transcript alone: ids, times, token
# counts, settings flags, copies of API requests, and the app's own backups of edited files.
CC_KEEP = {"user", "assistant", "system", "summary", "ai-title", "custom-title", "attachment"}
CODEX_KEEP = {"session_meta", "response_item", "turn_context", "compacted", "event_msg", "world_state",
              "retained_context"}
# Lines known to hold no conversation; they are skipped without being parsed (much faster).
# Anything else is parsed, so a new kind of line is never lost by mistake.
CC_SKIP = {"api-request-blob", "api-request", "api-request-shape", "last-prompt", "atis-latch",
           "mode", "permission-mode", "pr-link", "agent-name", "queue-operation", "session-owner",
           "bridge-session", "file-history-snapshot", "file-history-delta", "tools-used", "frame-link",
           "cost-state", "history-suppression", "isolation-latch", "fork-context-ref"}
CODEX_SKIP = {"token_usage_record", "inter_agent_communication_metadata"}
# Codex's own records of each step (event_msg) repeat the conversation, but sometimes hold more: the full
# output of a command when the model saw a shortened one, MCP tool results, web search results, goals.
# Only what is not already on the page is shown; these keys are bookkeeping.
CODEX_EVENT_BOOKKEEPING = {"type", "thread_id", "threadId", "turn_id", "root_turn_id", "id", "client_id", "call_id",
                           "started_at", "completed_at", "started_at_ms", "completed_at_ms", "process_id", "source",
                           "model_context_window", "collaboration_mode_kind", "createdAt", "updatedAt", "tokensUsed",
                           "timeUsedSeconds", "_meta", "cwd", "pluginId", "ref_id", "duration_ms", "full", "status",
                           "parsed_cmd", "formatted_output"}
CODEX_EVENT_LABELS = {"kind", "server", "tool", "name", "phase"}     # say what a record is; not content by themselves
# session_meta fields shown in the page header (the rest is shown as "Session settings")
CODEX_META_SHOWN = {"id", "session_id", "timestamp", "cwd", "originator", "cli_version", "git", "base_instructions",
                    "source", "thread_source", "parent_thread_id", "model_provider"}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
SESSION_MARK = "<!-- conversation -->"
LINE = "\x00line"                # the line number of a raw record (added while reading; never shown)
RAW = "\x00raw\x00"              # in a page: the link to its raw transcript (made relative when the page is written)
PATH = "\x00path:"               # in a page: a file of this backup, _path(rel) (made relative when the page is written)
_TYPE_RE = re.compile(rb'"type"\s*:\s*"([A-Za-z_\-]+)"')
_REMINDER_RE = re.compile(r"<system-reminder>(.*?)</system-reminder>\s*", re.S)
_WRAPPED_RE = re.compile(r"^\s*<([A-Za-z_][\w\-]*)[^>]*>(.*)</\1>\s*$", re.S)
# Context that Codex adds to a "user" message by itself (seen in real sessions). Only these are
# hidden; text in any other tag is shown, so your own words are never dropped by mistake.
CODEX_CONTEXT_TAGS = {"environment_context", "codex_internal_context", "goal_context", "guardian_tool_descriptions",
                      "recommended_plugins", "heartbeat", "skill", "user_instructions", "INSTRUCTIONS",
                      "collaboration_mode", "personality_spec", "external_codex_apps_open_page",
                      "external_codex_apps_writing_block_edits"}
CODEX_CONTEXT_PREFIXES = ("# AGENTS.md instructions", "<permissions instructions>", "<user_instructions>",
                          "<environment_context>")
_IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/gif": "gif",
              "image/webp": "webp", "image/heic": "heic", "application/pdf": "pdf"}
_PIC_HEADS = ("iVBORw0KGgo", "/9j/", "R0lGOD", "UklGR")      # base64 of the start of a PNG, JPEG, GIF, WebP
_BASE64 = re.compile(r"[A-Za-z0-9+/=\r\n]+")
_PATH_RE = re.compile("\x00path:([^\x00]*)\x00")


# ── small helpers ────────────────────────────────────────────────────────────

def _fence(text: str, lang: str = "") -> str:
    """A code block whose fence cannot be closed by backticks inside the text."""
    run = max((len(m) for m in re.findall(r"`+", text)), default=0)
    f = "`" * max(3, run + 1)
    return f"{f}{lang}\n{text.rstrip()}\n{f}"


Code = htmlview.Code


def _code(text, lang: str = "") -> Code:
    """Tool input or output, or context the app added: shown exactly as stored."""
    return Code(text if isinstance(text, str) else str(text), lang)


def _md(x) -> str:
    """A Markdown line, a Code block (as a fence), or a list of both."""
    if isinstance(x, list):
        return "\n\n".join(_md(p) for p in x)
    return _fence(x.text, x.lang) if isinstance(x, Code) else x


def _dump(v, pics: Optional["Pics"] = None) -> str:
    """Any JSON value as readable text with every value in full: `key: value`, nested items indented,
    text with several lines kept exactly as it is (below its key). With `pics`, a picture stored as
    text is saved as an image file and named here (shown below the text: Pics.take)."""
    out: List[str] = []
    v = _unpic(v, pics)

    def emit(prefix: str, val, ind: str) -> None:
        if prefix.strip() == "encrypted_content:" and isinstance(val, str):
            val = f"(encrypted by the company, {len(val):,} characters; nobody else can read it; kept in the raw transcript)"
        if isinstance(val, dict) and val:
            if prefix.strip():
                out.append(prefix.rstrip())
            for k, x in val.items():
                emit(f"{ind}{k}: ", x, ind + "  ")
        elif isinstance(val, list) and val:
            if prefix.strip():
                out.append(prefix.rstrip())
            for x in val:
                emit(f"{ind}- ", x, ind + "  ")
        elif isinstance(val, str) and "\n" in val:
            out.append(prefix + "|")
            out.extend((ind + line) if line else "" for line in val.split("\n"))
        else:
            out.append(prefix + (val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)))
    emit("", v, "")
    return "\n".join(out)


def _link(target: str) -> str:
    return f"<{target}>" if re.search(r"[\s()<>]", target) else target


def _path(rel: str) -> str:
    """A file of this backup (path from the backup root) in a page being built: see _fix_paths."""
    return f"{PATH}{rel}\x00"


def _fix_paths(md: str, page: str, raw: str) -> str:
    """Make the files a page links to (pictures, documents, its raw transcript) relative to the page.
    The markers cannot be typed, so text from the conversation is never changed."""
    md = md.replace(RAW, _link(_rel(page, raw)))
    return _PATH_RE.sub(lambda m: _link(_rel(page, m.group(1))), md)


def _pic_md(rel: str, alt: str = "image") -> str:
    return f"![{alt}]({_path(rel)})"


_PIC_MD_RE = re.compile(r"!\[([^\]\n]*)\]\(\x00path:([^\x00]*)\x00\)")
PIC_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic")
# Where a picture on the pictures page came from (the filter there), most telling first.
PIC_KINDS = (("you", "You pasted"), ("generated", "Generated"), ("tool", "From tools"), ("app", "App records"))
_PIC_RANK = {k: i for i, (k, _) in enumerate(PIC_KINDS)}


def _conv_pictures(conv: "Conv") -> List[Tuple[str, str, Optional[datetime]]]:
    """Every picture a session shows, once: (file, where it came from, when). "you": in your message;
    "generated": made by an image tool; "tool": in a tool call or result (what the model looked at);
    "app": in what the app added (Codex's own records, copies kept after compacting, notes). A picture
    shown in several places counts where it is most telling (you > generated > tool > app)."""
    found: Dict[str, Tuple[str, str, Optional[datetime]]] = {}

    def scan(x, kind: str, ts) -> None:
        if isinstance(x, list):
            for y in x:
                scan(y, kind, ts)
        elif isinstance(x, str) and PATH in x:
            for m in _PIC_MD_RE.finditer(x):
                rel = m.group(2)
                if not rel.lower().endswith(PIC_EXT):
                    continue
                k = "generated" if m.group(1) == "generated image" else kind
                if rel not in found or _PIC_RANK[k] < _PIC_RANK[found[rel][1]]:
                    found[rel] = (rel, k, ts)          # the first place it is shown this way
    for b in conv.blocks:
        t, ts = b["t"], b.get("ts")
        if t == "you":
            scan(b["md"], "app" if b.get("auto") else "you", ts)
        elif t in ("divider", "summary"):
            scan(b["md"], "app", ts)
        elif t == "note":
            scan(b.get("md"), "app", ts)
            scan(b.get("extra"), "app", ts)
        elif t == "context":
            for item in b["items"]:
                scan(item[1], "app", ts)
        elif t == "ai":
            for it in b["items"]:
                if it[0] in ("text", "thinking"):
                    scan(it[1], "tool", ts)
                elif it[0] == "tool":
                    scan(it[2], "tool", ts)
                elif it[0] == "result":
                    scan(it[3], "tool", ts)
                elif it[0] == "context":
                    scan(it[2], "app", ts)
    return list(found.values())


def _iso(dt: Optional[datetime]) -> str:
    """Local time as the pages' scripts read it ("2026-10-24T10:00")."""
    return _local(dt, "%Y-%m-%dT%H:%M")


def _rel(from_md: str, to: str) -> str:
    return posixpath.relpath(to, posixpath.dirname(from_md) or ".")


def _local(dt: Optional[datetime], fmt: Optional[str] = None) -> str:
    """fmt=None: the way dates are shown ("2026 October 24, 10:00"); a format: file names."""
    if fmt is None:
        return human_time(dt)
    try:
        return dt.astimezone().strftime(fmt) if dt else ""
    except (OverflowError, ValueError, OSError):
        return ""             # a date the clock cannot show (year 1, year 9999)


def _heading(who: str, ts: Optional[datetime], fmt: Optional[str] = None) -> str:
    when = _local(ts, fmt)
    return f"### {who} · {when}" if when else f"### {who}"


def _one_line(text: str, limit: int = 80) -> str:
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#>*- ").strip()
        if line:
            return line[:limit].rstrip() + ("…" if len(line) > limit else "")
    return ""


def _plain(text: str, limit: int = 280) -> str:
    """Markdown as one line of plain text, for the previews in index.html."""
    text = (text or "")[:50 * limit]                                 # the start is enough (a prompt can be megabytes)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)                   # pictures
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)                   # links: keep the words
    t = re.sub(r"^(`{3,}|~{3,}).*$", " ", t, flags=re.M)              # code fences
    t = re.sub(r"[`*_>#]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit].rstrip() + "…" if len(t) > limit else t


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _first_type(raw: bytes) -> Optional[str]:
    m = _TYPE_RE.search(raw, 0, 4000)
    return m.group(1).decode() if m else None


def _json_lines(path: Path, keep: set, skip: set, opener: Optional[Callable] = None) -> Iterator[dict]:
    """The lines of a transcript worth showing."""
    with (opener() if opener else open(path, "rb")) as f:
        for n, raw in enumerate(f, 1):
            if _first_type(raw) in skip:
                continue
            try:
                o = json.loads(raw)
            except (ValueError, RecursionError):
                continue       # the last line of a session that was still being written
            if isinstance(o, dict) and o.get("type") in keep:
                o[LINE] = n    # where it is in the raw transcript, for "Original: …, line n" links
                yield o


def _image_bytes(source) -> Tuple[Optional[bytes], str]:
    """(data, extension) from a base64 image block or a data: URL."""
    media, data = "", None
    if isinstance(source, dict):
        media = source.get("media_type") or ""
        data = source.get("data")
    elif isinstance(source, str) and source.startswith("data:"):
        head, _, data = source.partition(",")
        media = head[5:].split(";")[0]
    if not isinstance(data, str) or not data:
        return None, ""
    try:
        raw = base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError):
        return None, ""
    return raw, _IMAGE_EXT.get(media.lower()) or _magic(raw) or "bin"


def _magic(raw: bytes) -> str:
    """The kind of picture, from its first bytes ("" if not a PNG, JPEG, GIF or WebP)."""
    return "png" if raw[:4] == b"\x89PNG" else "jpg" if raw[:2] == b"\xff\xd8" else \
        "gif" if raw[:4] == b"GIF8" else "webp" if raw[8:12] == b"WEBP" else ""


def _pic_id(data: bytes) -> str:
    """The name of a picture's file: the start of its SHA-256 (the same picture is saved once)."""
    return hashlib.sha256(data).hexdigest()[:20]


def _picture(s) -> Tuple[Optional[bytes], str]:
    """A text that is a whole picture (a data:image URL in base64, or the base64 of a PNG, JPEG, GIF or
    WebP): (its bytes, extension). (None, "") for any other text."""
    if not isinstance(s, str) or len(s) < 100 or not s.startswith(("data:image/",) + _PIC_HEADS):
        return None, ""
    return _picture_of(s)


@functools.lru_cache(maxsize=16)              # the same text is asked about a few times in a row
def _picture_of(s: str) -> Tuple[Optional[bytes], str]:
    if s.startswith("data:image/"):
        head = s[:s.find(",")] if "," in s else ""
        if ";base64" not in head:
            return None, ""
        data, ext = _image_bytes(s)
        return (data, ext) if data and ext in ("png", "jpg", "gif", "webp", "heic") else (None, "")
    if not s.startswith(_PIC_HEADS) or not _BASE64.fullmatch(s):
        return None, ""
    try:
        data = base64.b64decode(s)
    except (binascii.Error, ValueError):
        return None, ""
    ext = _magic(data)
    return (data, ext) if ext else (None, "")


class Pics:
    """The pictures of one page. A picture stored as text inside a record (base64) is saved as an image
    file; the text says so, and the picture is shown below it. `known`: every picture the page shows."""

    def __init__(self, save: Callable[[bytes, str], str]):
        self._save = save
        self.known: set = set()
        self.pending: List[str] = []        # saved since take(), to show below the text they were in

    def file(self, data: bytes, ext: str) -> str:
        rel = self._save(data, ext)
        self.known.add(_pic_id(data))
        return rel

    def shown(self, s) -> bool:
        """A picture the page already shows."""
        data, _ = _picture(s)
        return data is not None and _pic_id(data) in self.known

    def note(self, s) -> Optional[str]:
        """Save a text that is a picture; return the words shown in its place (None: not a picture)."""
        data, ext = _picture(s)
        if data is None:
            return None
        rel = self.file(data, ext)
        if rel not in self.pending:
            self.pending.append(rel)
        return (f"(a picture, shown below as {posixpath.basename(rel)}; the raw transcript has it as "
                f"{len(s):,} characters of base64 text)")

    def inside(self, s: str, depth: int = 0) -> None:
        """Pictures inside JSON written as text (a tool's result stored as one text): the text is shown
        exactly as stored; each picture in it is also saved and shown below it."""
        if depth > 4 or s.lstrip()[:1] not in ("{", "[") or \
                not ("data:image/" in s or any(h in s for h in _PIC_HEADS)):
            return
        try:
            v = json.loads(s)
        except (ValueError, RecursionError):
            return
        stack = [v]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                stack.extend(reversed(list(x.values())))
            elif isinstance(x, list):
                stack.extend(reversed(x))
            elif isinstance(x, str):
                data, ext = _picture(x)
                if data is None:
                    self.inside(x, depth + 1)
                    continue
                rel = self.file(data, ext)
                if rel not in self.pending:
                    self.pending.append(rel)

    def take(self) -> List[str]:
        """The pictures saved since the last call, as Markdown to show below the text."""
        out, self.pending = [_pic_md(r) for r in self.pending], []
        return out


def _unpic(v, pics: Optional[Pics]):
    """A value with each picture stored as text replaced by a note (the picture is saved; see Pics)."""
    if pics is None:
        return v
    if isinstance(v, str):
        note = pics.note(v)
        if note is None:
            pics.inside(v)                # the text stays as it is; pictures in it are shown below it
        return note or v
    if isinstance(v, dict):
        return {k: _unpic(x, pics) for k, x in v.items()}
    if isinstance(v, list):
        return [_unpic(x, pics) for x in v]
    return v


def _dumped(v, pics: Optional[Pics]) -> list:
    """A value in full (see _dump), then the pictures that were in it."""
    return [Code(_dump(v, pics))] + (pics.take() if pics else [])


def _json_parts(v, pics: Optional[Pics]) -> list:
    """A value as JSON, then the pictures that were in it."""
    return [Code(json.dumps(_unpic(v, pics), ensure_ascii=False, indent=1), "json")] + (pics.take() if pics else [])


# ── writing ──────────────────────────────────────────────────────────────────

@dataclass
class Session:
    title: str
    md: str                      # path from the backup root
    raw: str
    started: Optional[datetime]
    last: Optional[datetime]
    messages: int
    group: str                   # project folder or month
    where: str = ""              # working folder
    notes: List[str] = field(default_factory=list)
    surface: str = ""            # Desktop app | Terminal | Code editor | Automation
    helper: bool = False         # a subagent or an automatic review, not a conversation with you
    preview: str = ""            # the start of your first message, as plain text
    model: str = ""
    version: str = ""
    sid: str = ""                # the app's session id
    branch: str = ""             # git branch
    pictures: List[Tuple[str, str, Optional[datetime]]] = field(default_factory=list)   # see _conv_pictures


class Writer:
    def __init__(self, ctx: Ctx, res: Result):
        self.ctx, self.res = ctx, res
        self.prev = ctx.prev(ID)
        self.images: set = set()
        self.names: set = set()
        self.listed: List[Tuple[str, Session]] = []     # (app, session) for index.html
        self.unlisted: List[Tuple[str, Session]] = []   # pages not in the lists (Claude Code subagents)

    def text(self, rel: str, text: str) -> None:
        self.ctx.store.add_bytes(rel, utf8(text), self.prev)

    def data(self, rel: str, data: bytes) -> None:
        self.ctx.store.add_bytes(rel, data, self.prev)

    def image(self, folder: str, data: bytes, ext: str) -> str:
        rel = f"{folder}/images/{_pic_id(data)}.{ext}"
        if rel not in self.images:
            self.data(rel, data)
            self.images.add(rel)
        return rel

    def unique(self, rel: str) -> str:
        base, ext = posixpath.splitext(rel)
        n, out = 2, rel
        while out.lower() in self.names:
            out = f"{base} {n}{ext}"
            n += 1
        self.names.add(out.lower())
        return out

    def raw_path(self, rel: str) -> Path:
        return self.ctx.store.path(rel)

    def exists(self, rel: str) -> bool:
        """Is this file (or folder) in the backup? Used to keep only links that lead somewhere."""
        store = self.ctx.store
        if rel in store.manifest:
            return True
        if not hasattr(self, "_folders"):
            self._folders = {r.rsplit("/", i)[0] for r in store.manifest for i in range(1, r.count("/") + 1)}
        return rel in self._folders

    def deleted(self, rel: str) -> Optional[str]:
        return self.ctx.store.deleted.get(rel)


def _header(title: str, rows: List[Tuple[str, str]]) -> List[str]:
    out = [f"# {title}", ""]
    rows = [(k, v) for k, v in rows if v]
    if rows:
        out += ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows] + [""]
    return out


# ── Claude Code transcripts ──────────────────────────────────────────────────

def _cc_tool_input(name: str, inp, pics: Optional[Pics] = None) -> list:
    """A tool call's input: a readable view of the main fields, then every other field as JSON."""
    if not isinstance(inp, dict):
        return _json_parts(inp, pics)
    out: list = []
    used = set()

    def take(*keys):
        used.update(keys)
    if name == "Bash" and isinstance(inp.get("command"), str):
        out.append(_code(inp["command"], "bash"))
        take("command")
    elif name in ("Read", "NotebookRead") and isinstance(inp.get("file_path"), str):
        out.append(f"`{inp['file_path']}`")
        take("file_path")
    elif name == "Write" and isinstance(inp.get("file_path"), str):
        out += [f"`{inp['file_path']}`", _code(inp.get("content", ""))]
        take("file_path", "content")
    elif name in ("Edit", "MultiEdit") and isinstance(inp.get("file_path"), str):
        out.append(f"`{inp['file_path']}`")
        take("file_path")
        edits = inp.get("edits") if name == "MultiEdit" else [inp]
        if name == "MultiEdit":
            take("edits")
        else:
            take("old_string", "new_string")
        for e in edits if isinstance(edits, list) else []:
            if isinstance(e, dict):
                diff = "\n".join(["- " + x for x in str(e.get("old_string", "")).split("\n")] +
                                 ["+ " + x for x in str(e.get("new_string", "")).split("\n")])
                out.append(_code(diff, "diff"))
                extra = {k: v for k, v in e.items() if k not in ("old_string", "new_string")}
                if name == "MultiEdit" and extra:
                    out.append(_code(json.dumps(extra, ensure_ascii=False, indent=1), "json"))
        if name == "MultiEdit" and not isinstance(edits, list):
            used.discard("edits")
    elif name == "TodoWrite" and isinstance(inp.get("todos"), list):
        for t in inp["todos"]:
            if isinstance(t, dict):
                mark = "x" if t.get("status") == "completed" else " "
                line = f"- [{mark}] {t.get('content', '')}"
                if t.get("status") not in ("completed", "pending", None):
                    line += f" ({t.get('status')})"
                if t.get("activeForm") and t.get("activeForm") != t.get("content"):
                    line += f" — *{t['activeForm']}*"
                extra = {k: v for k, v in t.items() if k not in ("content", "status", "activeForm")}
                if extra:
                    line += f" `{json.dumps(extra, ensure_ascii=False)}`"
                out.append(line)
            else:
                out.append(f"- {json.dumps(t, ensure_ascii=False)}")
        take("todos")
    elif name in ("Glob", "Grep") and isinstance(inp.get("pattern"), str):
        out.append(f"`{inp['pattern']}`" + (f" in `{inp['path']}`" if isinstance(inp.get("path"), str) else ""))
        take("pattern", "path" if isinstance(inp.get("path"), str) else "pattern")
    elif name == "WebFetch" and isinstance(inp.get("url"), str):
        out.append(f"<{inp['url']}>")
        take("url")
    elif name == "WebSearch" and isinstance(inp.get("query"), str):
        out.append(f"“{inp['query']}”")
        take("query")
    elif name in ("Task", "Agent") and isinstance(inp.get("prompt"), str):
        out.append(_code(inp["prompt"], "text"))
        take("prompt")
    if isinstance(inp.get("description"), str) and inp["description"] and name != "TodoWrite":
        out.insert(0, f"*{inp['description']}*")
        take("description")
    rest = {k: v for k, v in inp.items() if k not in used}
    if rest:
        out += _json_parts(rest, pics)
    return out


# Messages Claude Code puts in your place that you did not type, by the "origin" it records.
CC_SENDERS = {"task-notification": "Background task", "peer": "Another session",
              "coordinator": "Coordinator", "auto-continuation": "Automatic"}


def _cc_sender(o: dict, text: str) -> str:
    """Who sent a "user" message that you did not type ("" when you typed it)."""
    origin = o.get("origin") if isinstance(o.get("origin"), dict) else {}
    kind = str(origin.get("kind") or "")
    if kind and kind != "human":
        return CC_SENDERS.get(kind, "Claude Code")
    if text.lstrip().startswith("<task-notification>"):     # older sessions record no origin
        return CC_SENDERS["task-notification"]
    return ""


class Conv:
    """A conversation as blocks. The same blocks become the Markdown file and the web page.

    Blocks: you (a message in your place: yours, or sent by the app), ai (one turn of the assistant,
    with items: text, thinking, redacted, tool, result, image, context), context (what the app added
    to the conversation), note (a notice from the app), divider (e.g. "compacted here") and summary.
    Text is Markdown, or a Code block shown exactly as stored; files are linked with _path() (made
    relative to the page later). Nothing is ever shortened."""

    def __init__(self, raw_name: str = ""):
        self.blocks: List[dict] = []
        self.turn: Optional[dict] = None
        self._seen: Dict[str, Tuple[str, str]] = {}      # context text -> (label, time) where first shown
        self.raw_name = raw_name                          # the raw transcript (linked where text is left out)
        self.line: Optional[int] = None                   # the line of the record being read
        self.pics: Optional[Pics] = None                  # the page's pictures (set by the renderer)

    def src(self) -> str:
        """A link to the record in the raw transcript, for places where not every byte is shown."""
        where = f"{self.raw_name}, line {self.line:,}" if self.line else self.raw_name
        return f"Original: [{where}]({RAW}) (the raw transcript in this backup, every byte)"

    def you(self, who: str, ts: Optional[datetime], md, auto: bool = False, sub: str = "") -> None:
        """A message in your place. `md`: Markdown, a Code block, or a list of both. `auto`: not typed
        by you but sent by the app (a background task finished, another session wrote)."""
        self.blocks.append({"t": "you", "who": who, "ts": ts, "md": md, "auto": auto, "sub": sub})
        self.turn = None

    def add(self, who: str, ts: Optional[datetime], *item) -> None:
        if self.turn is None:
            self.turn = {"t": "ai", "who": who, "ts": ts, "items": []}
            self.blocks.append(self.turn)
        if item[0] == "redacted":
            if self.turn["items"] and self.turn["items"][-1][0] == "redacted":
                return  # several encrypted reasoning parts in a row: one note says it
            item = ("redacted", item[1] if len(item) > 1 else "Thinking (encrypted by Anthropic; not readable)",
                    self.src())
        elif item[0] == "thinking" and len(item) < 3:
            item += ("Thinking",)
        self.turn["items"].append(item)

    def context(self, app: str, ts: Optional[datetime], label: str, text: str, lang: str = "",
                reduced: bool = False, pics: Optional[List[str]] = None) -> None:
        """Something the app added to the conversation (instructions, a reminder, an attached file).
        Shown folded, in full. Text the app repeats word for word is shown in full the first time;
        later copies say where it was shown and link to the record in the raw transcript. `reduced`:
        not every byte is shown (copies of items already on the page, encrypted data): links too.
        `pics`: pictures that were in the text (Markdown), shown below it."""
        when = _local(ts, "%H:%M") or ""
        if len(text) > 300:
            first = self._seen.get(text)
            if first:
                pics = None                     # shown with the first copy
                label, text, lang, reduced = (f"{label} (the same as before)",
                                              f"Exactly the same text as “{first[0]}”" +
                                              (f" at {first[1]}" if first[1] else "") + " earlier on this page.", "", True)
            else:
                self._seen[text] = (label, when)
        if "(encrypted by the company," in text:
            reduced = True
        body = [Code(text, lang)] + pics if pics else Code(text, lang)
        item = (label, body, self.src() if reduced else "")
        if self.turn is not None:
            self.turn["items"].append(("context",) + item[:2] + (app,) + item[2:])
        elif self.blocks and self.blocks[-1]["t"] == "context" and self.blocks[-1]["who"] == app:
            self.blocks[-1]["items"].append(item)
        else:
            self.blocks.append({"t": "context", "who": app, "ts": ts, "items": [item]})

    def placeholder(self):
        """A place for something decided later (see fill): where it is, in a turn or between blocks."""
        if self.turn is not None:
            self.turn["items"].append(("skip",))
            return (self.turn["items"], len(self.turn["items"]) - 1, True)
        self.blocks.append({"t": "skip"})
        return (self.blocks, len(self.blocks) - 1, False)

    def fill(self, ref, app: str = "", ts: Optional[datetime] = None, label: str = "", text: str = "",
             line: Optional[int] = None, pics: Optional[List[str]] = None) -> None:
        """Put context the app added into a place kept for it (nothing: the place stays empty)."""
        if not text:
            return
        where, i, in_turn = ref
        keep = (self.turn, self.blocks, self.line)
        self.line, self.blocks = line, []
        self.turn = {"items": []} if in_turn else None
        self.context(app, ts, label, text, reduced=True, pics=pics)
        made = self.turn["items"][0] if in_turn else self.blocks[0]
        self.turn, self.blocks, self.line = keep
        where[i] = made

    def note(self, app: str, ts: Optional[datetime], label: str, md: str = "", extra: Optional[str] = None,
             pics: Optional[List[str]] = None) -> None:
        """A notice from the app, shown as a short line (e.g. "Worked for 2m 44s")."""
        body = ([Code(extra)] + pics if pics else Code(extra)) if extra else None
        self.blocks.append({"t": "note", "who": app, "label": label, "ts": ts, "md": md, "extra": body})
        self.turn = None

    def divider(self, md: str, summary: str = "") -> None:
        self.blocks.append({"t": "divider", "md": md})
        if summary:
            self.blocks.append({"t": "summary", "md": summary})
        self.turn = None

    def summary(self, md: str) -> None:
        self.blocks.append({"t": "summary", "md": md})
        self.turn = None

    def has_ai(self) -> bool:
        return any(b["t"] == "ai" for b in self.blocks)

    @staticmethod
    def _ctx_md(app: str, label: str, body, src: str = "") -> List[str]:
        return [f"<details><summary>Added by {app}: {label}</summary>", ""] + ([src, ""] if src else []) + \
            [_md(body), "", "</details>", ""]

    def markdown(self) -> str:
        out: List[str] = []
        for b in self.blocks:
            if b["t"] == "you":
                who = b["who"] + (f" ({b['sub']})" if b.get("sub") else "")
                out += ["", _heading(who, b["ts"]), "", _md(b["md"]), ""]
            elif b["t"] == "divider":
                out += ["", "---", "", b["md"], "", "---", ""]
            elif b["t"] == "summary":
                out += ["", "#### Summary of the earlier conversation", "", b["md"], ""]
            elif b["t"] == "context":
                out.append("")
                for label, body, src in b["items"]:
                    out += self._ctx_md(b["who"], label, body, src)
            elif b["t"] == "skip":
                continue
            elif b["t"] == "note":
                when = _local(b["ts"])
                out += ["", f"> **{b['label']}**" + (f" · {when}" if when else "")]
                if b["md"]:
                    out += [">"] + ["> " + x for x in b["md"].split("\n")]
                out.append("")
                if b.get("extra"):
                    out += self._ctx_md(b["who"], "details", b["extra"])
            else:
                out += ["", _heading(b["who"], b["ts"], "%H:%M"), ""]
                for it in b["items"]:
                    kind = it[0]
                    if kind == "text":
                        out += [it[1], ""]
                    elif kind == "thinking":
                        out += [f"> **{it[2]}**", ">",
                                "\n".join("> " + x for x in it[1].split("\n")), ""]
                    elif kind == "redacted":
                        out += [f"> *{it[1]}* · {it[2]}", ""]
                    elif kind == "tool":
                        out += [f"**{it[1]}**", ""] + [_md(x) + "\n" for x in it[2]]
                    elif kind == "result":
                        if it[2]:
                            out += [f"*{it[1]}:*", "", _fence(it[2]), ""]
                        out += [_md(x) + "\n" for x in it[3]]
                    elif kind == "context":
                        out += self._ctx_md(it[3], it[1], it[2], it[4])
        return "\n".join(out)



def claude_surface(entrypoint: str) -> str:
    e = (entrypoint or "").lower()
    if "desktop" in e:
        return "Desktop app"
    if any(x in e for x in ("vscode", "jetbrains", "ide", "cursor")):
        return "Code editor"
    if e.startswith("sdk") or "action" in e:
        return "Automation"
    if e == "cli":
        return "Terminal"
    return ""


def codex_surface(meta: dict) -> str:
    o = str(meta.get("originator") or "").lower()
    src = meta.get("source") if isinstance(meta.get("source"), str) else ""
    if "desktop" in o:
        return "Desktop app"
    if "vscode" in o or "jetbrains" in o:
        return "Code editor"
    if "exec" in o or src == "exec":
        return "Automation"
    if "tui" in o or "cli" in o or src == "cli":
        return "Terminal"
    return ""


CC_BOOKKEEPING = {LINE, "type", "subtype", "uuid", "parentUuid", "logicalParentUuid", "sessionId", "cwd", "version",
                  "gitBranch", "userType", "isSidechain", "entrypoint", "slug", "timestamp", "isMeta", "level",
                  "requestId", "toolUseID", "promptId", "agentId"}
CC_SYSTEM_LABELS = {"away_summary": "Recap (while you were away)", "informational": "Note", "local_command": "Command",
                    "scheduled_task_fire": "Scheduled task", "bridge_status": "Remote control", "api_error": "API error"}
CC_ATTACHMENT_LABELS = {
    "instructions": "Instructions (CLAUDE.md)", "nested_memory": "Instructions file", "file": "Attached file",
    "directory": "Attached folder", "prompt_snapshot": "System prompt", "skill_listing": "List of skills",
    "deferred_tools_record": "List of tools", "deferred_tools_delta": "Tools changed",
    "mcp_instructions_delta": "MCP server instructions", "agent_listing_delta": "List of agents",
    "environment": "Environment", "date": "Date", "edited_text_file": "A file was changed", "hook_success": "Hook output",
    "hook_additional_context": "Hook context", "plan_file_reference": "Plan", "invoked_skills": "Skills used",
    "task_status": "Background task status", "total_tokens_reminder": "Tokens left", "session_context": "Session context",
    "model": "Model", "plan_mode": "Plan mode", "plan_mode_exit": "Plan mode ended", "auto_mode": "Auto mode",
    "silent_turn_reminder": "Reminder", "batching_reminder_sent": "Reminder", "read_truncation_notice": "Read notice"}


def _attachment_label(a: dict) -> str:
    t = str(a.get("type") or "attachment")
    label = CC_ATTACHMENT_LABELS.get(t) or t.replace("_", " ").capitalize()
    where = a.get("displayPath") or a.get("filename") or a.get("planFilePath") or a.get("hookName") or \
        (a.get("path") if isinstance(a.get("path"), str) else "")
    return f"{label}: {where}" if isinstance(where, str) and where else label


def _cc_system(conv: "Conv", o: dict, ts: Optional[datetime]) -> None:
    """A system line of a Claude Code transcript, as a note (nothing but bookkeeping is left out)."""
    st = str(o.get("subtype") or "")
    if st == "compact_boundary":          # its metadata is bookkeeping (token counts, timings)
        said = o.get("content") if isinstance(o.get("content"), str) and o.get("content") else ""
        conv.divider((f"*{said}*: " if said else "") +
                     "*the conversation was shortened here to fit the model's memory.*")
        return
    if st == "turn_duration" and isinstance(o.get("durationMs"), (int, float)):
        sec = int(round(o["durationMs"] / 1000))
        n = o.get("messageCount")
        conv.note("Claude Code", ts, f"Worked for {sec // 60}m {sec % 60}s" + (f" · {n} messages" if n else ""))
        return
    content = o.get("content")
    text = content if isinstance(content, str) else (_dump(content, conv.pics) if content is not None else "")
    if st == "local_command":
        text = re.sub(r"</?local-command-std(out|err)>", "", text).strip()
    rest = {k: v for k, v in o.items() if k not in CC_BOOKKEEPING and k != "content"}
    extra = _dump(rest, conv.pics) if rest else None
    pics = conv.pics.take() if conv.pics else []
    if pics and not extra:
        text, pics = "\n\n".join([text] + pics), []
    conv.note("Claude Code", ts, CC_SYSTEM_LABELS.get(st) or (st.replace("_", " ").capitalize() or "Note"), text,
              extra, pics)


def _cc_user_parts(blocks: list, image: Callable, doc: Callable, without_reminders: bool = False,
                   pics: Optional[Pics] = None):
    """The parts of a message in your place: (parts to show, plain texts). Every kind of block is shown;
    pictures and documents are saved as files. System reminders are taken out (shown separately)."""
    parts: list = []
    plain: List[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            parts.append(_code(json.dumps(b, ensure_ascii=False), "json"))
            continue
        bt = b.get("type")
        if bt == "text":
            raw = b.get("text")
            txt = str(raw if raw is not None else "")
            if without_reminders:
                txt = _REMINDER_RE.sub("", txt)
            txt = txt.strip()
            if txt:
                parts.append(txt)
                plain.append(txt)
        else:
            src = image(b.get("source")) if bt == "image" else doc(b.get("source")) if bt == "document" else None
            if src and bt == "image":
                parts.append(_pic_md(src))
            elif src:
                parts.append(f"[{b.get('title') or 'document'}]({_path(src)})")
            else:
                parts += _dumped(b, pics)
    return parts, plain


def _cc_result(out, name: str, image: Callable, doc: Callable, pics: Optional[Pics] = None) -> Tuple[str, list]:
    """A tool result: (its text, other parts: pictures, documents, anything else in full)."""
    texts: List[str] = []
    extras: list = []
    if isinstance(out, list):
        for bb in out:
            if isinstance(bb, dict) and bb.get("type") == "text":
                texts.append(str(bb.get("text") if bb.get("text") is not None else ""))
                continue
            kind = bb.get("type") if isinstance(bb, dict) else None
            src = image(bb.get("source")) if kind == "image" else doc(bb.get("source")) if kind == "document" else None
            if src and kind == "image":
                extras.append(_pic_md(src, f"{name} image"))
            elif src:
                extras.append(f"[{bb.get('title') or name + ' document'}]({_path(src)})")
            elif isinstance(bb, dict) and bb.get("type") == "tool_reference" and set(bb) <= {"type", "tool_name"}:
                extras.append(f"Tool: `{bb.get('tool_name')}`")
            else:
                extras += _dumped(bb, pics)
    elif isinstance(out, str):
        texts.append(out)
    elif out is not None:
        texts.append(json.dumps(out, ensure_ascii=False, indent=1))
    return "\n".join(texts).strip("\n"), extras


def render_claude_code(w: Writer, rel: str, folder: str, md_rel_for: Callable[[str, Optional[datetime]], str],
                       app: str = "Claude Code") -> Optional[Session]:
    """One transcript -> one Markdown file and one web page. Returns None if it holds no conversation."""
    conv = Conv(posixpath.basename(rel))
    title = custom = summary = first_prompt = ""
    started = last = None
    cwd = version = branch = entrypoint = preview = sid = ""
    models: List[str] = []
    prompts = 0
    tools: Dict[str, str] = {}

    pics = conv.pics = Pics(lambda data, ext: w.image(folder, data, ext))

    def image(block_source) -> Optional[str]:
        data, ext = _image_bytes(block_source)
        return pics.file(data, ext) if data else None

    def doc(block_source) -> Optional[str]:            # a PDF or other document: saved as a file
        data, ext = _image_bytes(block_source)
        return w.image(folder, data, ext) if data else None

    shown: set = set()            # your messages shown so far (a message sent while Claude worked can come twice)
    for o in _json_lines(w.raw_path(rel), CC_KEEP, CC_SKIP):
        conv.line = o.get(LINE)
        t = o.get("type")
        if t == "ai-title":
            title = str(o.get("aiTitle") or title)
            continue
        if t == "custom-title":
            custom = str(o.get("customTitle") or o.get("title") or custom)
            continue
        if t == "summary":
            summary = summary or str(o.get("summary") or "")
            continue
        ts = parse_time(o.get("timestamp"))
        if ts:
            started = started or ts
            last = ts
        cwd = cwd or str(o.get("cwd") or "")
        version = str(o.get("version") or version)
        branch = branch or str(o.get("gitBranch") or "")
        entrypoint = entrypoint or str(o.get("entrypoint") or "")
        sid = sid or str(o.get("sessionId") or "")
        side = " (subagent)" if o.get("isSidechain") and "/subagents/" not in rel else ""
        if t == "system":
            _cc_system(conv, o, ts)
            continue
        if t == "attachment":
            a = o.get("attachment") if isinstance(o.get("attachment"), dict) else {}
            if a.get("type") == "queued_command":           # a message sent while Claude was working
                parts, plain = _cc_user_parts(a.get("prompt") if isinstance(a.get("prompt"), list)
                                              else [{"type": "text", "text": a.get("prompt")}], image, doc, pics=pics)
                key = "\n\n".join(plain).strip()
                if not parts or key in shown:
                    continue
                shown.add(key)
                sender = _cc_sender(a, key)
                if not sender:
                    prompts += 1
                    first_prompt = first_prompt or _one_line(key)
                    preview = preview or _plain(key)
                conv.you((sender or "You") + side, ts, parts, auto=bool(sender), sub="sent while Claude was working")
                rest = {k: v for k, v in a.items() if k not in ("type", "prompt", "origin", "timestamp", "source_uuid",
                                                                "delivery_id", "humanTurn", "commandMode")}
                if rest:
                    conv.context("Claude Code", ts, "Queued message details", _dump(rest, pics), pics=pics.take())
            else:
                conv.context("Claude Code", ts, _attachment_label(a), _dump({k: v for k, v in a.items() if k != "type"}, pics),
                             pics=pics.take())
            continue
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        content = msg.get("content")
        if t == "user":
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            if o.get("isMeta"):                               # a note Claude Code added, not typed by you
                parts, plain = _cc_user_parts(blocks, image, doc, pics=pics)
                pics.take()
                if parts:
                    conv.context("Claude Code", ts, "Note from Claude Code",
                                 "\n\n".join(plain) if len(plain) == len(parts) else _dump(blocks, pics),
                                 pics=pics.take())
                continue
            results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
            reminders = [m.group(1).strip() for b in blocks if isinstance(b, dict) and b.get("type") == "text"
                         for m in _REMINDER_RE.finditer(str(b.get("text") or ""))]
            parts, plain = _cc_user_parts([b for b in blocks if not (isinstance(b, dict) and b.get("type") == "tool_result")],
                                          image, doc, without_reminders=True, pics=pics)
            for b in results:
                name = tools.get(str(b.get("tool_use_id")), "tool")
                text, extras = _cc_result(b.get("content"), name, image, doc, pics)
                rest = {k: v for k, v in b.items() if k not in ("type", "tool_use_id", "content", "is_error")}
                if rest:
                    extras += _json_parts(rest, pics)
                if not text and not extras:
                    extras = ["*(no output)*"]
                conv.add("Claude" + side, ts, "result", "Error" if b.get("is_error") else "Result", text, extras)
            if parts:
                joined = "\n\n".join(plain)
                if o.get("isCompactSummary"):
                    conv.summary(_md(parts))
                    for r in reminders:
                        conv.context("Claude Code", ts, "System reminder", r)
                    continue
                m = re.match(r"\s*(?:<command-message>.*?</command-message>\s*)?<command-name>(.*?)</command-name>",
                             joined, re.S)
                sender = "" if m else _cc_sender(o, joined)
                if sender:
                    conv.you(sender + side, ts, parts, auto=True)
                else:
                    command = bool(m) or joined.lstrip().startswith(("<local-command-stdout>", "<local-command-stderr>"))
                    if m:                                 # a slash command: shown short, nothing else dropped
                        args = re.search(r"<command-args>(.*?)</command-args>", joined, re.S)
                        rest_text = re.sub(r"<command-(message|name|args)>.*?</command-\1>", "", joined, flags=re.S).strip()
                        parts = [f"`{m.group(1).strip()} {args.group(1).strip() if args else ''}`".replace(" `", "`")]
                        if rest_text:
                            parts.append(_code(rest_text))
                    elif command:
                        parts = [_code(re.sub(r"</?local-command-std(out|err)>", "", joined).strip())]
                    if command or joined not in shown:
                        prompts += 1
                        if not command:      # a slash command (/clear, /model) says nothing about the session
                            first_prompt = first_prompt or _one_line(joined)
                            preview = preview or _plain(joined)
                            shown.add(joined.strip())
                        conv.you("You" + side, ts, parts)
            for r in reminders:
                conv.context("Claude Code", ts, "System reminder", r)
        elif t == "assistant":
            if msg.get("model") and msg["model"] not in models and not str(msg["model"]).startswith("<"):
                models.append(str(msg["model"]))
            for b in content if isinstance(content, list) else [{"type": "text", "text": content or ""}]:
                who = "Claude" + side
                if not isinstance(b, dict):
                    conv.add(who, ts, "tool", "content", [_code(json.dumps(b, ensure_ascii=False), "json")])
                    continue
                kind = b.get("type")
                if kind == "text":
                    if str(b.get("text") or "").strip():
                        conv.add(who, ts, "text", str(b["text"]).strip())
                elif kind == "thinking":
                    if str(b.get("thinking") or "").strip():
                        conv.add(who, ts, "thinking", str(b["thinking"]).strip())
                elif kind == "redacted_thinking":
                    conv.add(who, ts, "redacted")
                elif kind == "tool_use":
                    name = str(b.get("name") or "tool")
                    tools[str(b.get("id"))] = name
                    conv.add(who, ts, "tool", name, _cc_tool_input(name, b.get("input"), pics))
                else:                                     # any other kind of block, in full
                    conv.add(who, ts, "tool", str(kind or "block"), _dumped(b, pics))
    if not prompts and not conv.has_ai():
        return None
    title = custom or title or summary or first_prompt or "Untitled session"
    md_rel = md_rel_for(title, started)
    text_body = _fix_paths(conv.markdown(), md_rel, rel)     # links to files, relative to this file
    deleted = w.deleted(rel)
    notes = [f"deleted at source on {deleted}"] if deleted else []
    surface = "Desktop app" if app == "Claude desktop" else claude_surface(entrypoint)
    head = _header(title, [
        ("App", app), ("Opened in", surface), ("Folder", f"`{cwd}`" if cwd else ""), ("Git branch", f"`{branch}`" if branch else ""),
        ("Started", _local(started)), ("Last message", _local(last)), ("Model", ", ".join(models)),
        ("Version", version), ("Raw transcript", f"[{posixpath.basename(rel)}]({_link(_rel(md_rel, rel))})"),
        ("Status", f"The app deleted this session on {deleted}; it is kept from an earlier backup." if deleted else ""),
    ])
    w.text(md_rel, "\n".join(head) + "\n" + SESSION_MARK + "\n\n" + text_body.strip() + "\n")
    s = Session(title, md_rel, rel, started, last, prompts, folder, cwd, notes, surface,
                "/subagents/" in rel or posixpath.basename(rel).startswith("agent-"), preview,
                ", ".join(models), version, sid, branch, _conv_pictures(conv))
    write_session_page(w, app, s, conv)
    return s


def _cc_project_name(enc: str) -> str:
    h = "-" + str(paths.home()).strip("/").replace("/", "-").replace(".", "-") + "-"
    name = enc[len(h):] if enc.startswith(h) else enc.lstrip("-")
    return safe_name(name or "home", limit=80)


def _session_file(started: Optional[datetime], title: str, tag: str) -> str:
    """The file name of a session's Markdown copy: "<date> <title> (<tag>).md"."""
    when = _local(started, "%Y-%m-%d %H-%M") or "undated"
    return safe_name(f"{when} {title[:60]} ({tag})", limit=110) + ".md"


def _session_link(base: str, s: Session) -> str:
    """A session as a link in its app's index.md."""
    return f"[{_cell(s.title)}]({_link(_rel(base + '/index.md', s.md))})"


def _render_session(res: Result, rel: str, render: Callable[[], Optional[Session]]) -> Optional[Session]:
    """One session's readable copy; an odd session is reported and must not stop the others."""
    try:
        return render()
    except DiskFull:
        raise
    except Exception as e:  # noqa: BLE001
        res.problem(f"could not make a readable copy of {rel}: {e}")
        return None


def claude_code_part(w: Writer, res: Result) -> Optional[str]:
    base = f"{ROOT}/claude-code"
    store = w.ctx.store
    rels = sorted(r for r in store.manifest if r.startswith("claude-code/projects/") and r.endswith(".jsonl"))
    if not rels and "claude-code/history.jsonl" not in store.manifest:
        return None
    sessions: List[Session] = []
    subagents: Dict[str, List[str]] = {}
    for rel in rels:
        parts = rel.split("/")
        if len(parts) < 4:
            continue
        folder = f"{base}/{_cc_project_name(parts[2])}"
        sub = "/subagents/" in rel or posixpath.basename(rel).startswith("agent-")

        def md_for(title, started, rel=rel, folder=folder, sub=sub):
            stem = posixpath.basename(rel)[:-6]
            name = _session_file(started, title, stem if sub else stem[-8:])
            return w.unique(f"{folder}/{'subagents/' if sub else ''}{name}")
        s = _render_session(res, rel, lambda: render_claude_code(w, rel, folder, md_for))
        if not s:
            continue
        if sub:
            parent = parts[3] if len(parts) > 5 else ""
            subagents.setdefault(f"{parts[2]}/{parent}", []).append(s.md)
            w.unlisted.append(("Claude Code", s))
        else:
            sessions.append(s)
    res.counts["Claude Code sessions as Markdown"] = len(sessions)
    w.listed += [("Claude Code", s) for s in sessions]
    hist = _guarded(res, "Claude Code prompt history", lambda: _claude_history(w, base))
    lines = [f"# Claude Code sessions", "",
             f"{len(sessions):,} sessions, newest first. Each file is one session; the raw transcript is linked "
             "at the top of each file.", ""]
    if hist:
        lines += [f"[Everything you typed, by date]({hist})", ""]
    by_project: Dict[str, List[Session]] = {}
    for s in sessions:
        by_project.setdefault(s.group, []).append(s)
    order = sorted(by_project, key=lambda g: max((x.last or x.started or _EPOCH)
                                                 for x in by_project[g]), reverse=True)
    for g in order:
        ss = sorted(by_project[g], key=lambda x: x.last or x.started or _EPOCH, reverse=True)
        where = next((x.where for x in ss if x.where), "")
        lines += [f"## {posixpath.basename(g)}", ""] + ([f"`{where}`", ""] if where else [])
        lines += ["| Last message | Session | Prompts | Note |", "|---|---|---:|---|"]
        for s in ss:
            lines.append(f"| {_local(s.last)} | {_session_link(base, s)} | {s.messages} | {'; '.join(s.notes)} |")
        lines.append("")
    n_sub = sum(len(v) for v in subagents.values())
    if n_sub:
        lines += [f"{n_sub:,} subagent transcripts are in the `subagents` folder of each project.", ""]
    w.text(f"{base}/index.md", "\n".join(lines))
    return f"{base}/index.md"


def _pasted(w: Writer, item) -> str:
    """The text of a paste in Claude Code's prompt history. A long paste is kept in Claude Code's paste
    cache (named by its hash) instead of the history; that file is in the backup if Claude Code still had it."""
    if isinstance(item, dict) and isinstance(item.get("content"), str):
        return item["content"]
    body = _dump(item)
    h = item.get("contentHash") if isinstance(item, dict) else None
    if not isinstance(h, str) or not re.fullmatch(r"[0-9A-Za-z]{6,128}", h):
        return body
    cached = f"claude-code/paste-cache/{h}.txt"
    if cached in w.ctx.store.manifest:
        return w.raw_path(cached).read_text(encoding="utf-8", errors="replace") + \
            f"\n\n(from Claude Code's paste cache: {cached} in this backup)"
    return body + "\n(the text was in Claude Code's paste cache, which no longer had it at the time of this backup)"


def _claude_history(w: Writer, base: str) -> Optional[str]:
    rel = "claude-code/history.jsonl"
    if rel not in w.ctx.store.manifest:
        return None
    rows = []
    with open(w.raw_path(rel), "rb") as f:
        for raw in f:
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            if isinstance(o, dict) and str(o.get("display") or "").strip():
                text = str(o["display"])
                pasted = o.get("pastedContents") if isinstance(o.get("pastedContents"), dict) else {}
                for key, item in pasted.items():          # what "[Pasted text #1 …]" stands for, in full
                    text += f"\n\n[Pasted {key}]\n{_pasted(w, item)}"
                rows.append((parse_time((o.get("timestamp") or 0) / 1000 if isinstance(o.get("timestamp"), (int, float))
                                        else o.get("timestamp")), str(o.get("project") or ""), text))
    rows.sort(key=lambda r: r[0] or _EPOCH, reverse=True)
    out = ["# Everything you typed into Claude Code", "", f"{len(rows):,} prompts, newest first.", ""]
    day = None
    for ts, project, text in rows:
        d = human_time(ts, with_time=False) or "undated"
        if d != day:
            out += [f"## {d}", ""]
            day = d
        out += [f"**{_local(ts, '%H:%M')}** · `{project}`", "", "\n".join("> " + x for x in text.split("\n")), ""]
    path = f"{base}/prompt-history.md"
    w.text(path, "\n".join(out))
    return "prompt-history.md"


def desktop_local_part(w: Writer, res: Result) -> Optional[str]:
    """Claude desktop's own local sessions (Cowork), when they are transcripts."""
    base = f"{ROOT}/claude-desktop"
    rels = sorted(r for r in w.ctx.store.manifest if r.endswith(".jsonl") and
                  (r.startswith("claude-desktop/local/") or r.startswith("claude-code/desktop-sessions/")))
    sessions = []
    for rel in rels:
        def md_for(title, started, rel=rel):
            return w.unique(f"{base}/{_session_file(started, title, posixpath.basename(rel)[-14:-6])}")
        s = _render_session(res, rel, lambda: render_claude_code(w, rel, base, md_for, app="Claude desktop"))
        if s:
            sessions.append(s)
    if not sessions:
        return None
    sessions.sort(key=lambda x: x.last or x.started or _EPOCH, reverse=True)
    lines = ["# Claude desktop: local sessions", "", "| Last message | Session | Prompts | Note |", "|---|---|---:|---|"]
    lines += [f"| {_local(s.last)} | {_session_link(base, s)} | {s.messages} | {'; '.join(s.notes)} |" for s in sessions]
    w.text(f"{base}/index.md", "\n".join(lines) + "\n")
    res.counts["Claude desktop local sessions as Markdown"] = len(sessions)
    w.listed += [("Claude desktop", s) for s in sessions]
    return f"{base}/index.md"


# ── Codex transcripts ────────────────────────────────────────────────────────

def _codex_user_text(txt: str) -> Optional[str]:
    """What to show for one part of a user message; None for context Codex added itself."""
    if txt.lstrip().startswith(CODEX_CONTEXT_PREFIXES):
        return None
    m = _WRAPPED_RE.match(txt)
    if not m:
        return txt
    tag, inner = m.group(1), m.group(2).strip()
    if tag in CODEX_CONTEXT_TAGS:
        return None
    if tag == "turn_aborted":
        return "*(This turn was stopped before it finished.)*" + (f"\n\n{inner}" if inner else "")
    if tag == "send_user_message_question_reply":
        return inner          # your answer to a question Codex asked
    return txt


def _codex_ctx_label(txt: str) -> str:
    m = _WRAPPED_RE.match(txt)
    if m:
        return m.group(1).replace("_", " ").capitalize()
    first = txt.strip().split("\n", 1)[0].strip("#<> ")
    return first[:60] or "Context"


def _codex_result(out, save_image: Callable, pics: Optional[Pics] = None) -> Tuple[str, list]:
    """A tool's output: (its text, every other part in full: pictures, metadata such as the exit code)."""
    def split(d: dict) -> Tuple[str, list]:
        for k in ("output", "content", "text"):
            if isinstance(d.get(k), str):
                rest = {x: v for x, v in d.items() if x != k}
                return d[k], (_json_parts(rest, pics) if rest else [])
        if pics is not None and any(_picture(v)[0] for v in d.values()):
            return "", _json_parts(d, pics)
        return json.dumps(d, ensure_ascii=False, indent=1), []
    if isinstance(out, str):
        try:
            j = json.loads(out)
        except ValueError:
            return out, []
        return split(j) if isinstance(j, dict) else (out, [])
    if isinstance(out, dict):
        return split(out)
    if isinstance(out, list):
        texts: List[str] = []
        extras: list = []
        for x in out:
            if isinstance(x, dict) and x.get("type") in ("input_text", "output_text", "text") and \
                    set(x) <= {"type", "text"}:
                texts.append(str(x.get("text") or ""))
            elif isinstance(x, dict) and x.get("type") in CODEX_IMAGE and (src := save_image(x.get("image_url"))):
                extras.append(_pic_md(src))
                rest = {k: v for k, v in x.items() if k not in ("type", "image_url")}
                if rest:                                  # e.g. the detail the picture was sent with
                    extras += _json_parts(rest, pics)
            else:
                extras += _dumped(x, pics)
        return "\n".join(texts), extras
    return json.dumps(out, ensure_ascii=False, indent=1), []


def _codex_call(args, pics: Optional[Pics] = None) -> list:
    """A function call's arguments: the command (if any) readable, then every other argument as JSON."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return [_code(args)]
    if isinstance(args, dict):
        key = "command" if "command" in args else "cmd" if "cmd" in args else None
        cmd = args.get(key) if key else None
        if isinstance(cmd, list) and all(isinstance(c, str) for c in cmd):
            cmd = " ".join(shlex.quote(c) for c in cmd)
        if isinstance(cmd, str):
            out: list = [f"*in `{args['workdir']}`*"] if isinstance(args.get("workdir"), str) and args["workdir"] else []
            out.append(_code(cmd, "bash"))
            rest = {k: v for k, v in args.items() if k != key and not (k == "workdir" and out and len(out) == 2)}
            if rest:
                out += _json_parts(rest, pics)
            return out
    return _json_parts(args, pics)


CODEX_IMAGE = ("input_image", "image")
CODEX_COMPACT_BOOKKEEPING = ("compaction_response_id", "latest_token_usage_record", "window_number", "window_id",
                             "first_window_id", "previous_window_id", "replacement_history_metadata")


def _codex_item_key(it) -> str:
    """The same item, whatever its id: to recognise copies of items already shown."""
    body = {k: v for k, v in it.items() if k not in ("id", "internal_chat_message_metadata_passthrough")} \
        if isinstance(it, dict) else it
    return "item:" + hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                                    .encode("utf-8", "replace")).hexdigest()


def _codex_kept(items: list, seen: set, save_image: Callable, pics: Optional[Pics] = None) -> str:
    """What Codex kept after compacting: mostly copies of earlier messages. Items already on this page
    (as messages, or kept by an earlier compaction) are counted, not repeated; every other item is
    shown in full, once, with its pictures as the image files they are saved in."""
    new: List[str] = []
    shown = encrypted = 0
    for it in items:
        if isinstance(it, dict) and it.get("type") == "compaction":
            encrypted += 1
            rest = {k: v for k, v in it.items() if k not in ("type", "id", "encrypted_content",
                                                             "internal_chat_message_metadata_passthrough")}
            key = _codex_item_key(rest)
            if rest and key not in seen:
                seen.add(key)
                new.append(_dump(rest, pics))
            continue
        if isinstance(it, dict) and it.get("type") == "message" and isinstance(it.get("content"), list):
            texts, images, view, other = [], [], [], False
            for c in it["content"]:
                kind = c.get("type") if isinstance(c, dict) else None
                if kind in ("input_text", "output_text", "text"):
                    texts.append(str(c.get("text") or "").strip())
                    view.append(c)
                    continue
                src = save_image(c.get("image_url") or c.get("source")) if kind in CODEX_IMAGE else None
                if src:
                    images.append("image:" + src)
                    view.append(c)                    # shown as the picture (see Pics)
                else:
                    other = True
                    view.append(c)
            if not other and all(t in seen for t in texts if t) and all(i in seen for i in images):
                shown += 1
                continue
            seen.update(t for t in texts if t)
            seen.update(images)
            new.append(_dump(dict(it, content=view), pics))
            continue
        key = _codex_item_key(it)
        if key in seen:
            shown += 1
            continue
        seen.add(key)
        new.append(_dump(it, pics))
    head = [f"Codex kept {len(items):,} items."]
    if shown:
        head.append(f"{shown:,} of them are already shown above on this page.")
    if encrypted:
        head.append(f"{encrypted:,} are encrypted by OpenAI and cannot be read (kept in the raw transcript).")
    if new:
        head.append(f"The other {len(new):,}, in full:")
    return " ".join(head) + "".join("\n\n" + x for x in new)


def _remember(v, seen: set) -> None:
    """Note every text of a value (and of JSON written as text) as shown on the page."""
    if isinstance(v, str):
        t = v.strip()
        if t:
            seen.add(t)
            if t[:1] in "{[":
                try:
                    _remember(json.loads(t), seen)
                except (ValueError, RecursionError):
                    pass
    elif isinstance(v, dict):
        for x in v.values():
            _remember(x, seen)
    elif isinstance(v, list):
        for x in v:
            _remember(x, seen)


def _ws(t: str) -> str:
    return " ".join(t.split())


def _texts(v, out: List[str]) -> None:
    """Every text of a value, including the texts of JSON written as text."""
    if isinstance(v, str):
        if v.strip():
            out.append(v)
            if v.strip()[:1] in "{[":
                try:
                    _texts(json.loads(v), out)
                except (ValueError, RecursionError):
                    pass
    elif isinstance(v, dict):
        for x in v.values():
            _texts(x, out)
    elif isinstance(v, list):
        for x in v:
            _texts(x, out)


class Shown:
    """What a turn of a Codex session already shows: the hash of every line of every text (fast to look
    up), and the text of the tool calls (to recognise a command run from inside a script)."""

    def __init__(self, seen: set, pics: Optional[Pics] = None):
        self.seen = seen
        self.pics = pics                   # the pictures the page shows
        self.lines: set = set()
        self.calls: List[str] = []

    def add(self, v, call: bool = False) -> None:
        found: List[str] = []
        _texts(v, found)
        for t in found:
            self.lines.update(hash(x.strip()) for x in t.splitlines() if x.strip())
            if call:
                self.calls.append(_ws(t))

    def has(self, t: str) -> bool:
        if t.strip() in self.seen:
            return True
        lines = [x.strip() for x in t.splitlines() if x.strip()]
        return bool(lines) and all(hash(x) in self.lines for x in lines)

    def has_call(self, t: str) -> bool:
        n = _ws(t)
        return len(n) >= 8 and any(n in c for c in self.calls)


def _new_only(v, shown: "Shown", key: str = "", pics_only: bool = False) -> object:
    """The parts of a value not already shown on the page (every line of a text already there, or a
    command already in a tool call), without bookkeeping (ids, times, numbers, flags). A picture is
    never bookkeeping: one the page does not show yet is kept wherever it is (`pics_only`: in a
    bookkeeping field, where nothing else is kept)."""
    if isinstance(v, str):
        if _picture(v)[0] is not None:
            return None if shown.pics is None or shown.pics.shown(v) else v
        return None if pics_only or not v.strip() or shown.has(v) else v
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            y = _new_only(x, shown, k, pics_only or k in CODEX_EVENT_BOOKKEEPING)
            if y is not None:
                out[k] = y
        if out and set(out) <= CODEX_EVENT_LABELS | {"type"}:
            return None                       # only labels are left: nothing new
        return out or None
    if isinstance(v, list):
        if key == "command" and not pics_only and v and all(isinstance(x, str) for x in v) and \
                (shown.has(v[-1]) or shown.has_call(v[-1])):
            return None                       # ["/bin/zsh", "-lc", "<a command already shown>"]
        out = [y for y in (_new_only(x, shown, "", pics_only) for x in v) if y is not None]
        return out or None
    return None                               # numbers and flags: bookkeeping


def _event_extra(p: dict, shown: "Shown"):
    """What one of Codex's own records adds to the page (None: nothing)."""
    item = p.get("item")
    if isinstance(item, dict) and item.get("type") == "CommandExecution":
        item = dict(item)
        out, std = item.get("aggregated_output"), item.get("stdout")
        if isinstance(out, str) and isinstance(std, str) and _ws(std) in _ws(out):
            item.pop("stdout")                # the same output twice
        p = dict(p, item=item)
    extra = _new_only(p, shown)
    if isinstance(extra, dict) and isinstance(extra.get("item"), dict):
        if set(extra["item"]) <= CODEX_EVENT_LABELS | {"type"}:
            return None
    return extra


def render_codex(w: Writer, rel: str, opener: Optional[Callable], titles: Dict[str, str],
                 md_rel_for: Callable[[str, Optional[datetime], str], str]) -> Optional[Session]:
    conv = Conv(posixpath.basename(rel))
    meta: dict = {}
    models: List[str] = []
    started = last = None
    first_prompt = preview = ""
    prompts = 0
    folder = f"{ROOT}/codex"
    path = w.raw_path(rel)
    last_turn = ""
    seen: set = set()                 # texts shown on this page (to tell what compacting and events add)
    shown = Shown(seen)               # what this turn (and the one before) shows
    before = Shown(seen)
    pending: list = []                # Codex's own records, decided at the end of their turn
    last_by_label: Dict[str, str] = {}
    pics = conv.pics = Pics(lambda data, ext: w.image(folder, data, ext))
    shown.pics = before.pics = pics

    def flush() -> None:
        both = Shown(seen, pics)
        both.lines, both.calls = shown.lines | before.lines, shown.calls + before.calls
        for ref, ts_, label, payload, line in pending:
            extra = _event_extra(payload, both)
            body = _dump(extra, pics) if extra else ""
            new_pics = pics.take()
            if body and last_by_label.get(label) != body:      # unchanged state is not repeated
                last_by_label[label] = body
                conv.fill(ref, "Codex", ts_, label, body, line, new_pics)
            else:
                conv.fill(ref)
        pending.clear()

    def save_image(src) -> Optional[str]:
        data, ext = _image_bytes(src)
        return pics.file(data, ext) if data else None
    for o in _json_lines(path, CODEX_KEEP, CODEX_SKIP, opener):
        conv.line = o.get(LINE)
        t = o.get("type")
        p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        ts = parse_time(o.get("timestamp"))
        if ts:
            started = started or ts
            last = ts
        if t == "session_meta":
            if not meta:
                meta = p
                bi = p.get("base_instructions")
                bi_text = bi.get("text") if isinstance(bi, dict) and set(bi) <= {"text"} else bi
                if isinstance(bi_text, str) and bi_text:
                    conv.context("Codex", ts, "Codex system instructions", bi_text)
                elif bi:
                    conv.context("Codex", ts, "Codex system instructions", _dump(bi, pics), pics=pics.take())
                rest = {k: v for k, v in p.items() if k not in CODEX_META_SHOWN}
                if rest:
                    conv.context("Codex", ts, "Session settings", _dump(rest, pics), pics=pics.take())
            else:                                   # a resumed or forked session repeats it
                conv.context("Codex", ts, "Session information", _dump(p, pics), pics=pics.take())
            continue
        if t == "turn_context":
            m = p.get("model")
            if m and m not in models:
                models.append(str(m))
            body = _dump({k: v for k, v in p.items() if k != "turn_id"}, pics)
            turn_pics = pics.take()
            if body != last_turn:                   # unchanged settings are not repeated
                conv.context("Codex", ts, "Settings for this turn" if not last_turn else "Settings changed", body,
                             pics=turn_pics)
                last_turn = body
            continue
        if t == "compacted":
            msg = p.get("message").strip() if isinstance(p.get("message"), str) else ""
            conv.divider("*The conversation was compacted here (shortened to fit the model's memory).*", msg)
            for key, label in (("replacement_history", "What Codex kept after compacting"),
                               ("guardian_history", "What the automatic reviewer kept")):
                if isinstance(p.get(key), list):
                    conv.context("Codex", ts, label, _codex_kept(p[key], seen, save_image, pics), reduced=True,
                                 pics=pics.take())
            rest = {k: v for k, v in p.items() if k not in ("message", "replacement_history", "guardian_history")
                    and k not in CODEX_COMPACT_BOOKKEEPING}
            if rest:
                conv.context("Codex", ts, "Compacting details", _dump(rest, pics), pics=pics.take())
            continue
        if t in ("event_msg", "world_state", "retained_context"):
            if t == "event_msg" and p.get("type") == "token_count":
                continue
            item = p.get("item") if isinstance(p.get("item"), dict) else None
            label = ("Codex record: " + str(p.get("type") or "event").replace("_", " ") +
                     (f" ({item.get('type')})" if item and item.get("type") else "")) if t == "event_msg" else \
                ("Codex workspace state" if t == "world_state" else "Retained context")
            pending.append((conv.placeholder(), ts, label, p, conv.line))
            if t == "event_msg" and p.get("type") == "task_started":
                flush()
                before.lines, before.calls = shown.lines, shown.calls
                shown.lines, shown.calls = set(), []
            continue
        kind = p.get("type")
        if t == "response_item":
            seen.add(_codex_item_key(p))
            shown.add(p, call=p.get("type") in ("function_call", "custom_tool_call", "local_shell_call"))
        if kind == "message":
            role = p.get("role")
            parts, plain, ctx = [], [], []
            for b in p.get("content") or []:
                if not isinstance(b, dict):
                    parts.append(_code(json.dumps(b, ensure_ascii=False), "json"))
                    continue
                if b.get("type") in ("input_text", "output_text", "text"):
                    txt = str(b.get("text") or "")
                    seen.add(txt.strip())
                    if role == "user":
                        shown_txt = _codex_user_text(txt)
                        if shown_txt is None:         # context Codex added by itself (folder, instructions)
                            ctx.append((_codex_ctx_label(txt), txt))
                            continue
                        txt = shown_txt
                    if txt.strip():
                        parts.append(txt.strip())
                        plain.append(txt.strip())
                    extra = {k: v for k, v in b.items() if k not in ("type", "text")}
                    if extra:
                        parts += _json_parts(extra, pics)
                elif b.get("type") in CODEX_IMAGE and (src := save_image(b.get("image_url") or b.get("source"))):
                    seen.add("image:" + src)
                    parts.append(_pic_md(src))
                    extra = {k: v for k, v in b.items() if k not in ("type", "image_url", "source")}
                    if extra:                         # e.g. the detail the picture was sent with
                        parts += _json_parts(extra, pics)
                else:
                    parts += _dumped(b, pics)
            if role == "user":
                if parts:
                    prompts += 1
                    first_prompt = first_prompt or _one_line(plain[0] if plain else "")
                    preview = preview or _plain("\n\n".join(plain))
                    conv.you("You", ts, parts)
                for label, txt in ctx:
                    conv.context("Codex", ts, label, txt)
            elif role == "assistant":
                for x in parts:
                    if isinstance(x, str):
                        conv.add("Codex", ts, "text", x)
                    else:
                        conv.add("Codex", ts, "tool", "content", [x])
            else:                                     # developer / system: instructions Codex sent the model
                conv.context("Codex", ts, "Instructions from Codex" if role == "developer" else f"Message ({role})",
                             "\n\n".join(plain) if len(plain) == len(parts) else _dump(p.get("content"), pics),
                             pics=pics.take())
            continue
        if kind == "reasoning":
            texts = [str(x.get("text") or "") for x in (p.get("summary") or []) + (p.get("content") or [])
                     if isinstance(x, dict) and str(x.get("text") or "").strip()]
            if texts:
                conv.add("Codex", ts, "thinking", "\n\n".join(texts).strip(), "Reasoning (summary)")
            elif p.get("encrypted_content"):
                conv.add("Codex", ts, "redacted", "Reasoning (encrypted by OpenAI; not readable)")
        elif kind == "function_call":
            _remember(p.get("arguments"), seen)
            ns = f"{p['namespace']} · " if isinstance(p.get("namespace"), str) and p["namespace"] else ""
            conv.add("Codex", ts, "tool", ns + str(p.get("name") or "tool"),
                     _codex_call(p.get("arguments"), pics))
        elif kind == "custom_tool_call":
            name = str(p.get("name") or "tool")
            ns = f"{p['namespace']} · " if isinstance(p.get("namespace"), str) and p["namespace"] else ""
            inp = p.get("input")
            _remember(inp, seen)
            conv.add("Codex", ts, "tool", ns + name, [_code(inp, "diff" if name == "apply_patch" else "")]
                     if isinstance(inp, str) else _dumped(inp, pics))
        elif kind == "local_shell_call":
            conv.add("Codex", ts, "tool", "shell", _codex_call(p.get("action") or {}))
        elif kind in ("function_call_output", "custom_tool_call_output"):
            text, extras = _codex_result(p.get("output"), save_image, pics)
            if text.strip():
                seen.add(text.strip())
            _remember(p.get("output"), seen)
            if not text.strip() and not extras:
                extras = ["*(no output)*"]
            conv.add("Codex", ts, "result", "Result", text.strip("\n"), extras)
        elif kind == "web_search_call":
            _remember(p.get("action"), seen)
            a = p.get("action") if isinstance(p.get("action"), dict) else {}
            q = a.get("query") or a.get("url") or ""
            rest = {k: v for k, v in a.items() if not (k in ("query", "url") and v == q)}
            conv.add("Codex", ts, "tool", "web search", ([f"“{q}”"] if q else []) +
                     (_json_parts(rest, pics) if rest else []))
        elif kind == "tool_search_call":
            conv.add("Codex", ts, "tool", "tool search", _dumped(p.get("arguments"), pics))
        elif kind == "tool_search_output":
            conv.add("Codex", ts, "result", "Result", "", _dumped(p.get("tools"), pics))
        elif kind == "agent_message":
            parts = []
            for x in p.get("content") or []:
                if isinstance(x, dict) and isinstance(x.get("text"), str):
                    parts.append(str(x.get("text")).strip())
                else:
                    parts += _dumped(x, pics)
            conv.you(f"Message from {p.get('author') or 'an agent'} to {p.get('recipient') or 'an agent'}", ts,
                     parts or ["*(empty)*"], auto=True)
        elif kind == "compaction":
            conv.add("Codex", ts, "redacted", "Compacted history (encrypted by OpenAI; not readable)")
        elif kind == "image_generation_call":
            data, ext = _image_bytes({"data": p.get("result"), "media_type": "image/png"})
            parts = [_code(p["revised_prompt"], "text")] if isinstance(p.get("revised_prompt"), str) else []
            if data:
                parts.append(_pic_md(pics.file(data, ext), "generated image"))
            rest = {k: v for k, v in p.items() if k not in ("type", "id", "status", "result", "revised_prompt")}
            if rest:
                parts += _dumped(rest, pics)
            conv.add("Codex", ts, "tool", "image generation",
                     parts or _dumped({k: v for k, v in p.items() if k != "result"}, pics))
        else:                                           # any other kind of item, in full
            conv.add("Codex", ts, "tool", str(kind or "item"), _dumped(p, pics))
    flush()
    if not prompts and not conv.has_ai():
        return None
    sid = str(meta.get("id") or meta.get("session_id") or "")
    title = titles.get(sid) or first_prompt or "Untitled session"
    md_rel = md_rel_for(title, started, sid or posixpath.basename(rel))
    text_body = _fix_paths(conv.markdown(), md_rel, rel)     # links to files, relative to this file
    deleted = w.deleted(rel) or w.deleted(rel + ".zst") or w.deleted(rel[:-4] if rel.endswith(".zst") else rel)
    notes = []
    surface = codex_surface(meta)
    kind = str(meta.get("thread_source") or "")
    helper = bool(meta.get("parent_thread_id")) or kind in ("subagent", "guardian_review") or \
        meta.get("source") == "subagent"
    if "/archived_sessions/" in rel:
        notes.append("archived")
    if helper:
        notes.append("automatic review" if kind == "guardian_review" else "subagent")
    if deleted:
        notes.append(f"deleted at source on {deleted}")
    git = meta.get("git") if isinstance(meta.get("git"), dict) else {}
    head = _header(title, [
        ("App", "Codex"), ("Opened in", surface or str(meta.get("originator") or "")),
        ("Folder", f"`{meta['cwd']}`" if meta.get("cwd") else ""),
        ("Git branch", f"`{git['branch']}`" if git.get("branch") else ""),
        ("Started", _local(started)), ("Last message", _local(last)), ("Model", ", ".join(models)),
        ("Codex version", str(meta.get("cli_version") or "")), ("Session", f"`{sid}`" if sid else ""),
        ("Raw transcript", f"[{posixpath.basename(rel)}]({_link(_rel(md_rel, rel))})"),
        ("Status", "; ".join(notes)),
    ])
    note = [f"*{CODEX_NOTE}*", ""]
    w.text(md_rel, "\n".join(head + note) + "\n" + SESSION_MARK + "\n\n" + text_body.strip() + "\n")
    s = Session(title, md_rel, rel, started, last, prompts, human_month(started) or "undated",
                str(meta.get("cwd") or ""), notes, surface, helper, preview, ", ".join(models),
                str(meta.get("cli_version") or ""), sid, str(git.get("branch") or ""), _conv_pictures(conv))
    write_session_page(w, "Codex", s, conv)
    return s


def _codex_titles(w: Writer) -> Dict[str, str]:
    titles: Dict[str, str] = {}
    rel = "codex/session_index.jsonl"
    if rel in w.ctx.store.manifest:
        try:
            with open(w.raw_path(rel), "rb") as f:
                for raw in f:
                    try:
                        o = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(o, dict) and o.get("id") and o.get("thread_name"):
                        titles[str(o["id"])] = str(o["thread_name"])
        except OSError:
            pass
    return titles


def codex_part(w: Writer, res: Result) -> Optional[str]:
    base = f"{ROOT}/codex"
    store = w.ctx.store
    rels = sorted(r for r in store.manifest if r.startswith(("codex/sessions/", "codex/archived_sessions/"))
                  and re.search(r"/rollout-[^/]+\.jsonl(\.zst)?$", r))
    plain = {r for r in rels if r.endswith(".jsonl")}
    todo = [r for r in rels if r.endswith(".jsonl") or (r.endswith(".zst") and r[:-4] not in plain)]
    titles = _codex_titles(w)
    sessions: List[Session] = []
    skipped_zst = 0
    for rel in todo:
        opener = None
        if rel.endswith(".zst"):
            if not w.ctx.zstd.available:
                skipped_zst += 1
                continue
            opener = (lambda p=w.raw_path(rel): w.ctx.zstd.open(p))

        def md_for(title, started, sid):
            month = _local(started, "%Y-%m") or "undated"
            return w.unique(f"{base}/{month}/{_session_file(started, title, sid[-8:])}")
        s = _render_session(res, rel, lambda: render_codex(w, rel, opener, titles, md_for))
        if s:
            sessions.append(s)
    if skipped_zst:
        res.notes.append(f"{skipped_zst:,} compressed Codex sessions have no readable copy (zstd is missing: "
                         "brew install zstd).")
    if not sessions and not any(r.startswith("codex/") for r in store.manifest):
        return None
    res.counts["Codex sessions as Markdown"] = len(sessions)
    w.listed += [("Codex", s) for s in sessions]
    hist = _guarded(res, "Codex prompt history", lambda: _codex_history(w, base))
    dbs = _guarded(res, "Codex databases", lambda: _codex_databases(w, base, res))
    sessions.sort(key=lambda x: x.started or _EPOCH, reverse=True)
    lines = ["# Codex sessions", "", f"{len(sessions):,} sessions, newest first. Each file is one session; the raw "
             "transcript is linked at the top of each file.", ""]
    if hist:
        lines += [f"[Everything you typed, by date]({hist})  "]
    if dbs:
        lines += [f"Codex's own databases (thread list, goals, memories) as JSON: [databases]({dbs})"]
    lines.append("")
    month = None
    for s in sessions:
        if s.group != month:
            month = s.group
            lines += ["", f"## {month}", "", "| Started | Session | Folder | Prompts | Note |", "|---|---|---|---:|---|"]
        lines.append(f"| {_local(s.started)} | {_session_link(base, s)} | "
                     f"{_cell(posixpath.basename(s.where))} | {s.messages} | {'; '.join(s.notes)} |")
    w.text(f"{base}/index.md", "\n".join(lines) + "\n")
    return f"{base}/index.md"


def _codex_history(w: Writer, base: str) -> Optional[str]:
    rel = "codex/history.jsonl"
    if rel not in w.ctx.store.manifest:
        return None
    rows = []
    with open(w.raw_path(rel), "rb") as f:
        for raw in f:
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            if isinstance(o, dict) and str(o.get("text") or "").strip():
                rows.append((parse_time(o.get("ts")), str(o["text"])))
    rows.sort(key=lambda r: r[0] or _EPOCH, reverse=True)
    out = ["# Everything you typed into Codex", "", f"{len(rows):,} prompts, newest first.", ""]
    day = None
    for ts, text in rows:
        d = human_time(ts, with_time=False) or "undated"
        if d != day:
            out += [f"## {d}", ""]
            day = d
        out += [f"**{_local(ts, '%H:%M')}**", "", "\n".join("> " + x for x in text.split("\n")), ""]
    w.text(f"{base}/prompt-history.md", "\n".join(out))
    return "prompt-history.md"


def _sql_value(v):
    if isinstance(v, bytes):
        return {"base64": base64.b64encode(v).decode()}
    return v


def _codex_databases(w: Writer, base: str, res: Result) -> Optional[str]:
    dbs = sorted(r for r in w.ctx.store.manifest if r.startswith("codex/databases/")
                 and not r.endswith(("-wal", "-shm", "-journal")))
    if not dbs:
        return None
    index = ["# Codex databases as JSON", "",
             "Codex keeps these as SQLite files (copied as they are into `codex/databases/`). Here every table is "
             "also saved as a JSON file: a list of rows, one object per row.", ""]
    for rel in dbs:
        name = posixpath.basename(rel)
        tmp = Path(tempfile.mkdtemp(prefix="pahest-readable-"))
        try:
            copy = tmp / name
            src = w.raw_path(rel)
            clone_or_copy(src, copy)
            wal = Path(str(src) + "-wal")
            if wal.exists():
                clone_or_copy(wal, Path(str(copy) + "-wal"))
            guard.check_write(copy, "open database")
            con = sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                tables = [r[0] for r in con.execute(
                    "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
                index += [f"## {name}", "", "| Table | Rows |", "|---|---:|"]
                for t in tables:
                    cur = con.execute(f'select * from "{t}"')
                    cols = [d[0] for d in cur.description]
                    rows = [{c: _sql_value(v) for c, v in zip(cols, row)} for row in cur]
                    if rows:
                        out_rel = f"{base}/databases/{safe_name(name)}/{safe_name(t)}.json"
                        w.data(out_rel, jdump(rows))
                        index.append(f"| [{_cell(t)}]({_link(_rel(base + '/databases/index.md', out_rel))}) | "
                                     f"{len(rows):,} |")
                    else:
                        index.append(f"| {_cell(t)} | 0 |")
                index.append("")
            finally:
                con.close()
        except sqlite3.Error as e:
            res.problem(f"could not read the database {rel}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    w.text(f"{base}/databases/index.md", "\n".join(index) + "\n")
    return "databases/index.md"


# ── the whole step ───────────────────────────────────────────────────────────

def _guarded(res: Result, what: str, fn: Callable[[], Optional[str]]) -> Optional[str]:
    try:
        return fn()
    except DiskFull:
        raise
    except Exception as e:  # noqa: BLE001 - the sessions and indexes are still written
        res.problem(f"{what}: readable copy could not be made: {type(e).__name__}: {e}")
        return None


def run(ctx: Ctx, stamp: str) -> Result:
    t0 = time.time()
    res = Result(ID, "readable", "Readable copies", "chats as Markdown, pictures as files", ROOT,
                 item_label="lists")
    w = Writer(ctx, res)
    links: List[Tuple[str, str]] = []
    for title, fn in (("Claude Code sessions", claude_code_part), ("Claude desktop local sessions", desktop_local_part),
                      ("Codex sessions", codex_part)):
        ctx.log.line(f"  {ctx.log.DOT} {title}…")
        try:
            idx = fn(w, res)
        except DiskFull:
            raise
        except Exception as e:  # noqa: BLE001 - one broken part must not stop the others
            res.problem(f"{title}: readable copies could not be made: {type(e).__name__}: {e}")
            continue
        if idx:
            links.append((title, idx))
    res.counts["images saved as files"] = len(w.images)
    _readme(w, stamp, links)
    ctx.log.line(f"  {ctx.log.DOT} Web pages (index.html)…")
    _guarded(res, "web pages", lambda: _web(w, stamp, res))
    res.items = len(links)
    res.seconds = time.time() - t0
    return res


SECTION_OF = [("readable/claude-code/", "Claude Code", "readable/claude-code/index.html"),
              ("readable/codex/", "Codex", "readable/codex/index.html"),
              ("readable/claude-desktop/", "Claude desktop", "readable/claude-desktop/index.html")]


def _section(page_rel: str) -> List[Tuple[str, str]]:
    for prefix, name, idx in SECTION_OF:
        if page_rel.startswith(prefix):
            return [(name, idx if page_rel != idx else "")]
    return []


def write_session_page(w: Writer, app: str, s: "Session", conv: Conv) -> None:
    """The web page of one session, from the HTML templates (htmlview.session_page)."""
    E = htmlview.esc
    store = w.ctx.store
    page_rel = s.md[:-3] + ".html"
    link = htmlview.make_linker(s.md, page_rel, {}, w.exists)

    def fix(md: str) -> str:              # links to files (pictures, the raw transcript), relative to this page
        return _fix_paths(md, s.md, s.raw)
    body = htmlview.conversation_html(conv.blocks, link, fix)          # everything, nothing shortened
    origin = _origin_path(store, s.raw)
    rows = [("App", E(app + (f" · {s.surface}" if s.surface else ""))),
            ("Folder", f"<code>{E(s.where)}</code>" if s.where else ""),
            ("Git branch", f"<code>{E(s.branch)}</code>" if s.branch else ""),
            ("Started", htmlview.when_html(_iso(s.started))),
            ("Last message", htmlview.when_html(_iso(s.last))),
            ("Your messages", str(s.messages)), ("Model", E(s.model)), ("Version", E(s.version)),
            ("Session", f"<code>{E(s.sid)}</code>" if s.sid else ""),
            ("Original file", f"<code>{E(origin)}</code>" if origin else ""),
            ("In this backup", f'<a href="{E(htmlview.href(page_rel, s.raw))}">{E(posixpath.basename(s.raw))}</a> '
                               "(raw transcript, every detail)"),
            ("Status", E("; ".join(s.notes)))]
    app_list = APP_LISTS.get(app, "index.html")
    w.text(page_rel, htmlview.session_page(s.title, rows, CODEX_NOTE if app == "Codex" else "", body, page_rel,
                                           [(app, app_list)], app_list))


APP_LISTS = {"Claude Code": "readable/claude-code/index.html", "Codex": "readable/codex/index.html",
             "Claude desktop": "readable/claude-desktop/index.html"}
CODEX_NOTE = ("Codex keeps the model's private reasoning encrypted with OpenAI's key, so nobody but OpenAI can read it; "
              "only reasoning summaries are shown when Codex saved them.")


def _origin_path(store, raw_rel: str) -> str:
    """Where the session's transcript was on this Mac (for a plain copy: its compressed original)."""
    rec = store.origins.get(raw_rel) or {}
    if rec.get("kind") == "derived":
        rec = store.origins.get(rec.get("from") or "", {})
    p = rec.get("path") or ""
    home = str(paths.home())
    return "~" + p[len(home):] if p.startswith(home + "/") else p


def _web(w: Writer, stamp: str, res: Result) -> None:
    """The web pages, all made with one template (htmlview.layout): index.html, one list page per app
    with the same filters, a page per session with previous / next, and a page per other Markdown file."""
    store = w.ctx.store
    E = htmlview.esc
    mds = sorted(r for r in store.manifest if htmlview.html_path(r))
    pages = {r: htmlview.html_path(r) for r in mds}
    known = set(store.manifest) | set(pages.values()) | {
        "index.html", "report.html", "backup.json", "backup.log", "checksums.sha256", "deleted-at-source.txt",
        "source-manifest.jsonl"}
    folders = {r.rsplit("/", i)[0] for r in known for i in range(1, r.count("/") + 1)}

    def exists(rel: str) -> bool:
        return rel in known or rel in folders

    # one list of every session, shared by all pages (readable/items.js)
    items: List[list] = []
    session_of: Dict[str, Tuple[str, Session]] = {}
    for app, s in w.listed:
        where = posixpath.basename(s.where.rstrip("/")) if s.where else ""
        pv = s.preview
        if pv.rstrip("…").strip().lower() == s.title.rstrip("…").strip().lower():
            pv = ""
        items.append([s.title, _iso(s.last or s.started), app, pages.get(s.md, s.md), "; ".join(s.notes), where,
                      s.surface, 1 if s.helper else 0, pv])
        session_of[s.md] = (app, s)
    # every picture of every session, once, for the pictures page (readable/images.js). Its session is an
    # index in items.js, or (for a page not in the lists, such as a Claude Code subagent) a row like them.
    pics: Dict[str, list] = {}
    sessions = [(app, s, i) for i, (app, s) in enumerate(w.listed)] + [
        (app, s, [s.title, _iso(s.last or s.started), app, pages.get(s.md, s.md), "subagent",
                  posixpath.basename(s.where.rstrip("/")) if s.where else "", s.surface, 1, ""])
        for app, s in w.unlisted]
    for app, s, ref in sessions:
        for rel, kind, ts in s.pictures:
            if kind == "you" and s.helper:
                kind = "tool"                   # a subagent's task comes from the main agent, not from you
            when = _iso(ts or s.started)
            name = posixpath.basename(rel)      # the same picture saved in two folders is listed once
            cur = pics.get(name)
            if cur is None or (_PIC_RANK[kind], when or "~") < (_PIC_RANK[cur[1]], cur[2] or "~"):
                pics[name] = [rel, kind, when, ref]
    footer_links = ([("Pictures", htmlview.PICS_PAGE)] if pics else []) + [(label, pages[md]) for label, md in (
        ("Typed into Claude Code", "readable/claude-code/prompt-history.md"),
        ("Typed into Codex", "readable/codex/prompt-history.md"),
        ("Codex databases", "readable/codex/databases/index.md")) if md in pages]
    about = f"Backup of {htmlview._shown_stamp(stamp)}"
    w.text(htmlview.ITEMS_JS, htmlview.items_js(items, footer_links, about))
    w.text(f"{htmlview.ASSETS}/style.css", htmlview.style_css())
    w.text(f"{htmlview.ASSETS}/app.js", htmlview.app_js())

    made = 0
    for md_rel in mds:
        page_rel = pages[md_rel]
        try:
            if md_rel in session_of or page_rel in store.manifest:
                continue                           # a session page, made when the session was read
            md = store.path(md_rel).read_text(encoding="utf-8", errors="replace")
            link = htmlview.make_linker(md_rel, page_rel, pages, exists)
            if page_rel in APP_LISTS.values():
                continue                           # a list page, made below from the same template
            else:
                body = htmlview.md_to_html(md, link)
                title = htmlview.title_of(md, posixpath.basename(md_rel)[:-3])
                w.text(page_rel, htmlview.doc_page(title, body, page_rel, _section(page_rel)))
            made += 1
        except DiskFull:
            raise
        except Exception as e:  # noqa: BLE001 - the other pages are still made
            res.problem(f"web page for {md_rel} could not be made: {type(e).__name__}: {e}")
    res.counts["web pages"] = sum(1 for r in store.manifest if r.startswith("readable/") and r.endswith(".html"))

    more = []
    if pics:
        rows = sorted(pics.values(), key=lambda p: p[2] or "", reverse=True)
        w.text(htmlview.PICS_JS, htmlview.pics_js(rows))
        kinds = [(k, label, sum(1 for p in rows if p[1] == k)) for k, label in PIC_KINDS]
        w.text(htmlview.PICS_PAGE, htmlview.images_page(f"{len(rows):,} pictures from your sessions, each shown once",
                                                        kinds))
        more = [(f"Pictures ({len(rows):,})", htmlview.PICS_PAGE)]
        res.counts["pictures on the pictures page"] = len(rows)
    apps = [a for a in APP_LISTS if any(it[2] == a for it in items)]
    for app in apps:
        n = sum(1 for it in items if it[2] == app)
        w.text(APP_LISTS[app], htmlview.list_page(f"{app} sessions", f"{n:,} sessions", APP_LISTS[app],
                                                  [(app, "")], items, app=app, more=more))
    w.text("index.html", htmlview.list_page("Your AI chats", "Works offline, without the apps or an account",
                                            "index.html", [], items, more=more))


def _readme(w: Writer, stamp: str, links: List[Tuple[str, str]]) -> None:
    lines = [f"# Backup of your AI chats: {stamp}", "",
             f"Made by [Pahest]({HOME_URL}) {__version__} (open source, MIT license; Pahest is Armenian for "
             "“reserve”). Everything in this folder is an ordinary file. You need "
             "none of the apps, and no account, to read it.", "",
             "**Open `index.html` in a web browser** to see all your chats, search them, and read them as web pages.",
             "", "## Start here", ""]
    for title, rel in links:
        lines.append(f"- {title}: [{rel}]({_link(rel)})")
    lines += ["- What this backup holds, and how it was checked: [report.html](report.html)", "",
              "## What the folders hold", "",
              "- `readable/`: every local session as a Markdown file (`.md`, opens in any text editor) and a web "
              "page, pictures as image files (all of them on one page: `readable/images.html`), and the Codex "
              "databases as JSON. Nothing is shortened there.",
              "- `claude-code/`, `codex/`: the apps' own files, exactly as found. The `.jsonl` files are the raw "
              "transcripts with every detail. Codex's compressed `.jsonl.zst` files also have a plain `.jsonl` copy.",
              "- `claude-desktop/local/`: what the Claude desktop app keeps on this Mac (Cowork files, the Cowork "
              "session disk image, MCP settings). Your claude.ai and chatgpt.com chats are not on this Mac; keep "
              "them with each app's own export (Settings → Privacy / Data controls → Export data).",
              "- `checksums.sha256`: a fingerprint of every file. Check the backup with "
              "`shasum -a 256 -c checksums.sha256`.",
              "- `deleted-at-source.txt` (if present): items the apps deleted that this backup still keeps.", "",
              "## What nobody but the company can read", "",
              "- The model's private reasoning in Codex is encrypted with OpenAI's key, and Claude's reasoning is "
              "sometimes encrypted with Anthropic's key. These parts are saved, but cannot be made readable.", ""]
    w.text("README.md", "\n".join(lines))
