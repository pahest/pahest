"""Turn raw chat JSON into readable Markdown, and rebuild artifacts and canvas documents.

The raw JSON is always saved too; this is the human-readable copy.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

CLAUDE_ROOT = "00000000-0000-4000-8000-000000000000"

LANG_EXT = {
    "python": "py", "py": "py", "javascript": "js", "js": "js", "typescript": "ts", "ts": "ts",
    "tsx": "tsx", "jsx": "jsx", "html": "html", "css": "css", "java": "java", "c": "c", "cpp": "cpp",
    "c++": "cpp", "csharp": "cs", "c#": "cs", "go": "go", "rust": "rs", "ruby": "rb", "php": "php",
    "swift": "swift", "kotlin": "kt", "bash": "sh", "shell": "sh", "sh": "sh", "zsh": "sh",
    "sql": "sql", "json": "json", "yaml": "yml", "yml": "yml", "markdown": "md", "md": "md",
    "xml": "xml", "r": "r", "scala": "scala", "dart": "dart", "lua": "lua", "perl": "pl",
    "powershell": "ps1", "toml": "toml", "react": "jsx", "vue": "vue", "svelte": "svelte",
}
TYPE_EXT = {
    "text/markdown": "md", "text/html": "html", "image/svg+xml": "svg", "text/plain": "txt",
    "application/vnd.ant.mermaid": "mmd", "application/vnd.ant.react": "jsx", "text/csv": "csv",
}


def jdump(obj) -> bytes:
    """Pretty JSON as UTF-8. Text with lone surrogates (invalid UTF-16 the servers sometimes
    send) is kept exactly by writing \\u escapes instead of failing."""
    try:
        return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    except UnicodeEncodeError:
        return (json.dumps(obj, ensure_ascii=True, indent=2) + "\n").encode("ascii")


def utf8(text: str) -> bytes:
    """Readable text as UTF-8; characters that cannot be encoded become '?'."""
    return text.encode("utf-8", "replace")


def safe_name(name: str, default: str = "file", limit: int = 120) -> str:
    """A file name that is safe on macOS/Linux/Windows and keeps the extension."""
    name = unicodedata.normalize("NFC", str(name or "")).strip()
    name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    name = re.sub(r'[\x00-\x1f<>"|?*]', "_", name).strip(" .")
    if not name:
        name = default
    if len(name) > limit:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: limit - len(ext) - 1] + "." + ext
        else:
            name = name[:limit]
    return name


_FRACTION = re.compile(r"\.(\d+)")


def parse_time(v) -> Optional[datetime]:
    """Unix seconds or an ISO date ("2026-11-08T10:00:00.12Z"). Works on Python 3.9, whose
    fromisoformat() accepts neither "Z" nor fractions that are not 3 or 6 digits long."""
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        text = str(v).strip().replace("Z", "+00:00")
        text = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError, TypeError):
        return None


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
_SHOWN_RE = re.compile(r"^\s*(\d{4}) (" + "|".join(MONTHS) + r")(?: (\d{1,2}))?(?:, (\d{1,2}):(\d{2}))?\s*$")
_ISO_SHOWN_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2})[:-](\d{2}))?")


def human_time(dt: Optional[datetime], with_time: bool = True) -> str:
    """How every date is shown: "2026 October 24, 10:00" in this Mac's time zone. Month names
    are fixed English words, whatever the computer's language settings."""
    if dt is None:
        return ""
    try:
        dt = dt.astimezone()
    except (OverflowError, ValueError, OSError):
        return ""
    day = f"{dt.year} {MONTHS[dt.month - 1]} {dt.day}"
    return f"{day}, {dt:%H:%M}" if with_time else day


def human_month(dt: Optional[datetime]) -> str:
    try:
        dt = dt.astimezone() if dt else None
    except (OverflowError, ValueError, OSError):
        dt = None
    return f"{dt.year} {MONTHS[dt.month - 1]}" if dt else ""


def parse_shown(text: str) -> Optional[datetime]:
    """Read back a date as this backup shows it ("2026 October 24, 10:00", or 2026-10-24 10:00).
    Gives a local time without a zone, used for sorting and for the date filters."""
    m = _SHOWN_RE.match(text or "")
    try:
        if m:
            return datetime(int(m.group(1)), MONTHS.index(m.group(2)) + 1, int(m.group(3) or 1),
                            int(m.group(4) or 0), int(m.group(5) or 0))
        m = _ISO_SHOWN_RE.match(text or "")
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0),
                            int(m.group(5) or 0))
    except ValueError:
        return None
    return None


