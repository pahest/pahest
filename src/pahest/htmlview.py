"""Web pages for the backup: index.html at the top, and one HTML page per conversation.

Markdown reads well in a text editor, but a browser shows it as plain text. This module
turns the Markdown the backup already has into HTML pages and writes index.html at the
top of the backup: every app, the newest conversations, and a search box over all titles.

The pages work offline, straight from the disk: no internet, no outside code. Text from
the chats is always escaped, so nothing in a chat can run as code in your browser. Only
links to web pages (http, https, mailto) and to files inside the backup are made clickable.
"""
from __future__ import annotations

import functools
import hashlib
import html
import json
import posixpath
import re
import urllib.parse
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import ABOUT, HOME_URL, NAME, SLOGAN, __version__, template

from .render import parse_shown

# What a session page can hide (the "Show" menu): key, label, what it covers, and where those parts are on
# the page (CSS selectors). The menu, the style sheet and the script are all made from this list.
SHOW = (("you", "Your messages", "what you typed", ".msg.you"),
        ("say", "AI answers", "what the AI wrote to you", ".msg.ai .say"),
        ("think", "Thinking", "the AI's visible thinking", ".msg.ai details.think,.msg.ai p.note"),
        ("tool", "Tool calls and results", "commands, file edits, searches and their output", ".msg.ai .tool,.msg.ai .res"),
        ("app", "Added by the app", "instructions, reminders, notes, the app's own records and messages it sent",
         ".ctxb,.anote,.msg.auto,.msg.ai>.mb>details.ctx"),
        ("pics", "Pictures", "pictures anywhere in the session", "main .msg img,main .ctxb img,main .anote img"))

_SAFE_SCHEMES = ("http://", "https://", "mailto:")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_LIST = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_INLINE = re.compile(
    r"(?P<code>(?P<ticks>`+)(?P<ctext>.+?)(?<!`)(?P=ticks)(?!`))"
    r"|!\[(?P<alt>[^\]]*)\]\((?P<isrc><[^>\n]*>|[^)\n]*)\)"
    r"|\[(?P<ltext>[^\]\n]+)\]\((?P<href><[^>\n]*>|[^)\n]*)\)"
    r"|<(?P<auto>https?://[^>\s]+)>"
    r"|(?P<bare>https?://[^\s<>()\"']+[^\s<>()\"'.,;:!?])")
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def _emphasis(escaped: str) -> str:
    s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", escaped)
    s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", s)
    return s


def _text(raw: str) -> str:
    """Plain text with **bold**, *italic*, ~~strike~~ and backslash escapes."""
    keep: List[str] = []

    def hold(m):
        keep.append(m.group(1))
        return f"\x00{len(keep) - 1}\x00"
    s = _emphasis(esc(_ESCAPED.sub(hold, raw)))
    return re.sub(r"\x00(\d+)\x00", lambda m: esc(keep[int(m.group(1))]), s)


def inline(raw: str, link: Callable[[str], Optional[str]], autolink: bool = True) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(raw):
        out.append(_text(raw[pos:m.start()]))
        pos = m.end()
        if m.group("code"):
            out.append(f"<code>{esc(m.group('ctext').strip())}</code>")
        elif m.group("isrc") is not None:
            src = link(m.group("isrc").strip().strip("<>"))
            out.append(f'<img src="{esc(src)}" alt="{esc(m.group("alt"))}" loading="lazy">' if src
                       else _text(m.group(0)))
        elif m.group("href") is not None:
            href = link(m.group("href").strip().strip("<>"))
            label = inline(m.group("ltext"), lambda u: None, autolink=False)   # no link inside a link
            out.append(f'<a href="{esc(href)}">{label}</a>' if href else _text(m.group(0)))   # never drop the target
        else:
            url = m.group("auto") or m.group("bare")
            out.append(f'<a href="{esc(url)}">{esc(url)}</a>' if autolink else _text(m.group(0)))
    out.append(_text(raw[pos:]))
    return "".join(out)