def _fmt_time(v) -> str:
    dt = parse_time(v)
    if dt is None:
        return "" if v in (None, "") else str(v)
    return human_time(dt)


def _md_escape_title(t: str) -> str:
    return (t or "Untitled").replace("\n", " ").strip() or "Untitled"


def fence(text: str, lang: str = "") -> str:
    ticks = "```"
    while ticks in text:
        ticks += "`"
    return f"{ticks}{lang}\n{text.rstrip()}\n{ticks}"


# ── Claude (claude.ai) ───────────────────────────────────────────────────────

def claude_path(conv: dict) -> List[dict]:
    msgs = {m.get("uuid"): m for m in conv.get("chat_messages") or [] if m.get("uuid")}
    leaf = conv.get("current_leaf_message_uuid")
    if leaf not in msgs:
        ordered = sorted(msgs.values(), key=lambda m: (m.get("index", 0), m.get("created_at", "")))
        leaf = ordered[-1]["uuid"] if ordered else None
    path, seen = [], set()
    while leaf and leaf in msgs and leaf not in seen:
        seen.add(leaf)
        path.append(msgs[leaf])
        leaf = msgs[leaf].get("parent_message_uuid")
    return list(reversed(path))


def claude_branch_count(conv: dict) -> int:
    msgs = conv.get("chat_messages") or []
    parents = {m.get("parent_message_uuid") for m in msgs}
    leaves = [m for m in msgs if m.get("uuid") not in parents]
    return len(leaves)


def _artifact_ext(inp: dict) -> str:
    t = str(inp.get("type") or "")
    if t == "application/vnd.ant.code":
        return LANG_EXT.get(str(inp.get("language") or "").lower(), "txt")
    return TYPE_EXT.get(t, "txt")


def claude_artifacts(conv: dict) -> Tuple[Dict[str, dict], Dict[Tuple[str, int], Tuple[str, int]], List[str]]:
    """Rebuild every version of every artifact and created file.

    Returns (artifacts, refs, problems):
      artifacts: key -> {"title", "ext", "kind", "versions": [text, ...]}
      refs: (message uuid, content block index) -> (key, version number)
    """
    arts: Dict[str, dict] = {}
    refs: Dict[Tuple[str, int], Tuple[str, int]] = {}
    problems: List[str] = []
    msgs = sorted(conv.get("chat_messages") or [], key=lambda m: (m.get("created_at", ""), m.get("index", 0)))
    for m in msgs:
        for i, block in enumerate(m.get("content") or []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            inp = block.get("input") or {}
            if not isinstance(inp, dict):
                continue
            if name == "artifacts":
                key = str(inp.get("id") or "artifact")
                cmd = inp.get("command")
                a = arts.setdefault(key, {"title": inp.get("title") or key, "ext": _artifact_ext(inp),
                                          "kind": "artifact", "versions": []})
                if inp.get("title"):
                    a["title"] = inp["title"]
                if inp.get("type"):
                    a["ext"] = _artifact_ext(inp)
                if cmd in ("create", "rewrite") and isinstance(inp.get("content"), str):
                    a["versions"].append(inp["content"])
                elif cmd == "update":
                    if not a["versions"]:
                        problems.append(f"artifact {key}: update without an earlier version")
                        continue
                    old, new = inp.get("old_str") or "", inp.get("new_str") or ""
                    cur = a["versions"][-1]
                    if old and old in cur:
                        a["versions"].append(cur.replace(old, new, 1))
                    else:
                        problems.append(f"artifact {key}: could not apply an update")
                        continue
                else:
                    continue
                refs[(m.get("uuid"), i)] = (key, len(a["versions"]))
            elif name in ("create_file", "str_replace") and isinstance(inp.get("path"), str):
                path = inp["path"]
                key = "file:" + path
                base = path.rstrip("/").split("/")[-1] or "file"
                ext = base.rsplit(".", 1)[1] if "." in base else "txt"
                a = arts.setdefault(key, {"title": path, "ext": ext, "kind": "file", "versions": []})
                if name == "create_file" and isinstance(inp.get("file_text"), str):
                    a["versions"].append(inp["file_text"])
                elif name == "str_replace" and a["versions"]:
                    old, new = inp.get("old_str") or "", inp.get("new_str") or ""
                    cur = a["versions"][-1]
                    if old and old in cur:
                        a["versions"].append(cur.replace(old, new, 1))
                    else:
                        problems.append(f"file {path}: could not apply an edit")
                        continue
                else:
                    continue
                refs[(m.get("uuid"), i)] = (key, len(a["versions"]))
    return arts, refs, problems


def artifact_folder(key: str) -> str:
    """Folder name for one artifact or created file; a short hash keeps long names distinct."""
    tag = hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:8]
    if key.startswith("file:"):
        path = key[5:].strip("/")
        tail = path.rsplit("/", 1)[-1] or "file"
        return f"file-{safe_name(tail, 'file', 60)}-{tag}"
    name = safe_name(key, "artifact", 80)
    return name if name == key else f"{name[:70]}-{tag}"


def claude_file_refs(conv: dict) -> List[Tuple[str, str]]:
    """(file uuid, file name) of every uploaded file or image in the chat."""
    out, seen = [], set()
    for m in conv.get("chat_messages") or []:
        for f in (m.get("files_v2") or []) + (m.get("files") or []):
            if not isinstance(f, dict):
                continue
            fid = f.get("file_uuid") or f.get("uuid")
            if fid and fid not in seen:
                seen.add(fid)
                out.append((fid, f.get("file_name") or fid))
    return out


def claude_markdown(conv: dict, files: Dict[str, str], art_refs: Dict[Tuple[str, int], Tuple[str, int]],
                    arts: Dict[str, dict], conv_dir_rel: str, extra: Dict[str, str]) -> str:
    """files: file uuid -> path relative to the conversations folder."""
    title = _md_escape_title(conv.get("name") or "")
    lines = [f"# {title}", ""]
    meta = [("Created", _fmt_time(conv.get("created_at"))), ("Updated", _fmt_time(conv.get("updated_at"))),
            ("Model", conv.get("model") or ""), ("Conversation", conv.get("uuid") or "")]
    meta += list(extra.items())
    branches = claude_branch_count(conv)
    if branches > 1:
        meta.append(("Branches", f"{branches} (this file shows the current one; the JSON has all)"))
    lines += [f"- **{k}:** {v}" for k, v in meta if v]
    lines += ["", "---", ""]
    for m in claude_path(conv):
        who = "You" if m.get("sender") == "human" else "Claude"
        lines.append(f"## {who} · {_fmt_time(m.get('created_at'))}")
        lines.append("")
        blocks = m.get("content") or []
        if not blocks and m.get("text"):
            blocks = [{"type": "text", "text": m["text"]}]
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and b.get("text"):
                lines += [b["text"].rstrip(), ""]
            elif t == "thinking" and b.get("thinking"):
                lines += ["<details><summary>Thinking</summary>", "", b["thinking"].rstrip(), "", "</details>", ""]
            elif t == "tool_use":
                ref = art_refs.get((m.get("uuid"), i))
                if ref:
                    key, ver = ref
                    a = arts[key]
                    rel = f"{conv_dir_rel}/{artifact_folder(key)}/v{ver}.{a['ext']}"
                    lines += [f"> **{'File' if a['kind'] == 'file' else 'Artifact'}:** {a['title']} "
                              f"(version {ver}) → [{rel}]({rel})", ""]
                else:
                    inp = b.get("input")
                    summary = json.dumps(inp, ensure_ascii=False)[:300] if inp else ""
                    lines += [f"> Tool call: `{b.get('name')}` {summary}", ""]
            elif t == "tool_result":
                parts = b.get("content") or []
                text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))[:300]
                if text.strip():
                    lines += [f"> Tool result ({b.get('name') or 'tool'}): {text.strip()}", ""]
        for a in m.get("attachments") or []:
            lines += [f"> Attachment: {a.get('file_name') or 'file'} "
                      f"({a.get('file_type') or 'text'}; its text is in the JSON)", ""]
        for f in (m.get("files_v2") or []) + (m.get("files") or []):
            if not isinstance(f, dict):
                continue
            fid = f.get("file_uuid") or f.get("uuid")
            name = f.get("file_name") or fid
            if fid in files:
                link = files[fid]
                if (f.get("file_kind") == "image") or re.search(r"\.(png|jpe?g|gif|webp)$", link, re.I):
                    lines += [f"![{name}]({link})", ""]
                else:
                    lines += [f"> File: [{name}]({link})", ""]
            elif fid:
                lines += [f"> File: {name} (not downloaded)", ""]
    return "\n".join(lines).rstrip() + "\n"


# ── ChatGPT (chatgpt.com) ────────────────────────────────────────────────────