def _cells(row: str) -> List[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def _date_attr(text: str) -> str:
    dt = parse_shown(text.strip())
    return f' data-date="{dt:%Y-%m-%dT%H:%M}"' if dt else ""


def _speaker(text: str) -> str:
    first = re.split(r"[\s·(]", text.strip(), 1)[0].lower()
    if first == "you":
        return ' class="you"'
    if first in ("claude", "codex", "assistant"):
        return ' class="ai"'
    return ""


def md_to_html(md: str, link: Callable[[str], Optional[str]]) -> str:
    """The Markdown this backup writes (and what chats usually contain) as safe HTML."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i, n = 0, len(lines)

    def starts_block(line: str) -> bool:
        return bool(_FENCE.match(line) or _HEADING.match(line) or _HR.match(line) or _LIST.match(line)
                    or line.lstrip().startswith(">") or line.strip() in ("</details>",)
                    or line.strip().startswith("<details>"))

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _FENCE.match(line)
        if m:
            fence, info = m.group(1), m.group(2).strip()
            lang = info if re.fullmatch(r"[\w+#.-]+", info) else ""
            body: List[str] = [info] if info and not lang else []     # text typed right after ``` is kept
            i += 1
            while i < n and not (lines[i].strip().startswith(fence[0] * len(fence))
                                 and set(lines[i].strip()) == {fence[0]}):
                body.append(lines[i])
                i += 1
            i += 1
            cls = f' class="lang-{esc(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{esc(chr(10).join(body))}</code></pre>")
            continue
        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            attr = _speaker(m.group(2)) if level in (2, 3) else ""
            if level == 2 and not attr and re.search(r"\d{4} [A-Za-z]+ \d{1,2}$|\d{4}-\d{2}-\d{2}$", m.group(2).strip()):
                attr = _date_attr(m.group(2))       # a day heading (prompt history), not a month
            out.append(f"<h{level}{attr}>{inline(m.group(2), link)}</h{level}>")
            i += 1
            continue
        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue
        d = re.match(r"^\s*<details><summary>(.*?)</summary>\s*$", line)
        if d:
            out.append(f"<details><summary>{esc(d.group(1))}</summary>")
            i += 1
            continue
        if line.strip() == "</details>":
            out.append("</details>")
            i += 1
            continue
        lab = re.match(r"^\s*(?:<sub>|\*)(Result|Error|Results?):(?:</sub>|\*)\s*$", line)
        if lab:
            out.append(f'<div class="label">{esc(lab.group(1))}:</div>')
            i += 1
            continue
        if line.lstrip().startswith(">"):
            quote = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*> ?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{md_to_html(chr(10).join(quote), link)}</blockquote>")
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            head = _cells(line)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            t = ["<div class=\"table\"><table><thead><tr>"] + [f"<th>{inline(c, link)}</th>" for c in head]
            t.append("</tr></thead><tbody>")
            listing = any(c.strip() for c in head)     # a list (not the key/value table at the top)
            for r in rows:
                t.append("<tr>" + "".join(f"<td{_date_attr(c) if listing else ''}>{inline(c, link)}</td>"
                                          for c in r) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue
        if _LIST.match(line):
            items: List[Tuple[int, bool, str]] = []
            while i < n:
                lm = _LIST.match(lines[i])
                if lm:
                    items.append((len(lm.group(1).replace("\t", "    ")), lm.group(2), [lm.group(3)]))
                    i += 1
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    items[-1][2].append(lines[i].strip())
                    i += 1
                else:
                    break
            out.append(_list([(ind, o, "\n".join(t)) for ind, o, t in items], link))
            continue
        para = []
        while i < n and lines[i].strip() and not (para and starts_block(lines[i])) and \
                not ("|" in lines[i] and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]):
            para.append(lines[i])
            i += 1
        if not para:          # a line that looked like a block start but was not one
            para.append(lines[i])
            i += 1
        out.append("<p>" + "<br>".join(inline(p.strip(), link) for p in para) + "</p>")
    return "\n".join(out)


def _list(items: List[Tuple[int, str, str]], link) -> str:
    """Lists; a numbered item keeps its own number (a list may start at 3 or skip numbers)."""
    out: List[str] = []
    stack: List[Tuple[int, str]] = []
    for indent, marker, text in items:
        ordered = marker[0].isdigit()
        tag = "ol" if ordered else "ul"
        li = f'<li value="{int(marker[:-1])}">' if ordered else "<li>"
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            out.append(f"<{tag}>")
            stack.append((indent, tag))
        else:
            out.append("</li>")
        box = re.match(r"^\[([ xX])\]\s+(.*)$", text, re.S)
        if box:
            mark = "☑" if box.group(1).lower() == "x" else "☐"
            text = box.group(2)
            out.append(f"{li}{mark} " + "<br>".join(inline(t, link) for t in text.split("\n")))
        else:
            out.append(li + "<br>".join(inline(t, link) for t in text.split("\n")))
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


# ── pages ────────────────────────────────────────────────────────────────────

def html_path(md_rel: str) -> Optional[str]:
    """Where the web page for a Markdown file goes (paths from the backup's top folder)."""
    if not md_rel.endswith(".md"):
        return None
    if md_rel.startswith("readable/"):
        return md_rel[:-3] + ".html"
    return None


def href(from_rel: str, to_rel: str) -> str:
    rel = posixpath.relpath(to_rel, posixpath.dirname(from_rel) or ".")
    return urllib.parse.quote(rel, safe="/#")


def make_linker(md_rel: str, page_rel: str, pages: Dict[str, str],
                exists: Optional[Callable[[str], bool]] = None) -> Callable[[str], Optional[str]]:
    """Links in a Markdown file, rewritten for its web page: other Markdown files become
    their web pages, files in the backup keep working from the page's folder. A link to a
    file that is not in the backup (a chat often names files of your own project) is shown
    as plain text."""
    def link(url: str) -> Optional[str]:
        url = url.strip()
        if not url:
            return None
        low = url.lower()
        if low.startswith(_SAFE_SCHEMES):
            return url
        if ":" in url.split("/")[0] or url.startswith(("/", "\\", "//")):
            return None                     # javascript:, file:, absolute paths: not clickable
        path, _, frag = url.partition("#")
        target = posixpath.normpath(posixpath.join(posixpath.dirname(md_rel), urllib.parse.unquote(path)))
        if target.startswith("../") or target == "..":
            return None
        target = pages.get(target, target)
        if exists is not None and not exists(target):
            return None
        out = href(page_rel, target)
        return out + ("#" + urllib.parse.quote(frag) if frag else "")
    return link


def title_of(md: str, fallback: str) -> str:
    m = re.search(r"^# (.+)$", md, re.M)
    return m.group(1).strip() if m else fallback


# ── the shared template ──────────────────────────────────────────────────────
#
# Every page is made with layout(): the same top bar, footer, stylesheet
# (readable/assets/style.css) and script (readable/assets/app.js), and the list of every
# session (readable/items.js), so filters, search and previous / next work the same way
# everywhere, offline.

ASSETS = "readable/assets"
ITEMS_JS = "readable/items.js"
PICS_JS = "readable/images.js"
PICS_PAGE = "readable/images.html"
BACKUP_PAGES = [("Backup report", "report.html"), ("What the folders hold", "README.md"),
                ("Original paths and attributes", "source-manifest.jsonl")]       # first in the More menu


def items_js(items: List[list], links: List[Tuple[str, List[Tuple[str, str]]]], about: str) -> str:
    """readable/items.js. ITEMS: [title, "YYYY-MM-DDTHH:MM" local time, app, page (from the backup's top
    folder), note, working folder (full path, ~ for the home folder), opened in, helper 0/1, preview].
    LINKS: more pages for the top bar, in groups [(group, [(label, page)])]: the group "" is shown as
    links in the bar, the others (one per app) in the More menu."""
    js = (f"window.ITEMS={json.dumps(items, ensure_ascii=False)};\n"
          f"window.LINKS={json.dumps(links, ensure_ascii=False)};\n"
          f"window.ABOUT={json.dumps(about, ensure_ascii=False)};\n")
    return js.replace("</", "<\\/")


def pics_js(rows: List[list]) -> str:
    """readable/images.js. PICS: [image file (from the backup's top folder), where it came from
    (readable.PIC_KINDS), "YYYY-MM-DDTHH:MM" local time, its session: an index in ITEMS, or a row like
    those of ITEMS for a page that is not in the lists], newest first."""
    return f"window.PICS={json.dumps(rows, ensure_ascii=False)};\n".replace("</", "<\\/")


def style_css() -> str:
    """readable/assets/style.css."""
    hide = ",".join(f"body.hide-{k} {part}" for k, _, _, sel in SHOW for part in sel.split(","))
    return template.render("style.css", {"hide_css": hide})


def app_js() -> str:
    """readable/assets/app.js."""
    return template.render("app.js", {"copy_icon": template.source("copy_icon.svg").strip(),
                                      "show_selectors": json.dumps({k: sel for k, _, _, sel in SHOW})})


@functools.lru_cache(maxsize=None)
def _asset_version() -> str:
    """Changes when the style sheet or the script changes. It is added to their addresses in every page, so a
    browser (Safari keeps local files in memory) does not go on using an old copy after the pages are rebuilt."""
    return hashlib.sha1((style_css() + app_js()).encode("utf-8")).hexdigest()[:8]


def layout(title: str, body: str, page_rel: str, crumbs: List[Tuple[str, str]], kind: str,
           attrs: Optional[Dict[str, str]] = None, actions: str = "", scripts: Tuple[str, ...] = ()) -> str:
    """The one page template (templates/page.html). kind: list | images | session | doc.
    crumbs: [(label, page or "")]. scripts: more data files (from the backup's top folder), loaded
    before the page's script."""
    index = href(page_rel, "index.html")
    data = {"page": kind, "root": index[:-len("index.html")]}          # root: "" or "../../"
    data.update(attrs or {})
    return template.render("page.html", {
        "title": title, "tool": NAME, "tool_version": __version__, "home_url": HOME_URL, "about": ABOUT,
        "slogan": SLOGAN,
        "style_href": href(page_rel, ASSETS + "/style.css") + "?v=" + _asset_version(), "index_href": index,
        "attrs": [{"name": k, "value": v} for k, v in data.items()],
        "crumbs": [{"label": label, "href": href(page_rel, target) if target else ""} for label, target in crumbs],
        "actions": actions,
        "keys": template.source(f"keys_{kind}.html").strip() if kind != "doc" else "",
        "body": body,
        "backup_pages": [{"label": label, "href": href(page_rel, t)} for label, t in BACKUP_PAGES],
        "scripts": [href(page_rel, x) + "?v=" + _asset_version() for x in (ITEMS_JS,) + tuple(scripts) + (ASSETS + "/app.js",)]})


def _filters(search_hint: str, app: str = "") -> dict:
    """The values of templates/filters.html."""
    return {"search_hint": search_hint,
            "selects": [{"key": key, "label": label, "typed": key == "where"} for key, label in (
                ("app", "App"), ("where", "Folder"), ("surface", "Opened in"), ("kind", "Type"), ("range", "Date"))
                if not (key == "app" and app)]}


def list_page(title: str, subtitle: str, page_rel: str, crumbs: List[Tuple[str, str]], items: List[list],
              app: str = "") -> str:
    """The same list for every app or for one app (`app`): filters, search, newest first by day."""
    mine = [it for it in items if not app or it[2] == app]
    recent = sorted(mine, key=lambda it: it[1] or "", reverse=True)[:50]      # shown without JavaScript
    body = template.render("list.html", dict(
        _filters("Search titles, folders, text…", app), title=title, subtitle=subtitle,
        recent=[{"title": it[0], "href": href(page_rel, it[3]), "when": _shown(it[1])} for it in recent]))
    return layout(title, body, page_rel, crumbs, "list", {"self": page_rel, "app": app})


def images_page(subtitle: str, kinds: List[Tuple[str, str, int]]) -> str:
    """Every picture of every session (readable/images.js), newest first by day, with the same filters as
    the session lists, plus where the pictures came from. kinds: [(key, label, how many)]."""
    body = template.render("images.html", dict(
        _filters("Search session titles, folders…"), subtitle=subtitle,
        kinds=[{"key": k, "label": label, "count": f"{n:,}"} for k, label, n in kinds if n]))
    return layout("Pictures", body, PICS_PAGE, [("Pictures", "")], "images", {"self": PICS_PAGE}, scripts=(PICS_JS,))


def session_page(title: str, rows: List[Tuple[str, str]], note: str, body: str, page_rel: str,
                 crumbs: List[Tuple[str, str]], app_list: str) -> str:
    """One session: a header, the conversation, and previous / next at the top and the bottom (the script
    fills them in, in the order of the list you came from). rows: [(label, html)]."""
    html_body = template.render("session.html", {
        "title": title, "note": note, "conversation": body, "list_href": href(page_rel, app_list),
        "rows": [{"label": k, "value": v} for k, v in rows if v]})
    acts = template.render("session_actions.html", {
        "markdown_href": href(page_rel, page_rel[:-5] + ".md"),
        "show": [{"key": k, "label": label, "tip": tip} for k, label, tip, _ in SHOW]})
    return layout(title, html_body, page_rel, crumbs, "session", {"self": page_rel, "list": app_list}, acts)


def doc_page(title: str, body: str, page_rel: str, crumbs: List[Tuple[str, str]]) -> str:
    return layout(title, body, page_rel, crumbs, "doc")


def when_html(iso: str) -> str:
    """A date as shown, plus how long ago (filled in by the page's script)."""
    if not iso:
        return ""
    return f'{esc(_shown(iso))} <span class="ago" data-iso="{esc(iso)}"></span>'


class Code(NamedTuple):
    """Code, tool input or output, or context the app added: shown exactly as stored, never shortened."""
    text: str
    lang: str = ""


def code_html(c: Code, cls: str = "") -> str:
    pre = f'<pre class="{cls}">' if cls else "<pre>"
    code = f'<code class="lang-{esc(c.lang)}">' if c.lang else "<code>"
    return f"{pre}{code}{esc(c.text.rstrip())}</code></pre>"


def conversation_html(blocks: List[dict], link: Callable[[str], Optional[str]], fix: Callable[[str], str]) -> str:
    """A conversation (blocks from readable.Conv) as HTML: your messages, the assistant's turns with
    their text, thinking, tool calls and results, and dividers. All text is escaped, and nothing is
    shortened (long blocks are only folded on screen)."""
    from .render import human_time

    def md(text) -> str:
        if isinstance(text, list):                # the parts of a message: separate paragraphs
            return parts_html(text, "\n\n")
        return code_html(text) if isinstance(text, Code) else md_to_html(fix(text), link)

    def ctx_html(items, who: str) -> str:   # context the app added: folded, shown in full when opened
        one = [f'<details class="ctx"><summary>{esc(label)}</summary>'
               f'{md(src).replace("<p>", "<p class=src>", 1) if src else ""}{md(body)}</details>'
               for label, body, src in items]
        if len(one) == 1:
            return one[0].replace("<summary>", f"<summary>Added by {esc(who)}: ", 1)
        names = ", ".join(x[0] for x in items[:4]) + (", …" if len(items) > 4 else "")
        return (f'<details class="ctx"><summary>Added by {esc(who)}: {len(items)} items ({esc(names)})</summary>'
                + "".join(one) + "</details>")

    def parts_html(parts, sep: str = "\n") -> str:    # Markdown lines and Code blocks, in order
        out, lines = [], []
        for x in parts:
            if isinstance(x, Code):
                if lines:
                    out.append(md(sep.join(lines)))
                    lines = []
                out.append(code_html(x))
            else:
                lines.append(x)
        if lines:
            out.append(md(sep.join(lines)))
        return "".join(out)

    def when(ts, full: bool) -> str:
        if ts is None:
            return ""
        shown_ = human_time(ts) if full else (human_time(ts)[-5:] if human_time(ts) else "")
        return f"<time>{esc(shown_)}</time>"
    out: List[str] = []
    for b in blocks:
        t = b["t"]
        if t == "you":
            cls = "auto" if b.get("auto") else "you"
            sub = f' <span class="sub">{esc(b["sub"])}</span>' if b.get("sub") else ""
            out.append(f'<section class="msg {cls}"><div class="mh"><b>{esc(b["who"])}{sub}</b>{when(b["ts"], True)}</div>'
                       f'<div class="mb">{md(b["md"])}</div></section>')
        elif t == "divider":
            out.append(f'<div class="divider">{md(b["md"])}</div>')
        elif t == "skip":
            continue
        elif t == "context":
            out.append(f'<div class="ctxb">{ctx_html(b["items"], b["who"])}</div>')
        elif t == "note":
            extra = ctx_html([("details", b["extra"], "")], b["who"]) if b.get("extra") else ""
            out.append(f'<div class="anote"><b>{esc(b["label"])}</b> {when(b["ts"], True)}{md(b["md"]) if b["md"] else ""}'
                       f'{extra}</div>')
        elif t == "summary":
            out.append('<section class="msg sum"><div class="mh"><b>Summary of the earlier conversation</b></div>'
                       f'<div class="mb">{md(b["md"])}</div></section>')
        else:
            parts: List[str] = []
            ctx: List[tuple] = []                    # context items in a row are shown as one folded group
            ctx_app = "the app"
            kinds = set()                            # what the turn holds (the "Show" menu hides by kind)
            for it in b["items"]:
                k = it[0]
                kinds.add({"text": "say", "thinking": "think", "redacted": "think",
                           "context": "app"}.get(k, "tool"))
                if k == "context":
                    ctx.append((it[1], it[2], it[4]))
                    ctx_app = it[3]
                    continue
                if ctx:
                    parts.append(ctx_html(ctx, ctx_app))
                    ctx = []
                if k == "text":
                    parts.append(f'<div class="say">{md(it[1])}</div>')
                elif k == "thinking":
                    parts.append(f'<details class="think"><summary>{esc(it[2])}'
                                 f"</summary>{md(it[1])}</details>")
                elif k == "redacted":
                    parts.append(f'<p class="note">{esc(it[1])} · {inline(fix(it[2]), link)}</p>')
                elif k == "tool":
                    parts.append(f'<div class="tool"><div class="tn">{esc(it[1])}</div>{parts_html(it[2])}</div>')
                elif k == "result":
                    err = " err" if it[1] == "Error" else ""
                    parts.append(f'<div class="res{err}"><div class="rl">{esc(it[1])}</div>'
                                 + (code_html(Code(it[2]), "result") if it[2] else "")
                                 + "".join(md(x) for x in it[3]) + "</div>")
            if ctx:
                parts.append(ctx_html(ctx, ctx_app))
            out.append(f'<section class="msg ai" data-k="{" ".join(sorted(kinds))}"><div class="mh">'
                       f'<b>{esc(b["who"])}</b>{when(b["ts"], False)}</div>'
                       f'<div class="mb">{"".join(parts)}</div></section>')
    return "\n".join(out)




def _shown(iso: str) -> str:
    from .render import MONTHS
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", iso or "")
    return f"{m.group(1)} {MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(4)}:{m.group(5)}" if m else ""


def _shown_stamp(stamp: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})", stamp)
    return _shown(f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}") if m else stamp