def chatgpt_path(conv: dict) -> List[dict]:
    mapping = conv.get("mapping") or {}
    node = conv.get("current_node")
    if node not in mapping:
        # newest leaf
        leaves = [n for n in mapping.values() if not n.get("children")]
        leaves.sort(key=lambda n: ((n.get("message") or {}).get("create_time") or 0))
        node = leaves[-1]["id"] if leaves else None
    out, seen = [], set()
    while node and node in mapping and node not in seen:
        seen.add(node)
        n = mapping[node]
        if n.get("message"):
            out.append(n["message"])
        node = n.get("parent")
    return list(reversed(out))


def chatgpt_branch_count(conv: dict) -> int:
    mapping = conv.get("mapping") or {}
    return sum(1 for n in mapping.values() if not n.get("children") and n.get("message"))


_POINTER_RE = re.compile(r"^(file-service|sediment)://(.+)$")


def _pointer_id(ptr: str) -> Optional[str]:
    m = _POINTER_RE.match(ptr or "")
    if not m:
        return None
    fid = m.group(2)
    return fid.split("#", 1)[0].split("?", 1)[0]


def chatgpt_file_refs(conv: dict) -> List[Tuple[str, str, str]]:
    """(file id, name hint, message id) for images, uploads and generated files."""
    out, seen = [], set()
    names: Dict[str, str] = {}
    for n in (conv.get("mapping") or {}).values():          # attachment names, to label images too
        for a in ((n.get("message") or {}).get("metadata") or {}).get("attachments") or []:
            if isinstance(a, dict) and a.get("id") and isinstance(a.get("name"), str):
                names[a["id"]] = a["name"]

    def add(fid, name, mid):
        if fid and fid not in seen:
            seen.add(fid)
            out.append((fid, names.get(fid) or name or fid, mid or ""))

    for n in (conv.get("mapping") or {}).values():
        msg = n.get("message") or {}
        mid = msg.get("id")
        content = msg.get("content") or {}
        for p in content.get("parts") or []:
            if isinstance(p, dict) and p.get("asset_pointer"):
                fid = _pointer_id(p["asset_pointer"])
                meta = p.get("metadata") or {}
                name = (meta.get("dalle") or {}).get("gen_id") if isinstance(meta.get("dalle"), dict) else None
                add(fid, name, mid)
        for a in (msg.get("metadata") or {}).get("attachments") or []:
            if isinstance(a, dict):
                add(a.get("id"), a.get("name"), mid)
    return out


def chatgpt_sandbox_refs(conv: dict) -> List[Tuple[str, str]]:
    """(message id, sandbox path) of files the code interpreter offered for download."""
    out, seen = [], set()
    for n in (conv.get("mapping") or {}).values():
        msg = n.get("message") or {}
        if (msg.get("author") or {}).get("role") != "assistant":
            continue
        for p in (msg.get("content") or {}).get("parts") or []:
            if not isinstance(p, str):
                continue
            # Markdown links "(sandbox:/mnt/data/My Report.xlsx)" may contain spaces; bare ones may not.
            found = re.findall(r"\(sandbox:(/mnt/data/[^)\n]+)\)", p)
            found += re.findall(r"(?<!\()sandbox:(/mnt/data/[^\s)\]\"']+)", p)
            for path in found:
                path = urllib.parse.unquote(path.strip())
                if (msg.get("id"), path) not in seen:
                    seen.add((msg.get("id"), path))
                    out.append((msg.get("id"), path))
    return out


def _canvas_ext(t: str) -> str:
    t = (t or "").lower()
    if t.startswith("code/"):
        return LANG_EXT.get(t.split("/", 1)[1], "txt")
    return "md" if t in ("document", "") else "txt"


def chatgpt_canvas(conv: dict) -> Tuple[Dict[str, dict], List[str]]:
    """Rebuild canvas documents from canmore.* tool calls. key -> {title, ext, versions}."""
    docs: Dict[str, dict] = {}
    problems: List[str] = []
    current: Optional[str] = None
    count = 0
    msgs = [n.get("message") for n in (conv.get("mapping") or {}).values() if n.get("message")]
    msgs.sort(key=lambda m: m.get("create_time") or 0)
    for m in msgs:
        rcpt = m.get("recipient") or ""
        if not rcpt.startswith("canmore."):
            continue
        content = m.get("content") or {}
        raw = content.get("text")
        if raw is None:
            parts = content.get("parts") or []
            raw = parts[0] if parts and isinstance(parts[0], str) else None
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            continue
        if rcpt == "canmore.create_textdoc":
            count += 1
            current = f"canvas-{count}"
            docs[current] = {"title": data.get("name") or current, "ext": _canvas_ext(data.get("type", "")),
                             "versions": [str(data.get("content") or "")]}
        elif rcpt == "canmore.update_textdoc" and current:
            text = docs[current]["versions"][-1]
            ok = True
            for u in data.get("updates") or []:
                try:
                    text = re.sub(u.get("pattern", ""), lambda _m, r=u.get("replacement", ""): r, text,
                                  count=0 if u.get("multiple") else 1, flags=re.DOTALL)
                except re.error:
                    ok = False
            if not ok:
                problems.append(f"{docs[current]['title']}: one canvas edit could not be applied")
            docs[current]["versions"].append(text)
    return docs, problems


def _chatgpt_parts(content: dict, files: Dict[str, str]) -> List[str]:
    out: List[str] = []
    ct = content.get("content_type")
    if ct in ("text", "multimodal_text"):
        for p in content.get("parts") or []:
            if isinstance(p, str):
                if p.strip():
                    out += [p.rstrip(), ""]
            elif isinstance(p, dict) and p.get("asset_pointer"):
                fid = _pointer_id(p["asset_pointer"])
                if fid and fid in files:
                    out += [f"![image]({files[fid]})", ""]
                else:
                    out += [f"> Image {fid or p['asset_pointer']} (not downloaded)", ""]
    elif ct == "code":
        out += [fence(content.get("text") or "", content.get("language") or ""), ""]
    elif ct == "execution_output":
        out += ["Output:", fence(content.get("text") or ""), ""]
    elif ct in ("tether_quote",):
        out += [f"> {content.get('title') or ''} {content.get('url') or ''}".rstrip(), ""]
    return out


def chatgpt_markdown(conv: dict, files: Dict[str, str], extra: Dict[str, str]) -> str:
    title = _md_escape_title(conv.get("title") or "")
    lines = [f"# {title}", ""]
    meta = [("Created", _fmt_time(conv.get("create_time"))), ("Updated", _fmt_time(conv.get("update_time"))),
            ("Model", conv.get("default_model_slug") or ""),
            ("Conversation", conv.get("conversation_id") or conv.get("id") or "")]
    meta += list(extra.items())
    branches = chatgpt_branch_count(conv)
    if branches > 1:
        meta.append(("Branches", f"{branches} (this file shows the current one; the JSON has all)"))
    lines += [f"- **{k}:** {v}" for k, v in meta if v]
    lines += ["", "---", ""]
    for m in chatgpt_path(conv):
        role = (m.get("author") or {}).get("role")
        md = m.get("metadata") or {}
        if role == "system" or md.get("is_visually_hidden_from_conversation"):
            continue
        content = m.get("content") or {}
        rcpt = m.get("recipient") or "all"
        if role == "assistant" and rcpt.startswith("canmore."):
            lines += [f"> Canvas ({rcpt.split('.', 1)[1]}) → see the canvas folder", ""]
            continue
        body = _chatgpt_parts(content, files)
        if role == "tool":
            imgs = [l for l in body if l.startswith("![")]
            if imgs:
                lines += [f"## Image result · {_fmt_time(m.get('create_time'))}", ""] + imgs + [""]
            continue
        if role == "assistant" and rcpt != "all" and content.get("content_type") == "code":
            lines += [f"> Tool call to `{rcpt}`", ""] + body
            continue
        if not body:
            continue
        who = "You" if role == "user" else "ChatGPT"
        lines += [f"## {who} · {_fmt_time(m.get('create_time'))}", ""] + body
        for a in md.get("attachments") or []:
            if isinstance(a, dict):
                fid = a.get("id")
                name = a.get("name") or fid
                if fid in files:
                    lines += [f"> Attachment: [{name}]({files[fid]})", ""]
                else:
                    lines += [f"> Attachment: {name} (not downloaded)", ""]
    return "\n".join(lines).rstrip() + "\n"


# ── index pages ──────────────────────────────────────────────────────────────

def index_markdown(title: str, rows: Iterable[dict], note: str = "") -> str:
    """rows: {"title", "md", "json", "created", "updated", "flags"} (paths relative to the index)."""
    rows = sorted(rows, key=lambda r: parse_shown(r.get("updated") or "") or datetime.min, reverse=True)
    lines = [f"# {title}", ""]
    if note:
        lines += [note, ""]
    lines += [f"{len(rows)} chats, newest first.", "",
              "| Title | Updated | Created | Notes | Files |", "|---|---|---|---|---|"]
    for r in rows:
        t = (r.get("title") or "Untitled").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| [{t}]({r['md']}) | {r.get('updated', '')} | {r.get('created', '')} | "
                     f"{r.get('flags', '')} | [json]({r['json']}) |")
    return "\n".join(lines) + "\n"


fmt_time = _fmt_time
