"""Web pages for the backup: index.html at the top, and one HTML page per conversation.

Markdown reads well in a text editor, but a browser shows it as plain text. This module
turns the Markdown the backup already has into HTML pages and writes index.html at the
top of the backup: every app, the newest conversations, and a search box over all titles.

The pages work offline, straight from the disk: no internet, no outside code. Text from
the chats is always escaped, so nothing in a chat can run as code in your browser. Only
links to web pages (http, https, mailto) and to files inside the backup are made clickable.
"""
from __future__ import annotations

import html
import json
import posixpath
import re
import urllib.parse
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import HOME_URL, NAME, __version__

from .render import parse_shown

CSS = """
:root{--bg:#fbfaf8;--fg:#1f1f1c;--muted:#6b6a64;--line:#e6e3dc;--card:#fff;--code:#f4f2ed;--tag:#efede7;
--you:#2f5fb3;--you-bg:#eef3fc;--ai:#2d7a52;--ai-bg:#eef7f1;--link:#2f5fb3;--sel:#d7e4fb;--err:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a18;--fg:#e9e7e1;--muted:#a19f97;--line:#34332f;--card:#22221f;
--code:#2a2926;--tag:#2e2d29;--you:#8fb3f5;--you-bg:#1e2738;--ai:#86cfa6;--ai-bg:#1c2b23;--link:#8fb3f5;--sel:#2b3a57;--err:#f2a19a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,
sans-serif;-webkit-text-size-adjust:100%}
main{max-width:940px;margin:0 auto;padding:10px 16px 24px}
nav.top{position:sticky;top:0;z-index:4;background:var(--bg);border-bottom:1px solid var(--line);padding:7px 16px;font-size:13px;
display:flex;gap:6px;flex-wrap:wrap;align-items:center}
nav.top a{color:var(--link);text-decoration:none}nav.top a.brand{color:var(--fg);font-weight:700;letter-spacing:.01em}nav.top .sep{color:var(--muted)}nav.top .keys{margin-left:auto;color:var(--muted)}
nav.top .acts{margin-left:auto;display:flex;gap:12px}nav.top .acts+.keys{margin-left:12px}
nav.top .acts button{font:inherit;color:var(--link);background:none;border:0;padding:0;cursor:pointer}nav.top .acts button:hover,nav.top a:hover{text-decoration:underline}
a{color:var(--link)}h1{font-size:19px;line-height:1.3;margin:10px 0 2px}h2{font-size:16px;margin:20px 0 6px}
h3,h4{font-size:14px;margin:16px 0 6px}.sub{color:var(--muted);font-size:12px;margin:0 0 6px}
h2.you,h3.you,h2.ai,h3.ai{padding:4px 10px;border-radius:6px;border-left:3px solid}
h2.you,h3.you{background:var(--you-bg);border-color:var(--you);color:var(--you)}
h2.ai,h3.ai{background:var(--ai-bg);border-color:var(--ai);color:var(--ai)}
pre{position:relative;background:var(--code);border:1px solid var(--line);border-radius:6px;padding:8px 10px;overflow:auto;
white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.45;margin:6px 0}
code{font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
p code,li code,td code,dd code{background:var(--code);padding:1px 4px;border-radius:4px}
p{margin:6px 0}blockquote{margin:6px 0;padding:0 12px;border-left:3px solid var(--line);color:var(--muted)}
img{max-width:100%;height:auto;border-radius:6px;border:1px solid var(--line)}
.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td[data-date]{white-space:nowrap}hr{border:0;border-top:1px solid var(--line);margin:14px 0}
details{margin:6px 0}summary{cursor:pointer;color:var(--muted)}
kbd{font:11px ui-monospace,Menlo,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 4px;
background:var(--card)}
/* filters */
.filters{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;background:var(--bg);padding:6px 0;border-bottom:1px solid var(--line);
position:sticky;top:33px;z-index:3;font-size:12px}
.filters label{color:var(--muted);display:flex;align-items:center;gap:4px;white-space:nowrap}
.filters select{font:inherit;font-size:12px;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:5px;
padding:2px 4px;max-width:170px}
.filters select.set{border-color:var(--you);color:var(--you);background:var(--you-bg);font-weight:600}
.filters input[type=search]{flex:1 1 160px;min-width:120px;font:inherit;font-size:12px;padding:4px 8px;border:1px solid var(--line);
border-radius:5px;background:var(--card);color:var(--fg)}
.filters .count{color:var(--muted)}.filters .reset{font-size:12px;cursor:pointer;color:var(--link);background:none;border:0;padding:0}
/* list */
h3.day{display:flex;align-items:baseline;gap:8px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);
margin:14px 0 2px;padding-bottom:3px;border-bottom:1px solid var(--line)}h3.day .dc{font-weight:400}
.det,.filters .alldet{margin-left:auto;font:inherit;font-size:11px;letter-spacing:0;text-transform:none;font-weight:400;color:var(--link);
background:none;border:0;padding:0;cursor:pointer}.filters .alldet{margin-left:0;font-size:12px}.det:hover,.alldet:hover{text-decoration:underline}
ul.items{list-style:none;padding:0;margin:0}
ul.items li{padding:6px 8px;margin:0 -8px;border-bottom:1px solid var(--line);border-radius:6px}
ul.items li:hover{background:var(--card)}
ul.items li.sel{background:var(--sel);box-shadow:inset 3px 0 0 var(--you)}
ul.one li{padding:3px 8px}ul.one .pv,ul.one .tags,ul.items:not(.one) .meta{display:none}
.meta{flex:0 1 auto;max-width:42%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:12px}
.meta button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}.meta button:hover{color:var(--link);text-decoration:underline}
.meta button.on{color:var(--you);font-weight:600}.meta .warn{color:var(--err)}
.r1{display:flex;gap:10px;align-items:baseline}
.r1 a{flex:1;min-width:0;font-weight:600;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.r1 a:hover{text-decoration:underline}.when{flex:none;color:var(--muted);font-size:12px;white-space:nowrap}
.pv{color:var(--muted);font-size:12.5px;margin:1px 0 3px;display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;
-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
.tags{display:flex;flex-wrap:wrap;gap:4px}
.tag{font:inherit;font-size:11px;line-height:1.6;border:0;border-radius:4px;padding:0 6px;background:var(--tag);color:var(--muted);
cursor:pointer}
.tag:hover{color:var(--fg);box-shadow:inset 0 0 0 1px var(--line)}.tag.app{color:var(--you);background:var(--you-bg)}
.tag.on{color:var(--bg);background:var(--you)}span.tag{cursor:default}.tag.warn{color:var(--err)}
aside.dates{display:none;font-size:12px}
aside.dates .dh{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);padding:0 6px 4px}
aside.dates a{display:flex;justify-content:space-between;gap:8px;padding:1px 6px;border-radius:4px;color:var(--muted);text-decoration:none;
white-space:nowrap}aside.dates a span{opacity:.75;font-variant-numeric:tabular-nums}
aside.dates a:hover{background:var(--card);color:var(--fg)}aside.dates a.l0{color:var(--fg);font-weight:600;margin-top:4px}
aside.dates a.l1{padding-left:14px}aside.dates a.l2{padding-left:24px}aside.dates a.l3{padding-left:34px}
aside.dates a.on{color:var(--you);font-weight:600}aside.dates a.cur{background:var(--you-bg)}
@media (min-width:1000px){body[data-page=list] main,body[data-page=images] main{max-width:1120px}
.cols{display:grid;grid-template-columns:minmax(0,1fr) 170px;gap:28px;align-items:start}
aside.dates{display:block;position:sticky;top:110px;max-height:calc(100vh - 120px);overflow:auto;padding-top:12px}}
/* pictures page */
.pks{display:flex;flex-wrap:wrap;gap:2px 14px;flex-basis:100%}.filters .pks label{color:var(--fg);cursor:pointer}.pks .n{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:8px 0 4px}
figure.pic{margin:0;min-width:0;padding:4px;border-radius:8px}figure.pic:hover{background:var(--card)}
figure.pic.sel{background:var(--sel);box-shadow:inset 0 0 0 2px var(--you)}
figure.pic img{display:block;width:100%;height:120px;object-fit:cover;object-position:top;background:var(--code)}
figure.pic figcaption{font-size:11.5px;line-height:1.35;margin-top:4px}
figure.pic a.pa{display:block;cursor:zoom-in}
figure.pic .t{display:block;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
figure.pic small{display:block;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
figure.pic a.vc{font-size:11.5px;text-decoration:none}figure.pic a.vc:hover{text-decoration:underline}
.lb{position:fixed;inset:0;z-index:20;background:rgba(12,12,12,.88);display:flex;align-items:center;justify-content:center;padding:16px 64px}
.lb[hidden]{display:none}.lb figure{margin:0;max-width:100%;max-height:100%;display:flex;flex-direction:column;align-items:center;gap:8px}
.lb img{max-width:min(1600px,100%);max-height:calc(100vh - 100px);object-fit:contain;border:0;border-radius:4px;background:#fff}
.lb figcaption{color:#eee;font-size:13px;line-height:1.5;text-align:center;overflow-wrap:anywhere}.lb figcaption a{color:#9ec3ff}.lb .lm{color:#aaa}
.lb button{position:absolute;width:42px;height:42px;border:0;border-radius:50%;background:rgba(255,255,255,.14);color:#fff;font:26px/1 sans-serif;
cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0 0 3px}.lb button:hover{background:rgba(255,255,255,.28)}
.lb button:disabled{opacity:.25;cursor:default}.lb .lbx{top:12px;right:12px}.lb .lbp{left:12px;top:calc(50% - 21px)}.lb .lbn{right:12px;top:calc(50% - 21px)}
@media (max-width:640px){.lb{padding:56px 8px 8px}.lb .lbp,.lb .lbn{top:auto;bottom:12px}}
button.more{font:inherit;margin:12px 0;padding:5px 12px;border-radius:6px;border:1px solid var(--line);background:var(--card);
color:var(--fg);cursor:pointer}
/* session */
nav.pn{display:flex;gap:8px;align-items:stretch;margin:8px 0;font-size:12px}
nav.pn a,nav.pn span{flex:1 1 0;border:1px solid var(--line);border-radius:6px;padding:5px 9px;text-decoration:none;color:var(--fg);
background:var(--card);min-width:0}
nav.pn .up{flex:0 0 auto;text-align:center;color:var(--muted)}nav.pn .next{text-align:right}nav.pn span{opacity:.45}
nav.pn small{display:block;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}nav.pn b{color:var(--link)}
dl.meta{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:6px 0;font-size:12.5px}
dl.meta dt{color:var(--muted)}dl.meta dd{margin:0;overflow-wrap:anywhere}p.note{font-size:12px;color:var(--muted);font-style:italic}
.msg{margin:10px 0;border:1px solid var(--line);border-radius:8px;background:var(--card);overflow:hidden;
content-visibility:auto;contain-intrinsic-size:auto 300px}
.msg .mh{display:flex;align-items:center;gap:8px;padding:4px 10px;font-size:12px;border-bottom:1px solid var(--line)}
.msg .mh b{flex:1}.msg .mh time{color:var(--muted)}
.msg.you .mh{background:var(--you-bg);color:var(--you)}.msg.ai .mh{background:var(--ai-bg);color:var(--ai)}
.msg.sum .mh,.msg.auto .mh{color:var(--muted)}.msg.auto .mh{background:var(--code)}
.msg .mh .copy{position:static;flex:0 0 auto;width:20px;height:20px;margin:-2px -6px -2px 0;border-color:transparent;background:none}
.msg .mh .copy:hover{border-color:var(--line);background:var(--card)}.msg .mb{padding:2px 10px 6px}
.tool{margin:6px 0;padding-left:8px;border-left:2px solid var(--line)}
.tool .tn{font:600 11px ui-monospace,Menlo,monospace;color:var(--muted)}
.res{margin:-2px 0 8px 10px}.res .rl{font-size:11px;color:var(--muted)}.res.err .rl{color:var(--err)}
details.think{border-left:2px solid var(--line);padding-left:8px}details.think>summary{font-size:12px}
.divider{text-align:center;color:var(--muted);font-size:12px;margin:14px 0}
details.ctx{margin:4px 0;font-size:12px;color:var(--muted)}details.ctx>summary{cursor:pointer;list-style-position:inside}
details.ctx>summary:hover{color:var(--fg)}details.ctx pre{color:var(--fg)}details.ctx details.ctx{margin-left:14px}
.ctxb{margin:6px 0 6px 12px}p.src{margin:4px 0;font-size:12px}.anote{margin:8px 0 8px 12px;font-size:12px;color:var(--muted)}.anote p{margin:2px 0}
.msg .mh .sub{font-weight:400;color:var(--muted)}
/* session: what to show */
details.showm{position:relative;margin:0}details.showm>summary{color:var(--link);list-style:none}
details.showm>summary::-webkit-details-marker{display:none}details.showm>summary::after{content:" ▾";font-size:10px}
details.showm.set>summary{color:var(--you);font-weight:600}
details.showm .menu{position:absolute;right:0;top:24px;z-index:6;background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:8px 12px;min-width:260px;box-shadow:0 6px 20px rgba(0,0,0,.15);color:var(--fg);font-size:13px}
details.showm label{display:flex;gap:6px;align-items:center;padding:2px 0;white-space:nowrap;cursor:pointer}
details.showm label .n{margin-left:auto;padding-left:12px;color:var(--muted);font-size:12px}details.showm label.none{opacity:.45}
details.showm .pre{display:flex;flex-wrap:wrap;gap:4px 12px;border-top:1px solid var(--line);margin-top:6px;padding-top:6px}
details.showm .pre button,p.showing button{font:inherit;font-size:12px;color:var(--link);background:none;border:0;padding:0;cursor:pointer}
p.showing{font-size:12px;color:var(--you);background:var(--you-bg);border-radius:6px;padding:4px 10px}
body.hide-you .msg.you,body.hide-say .msg.ai .say,body.hide-think .msg.ai details.think,body.hide-think .msg.ai p.note,
body.hide-tool .msg.ai .tool,body.hide-tool .msg.ai .res,body.hide-app .ctxb,body.hide-app .anote,body.hide-app .msg.auto,
body.hide-app .msg.ai>.mb>details.ctx,body.hide-pics main .msg img,body.hide-pics main .ctxb img,body.hide-pics main .anote img,
.msg.gone{display:none!important}
img.hit{outline:3px solid var(--you);outline-offset:3px;scroll-margin-top:50px}
.copy{position:absolute;top:4px;right:4px;width:24px;height:24px;border:1px solid var(--line);border-radius:5px;
background:var(--card);color:var(--muted);cursor:pointer;opacity:0;display:flex;align-items:center;justify-content:center;padding:0}
pre:hover .copy,.msg:hover>.mh .copy,.copy:focus{opacity:1}@media (hover:none){.copy{opacity:.6}}.copy:hover{color:var(--fg)}.copy.done{color:var(--ai);opacity:1}
.clip{max-height:var(--clip,320px);overflow:hidden;-webkit-mask-image:linear-gradient(#000 70%,transparent);
mask-image:linear-gradient(#000 70%,transparent)}
.expand{font:inherit;font-size:12px;color:var(--link);background:none;border:0;padding:0 0 4px;cursor:pointer}.msg>.expand{margin:0 10px 6px}
footer{max-width:940px;margin:0 auto;padding:10px 16px 28px;font-size:12px;color:var(--muted);border-top:1px solid var(--line)}
footer a{color:var(--muted)}footer a:hover{color:var(--link)}footer .made{margin-top:4px}
@media print{:root{--bg:#fff;--fg:#000;--muted:#555;--line:#ccc;--card:#fff;--code:#f6f6f6;--tag:#eee;--you:#1d4ea0;
--you-bg:#eef3fc;--ai:#1f6b44;--ai-bg:#eef7f1;--link:#1d4ea0}
nav.top,nav.pn,footer,.copy,.expand,.filters,aside.dates,.det,.alldet,button.more,p.showing{display:none!important}
main{max-width:none;padding:0}.clip{max-height:none!important;-webkit-mask-image:none!important;mask-image:none!important}
pre{overflow:visible;break-inside:auto}.msg{break-inside:auto;overflow:visible;content-visibility:visible}.msg .mh{break-after:avoid}
a{color:inherit;text-decoration:none}ul.one .pv,ul.one .tags{display:block}}
@media (max-width:640px){.filters{top:0;position:static}.filters label{flex:1 1 calc(50% - 12px);min-width:0}
.filters select{flex:1 1 auto;min-width:0;width:100%;max-width:none}.filters input[type=search]{flex-basis:100%}
nav.top .keys{display:none}.meta{display:none}}
"""

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
    if first in ("claude", "codex", "chatgpt", "assistant", "image"):
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
                    items.append((len(lm.group(1).replace("\t", "    ")), lm.group(2), lm.group(3)))
                    i += 1
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    ind, o, t = items[-1]
                    items[-1] = (ind, o, t + "\n" + lines[i].strip())
                    i += 1
                else:
                    break
            out.append(_list(items, link))
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
    if md_rel.startswith("claude-desktop/account/"):
        return "readable/claude.ai/" + md_rel[len("claude-desktop/account/"):-3] + ".html"
    if md_rel.startswith("chatgpt/"):
        return "readable/chatgpt.com/" + md_rel[len("chatgpt/"):-3] + ".html"
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

MADE_WITH = (f'<div class="made">Made with <a href="{HOME_URL}" rel="noopener">{NAME}</a> {__version__}, '
             'open source (MIT license). Pahest is Armenian for “reserve”.</div>')
ASSETS = "readable/assets"
ITEMS_JS = "readable/items.js"
PICS_JS = "readable/images.js"
PICS_PAGE = "readable/images.html"
COPY_ICON = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
             '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>')
FOOTER = [("Backup report", "report.html"), ("What the folders hold", "README.md"),
          ("Original paths and attributes", "source-manifest.jsonl")]


def items_js(items: List[list], links: List[Tuple[str, str]], about: str) -> str:
    """readable/items.js. ITEMS: [title, "YYYY-MM-DDTHH:MM" local time, app, page (from the backup's top
    folder), note, folder, opened in, helper 0/1, preview]. LINKS: more pages for the footer."""
    js = (f"window.ITEMS={json.dumps(items, ensure_ascii=False)};\n"
          f"window.LINKS={json.dumps(links, ensure_ascii=False)};\n"
          f"window.ABOUT={json.dumps(about, ensure_ascii=False)};\n")
    return js.replace("</", "<\\/")


def pics_js(rows: List[list]) -> str:
    """readable/images.js. PICS: [image file (from the backup's top folder), where it came from
    (readable.PIC_KINDS), "YYYY-MM-DDTHH:MM" local time, its session: an index in ITEMS, or a row like
    those of ITEMS for a page that is not in the lists], newest first."""
    return f"window.PICS={json.dumps(rows, ensure_ascii=False)};\n".replace("</", "<\\/")


def layout(title: str, body: str, page_rel: str, crumbs: List[Tuple[str, str]], kind: str,
           attrs: Optional[Dict[str, str]] = None, actions: str = "", scripts: Tuple[str, ...] = ()) -> str:
    """The one page template. kind: list | images | session | doc. crumbs: [(label, page or "")].
    scripts: more data files (from the backup's top folder), loaded before the page's script."""
    root = href(page_rel, "index.html")[:-len("index.html")]        # "" or "../../"
    nav = [f'<a class="brand" href="{href(page_rel, "index.html")}" title="{NAME}: your AI chats, backed up">{NAME}</a>',
           '<span class="sep">·</span>', f'<a href="{href(page_rel, "index.html")}">All chats</a>']
    for label, target in crumbs:
        nav.append('<span class="sep">›</span>')
        nav.append(f'<a href="{href(page_rel, target)}">{esc(label)}</a>' if target else f"<span>{esc(label)}</span>")
    keys = {"list": "<kbd>/</kbd> search · <kbd>j</kbd><kbd>k</kbd> move · <kbd>Enter</kbd> open · <kbd>d</kbd> details",
            "images": "<kbd>/</kbd> search · <kbd>←</kbd><kbd>→</kbd><kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Space</kbd> preview · "
                      "<kbd>Enter</kbd> view in chat",
            "session": "<kbd>←</kbd><kbd>→</kbd> previous / next · <kbd>e</kbd> expand all · <kbd>Esc</kbd> list"}.get(kind, "")
    if actions:
        nav.append(f'<span class="acts">{actions}</span>')
    if keys:
        nav.append(f'<span class="keys">{keys}</span>')
    data = {"page": kind, "root": root}
    data.update(attrs or {})
    body_attrs = " ".join(f'data-{k}="{esc(v)}"' for k, v in data.items())
    foot = " · ".join(f'<a href="{esc(href(page_rel, t))}">{esc(label)}</a>' for label, t in FOOTER)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)}</title><link rel=\"stylesheet\" href=\"{href(page_rel, ASSETS + '/style.css')}\">"
            f"</head><body {body_attrs}><nav class=\"top\">{''.join(nav)}</nav><main>{body}</main>"
            f"<footer id=\"foot\"><span id=\"about\"></span> {foot}<span id=\"links\"></span>{MADE_WITH}</footer>"
            f'<script src="{href(page_rel, ITEMS_JS)}"></script>'
            + "".join(f'<script src="{href(page_rel, x)}"></script>' for x in scripts) +
            f'<script src="{href(page_rel, ASSETS + "/app.js")}"></script></body></html>\n')


def _selects(app: str = "") -> str:
    return "".join(
        f'<label>{label} <select data-key="{key}"><option value="All">All</option></select></label>'
        for key, label in (("app", "App"), ("where", "Folder"), ("surface", "Opened in"), ("kind", "Type"),
                           ("range", "Date")) if not (key == "app" and app))


def list_page(title: str, subtitle: str, page_rel: str, crumbs: List[Tuple[str, str]], items: List[list],
              app: str = "", more: Sequence[Tuple[str, str]] = ()) -> str:
    """The same list for every app or for one app (`app`): filters, search, newest first by day.
    more: other pages to link under the title, such as the pictures page."""
    selects = _selects(app)
    mine = [it for it in items if not app or it[2] == app]
    recent = sorted(mine, key=lambda it: it[1] or "", reverse=True)[:50]
    rec = "".join(f'<li><div class="r1"><a href="{esc(href(page_rel, it[3]))}">{esc(it[0])}</a>'
                  f'<span class="when">{esc(_shown(it[1]))}</span></div></li>' for it in recent)
    links = "".join(f' · <a href="{esc(href(page_rel, t))}">{esc(label)}</a>' for label, t in more)
    body = (f"<h1>{esc(title)}</h1><p class=\"sub\">{esc(subtitle)}{links}</p>"
            f"<div class=\"filters\" id=\"filters\">{selects}"
            "<input type=\"search\" id=\"q\" placeholder=\"Search titles, folders, text…\" autocomplete=\"off\">"
            "<span class=\"count\" id=\"info\"></span><button type=\"button\" class=\"reset\" id=\"reset\" hidden>"
            "Reset</button><button type=\"button\" class=\"alldet\" id=\"alldet\">Show all details</button></div>"
            "<div class=\"cols\"><div id=\"list\"></div><aside class=\"dates\" id=\"dates\" aria-label=\"Dates\"></aside></div>"
            f"<noscript><ul class=\"items\">{rec}</ul></noscript>")
    return layout(title, body, page_rel, crumbs, "list", {"self": page_rel, "app": app})


def images_page(subtitle: str, kinds: List[Tuple[str, str, int]]) -> str:
    """Every picture of every session (readable/images.js), newest first by day, with the same filters as
    the session lists, plus where the pictures came from. kinds: [(key, label, how many)]."""
    page_rel = PICS_PAGE
    boxes = "".join(f'<label title="{n:,} in all"><input type="checkbox" data-pk="{esc(k)}"> {esc(label)} '
                    f'<span class="n"></span></label>' for k, label, n in kinds if n)
    body = (f"<h1>Pictures</h1><p class=\"sub\">{esc(subtitle)}. Click a picture to see it bigger; “View in chat” opens the session at that picture.</p>"
            f"<div class=\"filters\" id=\"filters\"><span class=\"pks\" id=\"pks\">{boxes}</span>{_selects()}"
            "<input type=\"search\" id=\"q\" placeholder=\"Search session titles, folders…\" autocomplete=\"off\">"
            "<span class=\"count\" id=\"info\"></span><button type=\"button\" class=\"reset\" id=\"reset\" hidden>"
            "Reset</button></div>"
            "<div class=\"cols\"><div id=\"list\"></div><aside class=\"dates\" id=\"dates\" aria-label=\"Dates\"></aside></div>"
            "<noscript><p>This page needs JavaScript. The pictures are image files in <code>readable/codex/images/</code> "
            "and <code>readable/claude-code/&lt;project&gt;/images/</code>.</p></noscript>")
    return layout("Pictures", body, page_rel, [("Pictures", "")], "images", {"self": page_rel}, scripts=(PICS_JS,))


# what a session page can hide (the "Show" menu): key, label, what it covers
SHOW = (("you", "Your messages", "what you typed"),
        ("say", "AI answers", "what the AI wrote to you"),
        ("think", "Thinking", "the AI's visible thinking"),
        ("tool", "Tool calls and results", "commands, file edits, searches and their output"),
        ("app", "Added by the app", "instructions, reminders, notes, the app's own records and messages it sent"),
        ("pics", "Pictures", "pictures anywhere in the session"))


def session_page(title: str, rows: List[Tuple[str, str]], note: str, body: str, page_rel: str,
                 crumbs: List[Tuple[str, str]], app_list: str, prev: Optional[list] = None,
                 nxt: Optional[list] = None) -> str:
    """One session: a header from the template, the conversation, and previous / next at the top and the
    bottom (the script fills them in, in the order of the list you came from). rows: [(label, html)]."""
    up = f'<a class="up" href="{esc(href(page_rel, app_list))}">↑ List</a>'
    pn = f'<nav class="pn"><span class="prev">← Previous</span>{up}<span class="next">Next →</span></nav>'
    meta = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows if v)
    html_body = (f"{pn}<h1>{esc(title)}</h1><dl class=\"meta\">{meta}</dl>"
                 + (f"<p class=\"note\">{esc(note)}</p>" if note else "") + f"{body}{pn}")
    show = ('<details class="showm" id="showm"><summary title="Choose what the page shows; printing and copying '
            'follow it">Show</summary><div class="menu">'
            + "".join(f'<label title="{esc(tip)}"><input type="checkbox" data-show="{k}" checked> {esc(label)} '
                      f'<span class="n"></span></label>' for k, label, tip in SHOW) +
            '<div class="pre"><button type="button" data-preset="you">Only my messages</button>'
            '<button type="button" data-preset="you,say">Conversation only</button>'
            '<button type="button" data-preset="">Everything</button></div></div></details>')
    acts = (show + '<button type="button" id="expandall" title="Open every folded block and thinking section (e)">Expand all</button>'
            '<button type="button" id="print" title="Print, or save as PDF from the print window">Print / PDF</button>'
            f'<a href="{esc(href(page_rel, page_rel[:-5] + ".md"))}" title="The same conversation as a Markdown file">'
            "Markdown</a>") if page_rel.endswith(".html") else ""
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
                kinds.add({"text": "say", "image": "say", "thinking": "think", "redacted": "think",
                           "context": "app"}.get(k, "tool"))
                if k == "context":
                    ctx.append((it[1], it[2], it[4] if len(it) > 4 else ""))
                    ctx_app = it[3] if len(it) > 3 else "the app"
                    continue
                if ctx:
                    parts.append(ctx_html(ctx, ctx_app))
                    ctx = []
                if k == "text":
                    parts.append(f'<div class="say">{md(it[1])}</div>')
                elif k == "thinking":
                    parts.append(f'<details class="think"><summary>{esc(it[2] if len(it) > 2 else "Thinking")}'
                                 f"</summary>{md(it[1])}</details>")
                elif k == "redacted":
                    label = it[1] if len(it) > 1 else "Thinking (encrypted by Anthropic; not readable)"
                    src = f" · {inline(fix(it[2]), link)}" if len(it) > 2 and it[2] else ""
                    parts.append(f'<p class="note">{esc(label)}{src}</p>')
                elif k == "tool":
                    parts.append(f'<div class="tool"><div class="tn">{esc(it[1])}</div>{parts_html(it[2])}</div>')
                elif k == "result":
                    err = " err" if it[1] == "Error" else ""
                    parts.append(f'<div class="res{err}"><div class="rl">{esc(it[1])}</div>'
                                 + (code_html(Code(it[2]), "result") if it[2] else "")
                                 + "".join(md(x) for x in it[3]) + "</div>")
                elif k == "image":
                    parts.append(f'<div class="say">{md(it[1])}</div>')
            if ctx:
                parts.append(ctx_html(ctx, ctx_app))
            out.append(f'<section class="msg ai" data-k="{" ".join(sorted(kinds))}"><div class="mh">'
                       f'<b>{esc(b["who"])}</b>{when(b["ts"], False)}</div>'
                       f'<div class="mb">{"".join(parts)}</div></section>')
    return "\n".join(out)


APP_JS = r"""
(function(){
var B=document.body,PAGE=B.getAttribute('data-page'),ROOT=B.getAttribute('data-root')||'',SELF=B.getAttribute('data-self')||'';
var MONTHS=['January','February','March','April','May','June','July','August','September','October','November','December'];
var RANGES=[['All','All'],['today','Today'],['yesterday','Yesterday'],['week','Last 7 days'],['month','Last 30 days'],['ytd','Year to date']];
var KEYS=['app','where','surface','kind','range','q','pk'],DEF={q:'',pk:'you,generated'};
function def(k){return DEF.hasOwnProperty(k)?DEF[k]:'All'}
var SHOWK=['you','say','think','tool','app','pics'],HID={},anyGone=false;   /* session pages: the Show menu */
var COPY='""" + COPY_ICON.replace("'", "\\'") + r"""';
function pad(n){return (n<10?'0':'')+n}
function parseIso(s){var m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(s||'');return m?new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]):null}
function dkey(d){return d?d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()):'undated'}
function dayName(d){return d?d.getFullYear()+' '+MONTHS[d.getMonth()]+' '+d.getDate():'Undated'}
function shown(d){return d?dayName(d)+', '+pad(d.getHours())+':'+pad(d.getMinutes()):''}
function inRange(d,r){if(r=='All')return true;if(!d)return false;var n=new Date(),y=n.getFullYear(),m=n.getMonth(),t=n.getDate(),from,to=null;
if(r=='today')from=new Date(y,m,t);else if(r=='yesterday'){from=new Date(y,m,t-1);to=new Date(y,m,t)}else if(r=='week')from=new Date(y,m,t-6);
else if(r=='month')from=new Date(y,m,t-29);else if(r=='ytd')from=new Date(y,0,1);else return true;return d>=from&&(!to||d<to)}
function ago(d){if(!d)return '';var now=new Date(),s=(now-d)/1000;if(s<45)return 'just now';
var m=Math.round(s/60);if(m<60)return m+' min ago';var h=Math.floor(m/60);if(h<12||(h<24&&d.getDate()==now.getDate()))return h+'h ago';
var t0=new Date(now.getFullYear(),now.getMonth(),now.getDate()),d0=new Date(d.getFullYear(),d.getMonth(),d.getDate()),
days=Math.round((t0-d0)/864e5);if(days<=1)return 'yesterday';if(days<7)return days+' days ago';
var mo=(now.getFullYear()-d.getFullYear())*12+now.getMonth()-d.getMonth()-(now.getDate()<d.getDate()?1:0);
if(days<30||mo<1){var w=Math.floor(days/7);return w+(w==1?' week ago':' weeks ago')}
if(mo<12)return mo+(mo==1?' month ago':' months ago');var y=Math.floor(mo/12);return y+(y==1?' year ago':' years ago')}
function dayLabel(d){if(!d)return 'Undated';var n=dayName(d),now=new Date();if(d.toDateString()==now.toDateString())return n+' · Today';
if(ago(new Date(d.getFullYear(),d.getMonth(),d.getDate(),12))=='yesterday')return n+' · Yesterday';return n}
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function typing(e){var t=e.target;return t&&(t.tagName=='INPUT'||t.tagName=='TEXTAREA'||t.tagName=='SELECT'||t.isContentEditable)}
function refreshAgo(){[].forEach.call(document.querySelectorAll('.ago'),function(e){var d=parseIso(e.getAttribute('data-iso'));
var a=ago(d);e.textContent=a?(e.getAttribute('data-bare')?a:'· '+a):''})}

/* footer: when the backup was made, and the other pages */
(function(){var a=document.getElementById('about'),l=document.getElementById('links');if(a&&window.ABOUT)a.textContent=window.ABOUT+' · ';
if(l&&window.LINKS)l.innerHTML=window.LINKS.map(function(x){return ' · <a href="'+esc(ROOT+x[1])+'">'+esc(x[0])+'</a>'}).join('')})();

/* copy buttons (code blocks and whole messages), and long blocks folded with "Expand" */
var TPL=document.createElement('button');TPL.type='button';TPL.className='copy';TPL.innerHTML=COPY;
function copyButton(title,kind){var b=TPL.cloneNode(true);b.title=title;b.setAttribute('aria-label',title);b.setAttribute('data-copy',kind);return b}
function copyText(b){var kind=b.getAttribute('data-copy');if(kind=='pre'){var pre=b.parentNode;return (pre.querySelector('code')||pre).textContent.replace(/\n$/,'')}
return asText(b.parentNode.parentNode.querySelector('.mb'))}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button.copy');if(!b)return;e.preventDefault();e.stopPropagation();
var text=copyText(b);function ok(){b.classList.add('done');b.textContent='✓';setTimeout(function(){b.classList.remove('done');b.innerHTML=COPY},1200)}
function fallback(){var t=document.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';
document.body.appendChild(t);t.select();try{document.execCommand('copy');ok()}catch(x){}document.body.removeChild(t)}
if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(ok,fallback);else fallback()});
/* a message as Markdown, like the original: what is shown, without buttons; closed thinking is left out */
function asText(el,inner){var out=[],nls=1;
function put(t){if(!t)return;if(nls)t=t.replace(/^[ \t]+/,'');if(!t)return;out.push(t);var m=/\n*$/.exec(t)[0].length;nls=m==t.length?nls+m:m}
function nl(n){if(out.length&&nls<n)put('\n\n'.slice(0,n-nls))}
function wrap(n,mark){put(mark);kids(n);out.push(mark);nls=0}
function kids(e){for(var c=e.firstChild;c;c=c.nextSibling)walk(c)}
function walk(n){if(n.nodeType==3){put(n.nodeValue.replace(/\s+/g,' '));return}if(n.nodeType!=1)return;
var tag=n.tagName.toUpperCase(),cl=n.classList;if(tag=='BUTTON'||tag=='SVG'||tag=='SCRIPT'||tag=='STYLE'||tag=='NOSCRIPT'||off(n))return;
if(tag=='DETAILS'&&!n.open)return;
if(tag=='BR'){put('\n');return}
if(tag=='PRE'){var c=n.querySelector('code')||n,lang=/lang(?:uage)?-(\S+)/.exec(c.className||''),body=c.textContent.replace(/\n$/,''),
f=body.indexOf('```')<0?'```':'````';nl(2);out.push(f+(lang?lang[1]:'')+'\n'+body+'\n'+f);nls=0;nl(2);return}
if(tag=='CODE'){var t=n.textContent,tick=t.indexOf('`')<0?'`':'``';put(tick+t+tick);return}
if(tag=='IMG'){put('!['+(n.getAttribute('alt')||'image')+']('+n.getAttribute('src')+')');return}
if(tag=='A'){var h=n.getAttribute('href')||'';if(/^https?:/.test(h)&&h!=n.textContent){put('[');kids(n);out.push('](' +h+')');nls=0}else kids(n);return}
if(cl.contains('tn')||cl.contains('rl')||tag=='SUMMARY'){nl(2);wrap(n,'**');nl(tag=='SUMMARY'?2:1);return}
if(tag=='STRONG'||tag=='B'){wrap(n,'**');return}
if(tag=='EM'||tag=='I'){wrap(n,'*');return}
if(tag=='DEL'||tag=='S'){wrap(n,'~~');return}
var m=/^H([1-6])$/.exec(tag);if(m){nl(2);put('######'.slice(0,+m[1])+' ');kids(n);nl(2);return}
if(tag=='HR'){nl(2);put('---');nl(2);return}
if(tag=='BLOCKQUOTE'){nl(2);put(asText(n,true).split('\n').map(function(l){return l?'> '+l:'>'}).join('\n'));nl(2);return}
if(tag=='UL'||tag=='OL'){nl(n.parentNode&&n.parentNode.tagName=='LI'?1:2);var i=0;for(var li=n.firstChild;li;li=li.nextSibling){if(li.tagName!='LI')continue;i++;nl(1);
var mark=tag=='OL'?i+'. ':'- ',pad='   '.slice(0,mark.length);
put(mark+asText(li,true).split('\n').map(function(l,j){return j&&l?pad+l:l}).join('\n'))}nl(2);return}
if(tag=='TR'){nl(1);put('|');[].forEach.call(n.children,function(td){out.push(' '+asText(td,true).replace(/\n+/g,' ').replace(/\|/g,'\\|')+' |')});nls=0;
if(n.parentNode.tagName=='THEAD')out.push('\n|'+[].map.call(n.children,function(){return ' --- |'}).join(''));return}
var block=/^(P|DIV|SECTION|DETAILS|TABLE|FIGURE|DL|DT|DD|LI)$/.test(tag);if(block)nl(2);kids(n);if(block)nl(2)}
if(inner)kids(el);else walk(el);
return out.join('').split('\n').map(function(l){return l.replace(/[ \t]+$/,'')}).join('\n').replace(/\n{3,}/g,'\n\n').trim()}
/* copy buttons and folding. Long blocks are found from their text (lines and characters), not by
   measuring the page, so even a session of tens of megabytes opens quickly. */
function tall(text,maxPx){var lines=1,i=-1;while((i=text.indexOf('\n',i+1))>=0){lines++;if(lines>maxPx/16+8)return true}
return text.length>(maxPx/16+8)*110}
function enhance(root){var r=root||document;
[].forEach.call(r.querySelectorAll('pre:not([data-done])'),function(pre){pre.setAttribute('data-done','1');pre.appendChild(copyButton('Copy','pre'));
var max=pre.classList.contains('result')?200:360;if(tall(pre.textContent,max))fold(pre,max)});
[].forEach.call(r.querySelectorAll('.msg'),function(msg){var mh=msg.querySelector('.mh'),mb=msg.querySelector('.mb');
if(!mh||!mb||mh.querySelector('.copy'))return;mh.appendChild(copyButton('Copy message','msg'));
var max=msg.classList.contains('auto')?160:900;if(tall(mb.textContent,max))fold(mb,max)})}
function fold(el,max){if(el.getAttribute('data-fold'))return;el.setAttribute('data-fold','1');
el.style.setProperty('--clip',max+'px');el.classList.add('clip');var lines=el.tagName=='PRE'?(((el.textContent.match(/\n/g)||[]).length+1).toLocaleString()+' lines'):'';
var x=document.createElement('button'),label='Expand'+(lines?' · '+lines:'');x.type='button';x.className='expand';x.textContent=label;
x.setAttribute('data-label',label);x.onclick=function(){var shut=el.classList.toggle('clip');x.textContent=shut?label:'Collapse'};
el.parentNode.insertBefore(x,el.nextSibling)}

/* the list of every session, shared by list pages and session pages */
var ITEMS=window.ITEMS||[];ITEMS.forEach(function(it){it.d=parseIso(it[1])});
function surf(it){return it[6]||'Other'}function kind(it){return it[7]?'Helpers':'Conversations'}function where(it){return it[5]||'(no folder)'}
function val(it,k){return k=='app'?it[2]:k=='where'?where(it):k=='surface'?surf(it):k=='kind'?kind(it):null}
function readState(){var st={app:'All',where:'All',surface:'All',kind:'All',range:'All',q:'',pk:DEF.pk,from:''};
location.hash.replace(/^#/,'').split('&').forEach(function(kv){var p=kv.split('=');if(p.length==2&&st.hasOwnProperty(p[0]))st[p[0]]=decodeURIComponent(p[1])});return st}
function stateHash(st,from){var p=[];KEYS.forEach(function(k){if(st[k]!=null&&st[k]!==def(k)&&(st[k]||k=='pk'))p.push(k+'='+encodeURIComponent(st[k]))});
if(from)p.push('from='+encodeURIComponent(from));return p.join('&')}
function match(it,st,skip){for(var i=0;i<KEYS.length;i++){var k=KEYS[i];if(k==skip||k=='q')continue;
if(k=='pk'){if(it.pk&&(','+st.pk+',').indexOf(','+it.pk+',')<0)return false;continue}if(st[k]=='All')continue;
if(k=='range'){if(!inRange(it.d,st.range))return false}else if(val(it,k)!=st[k])return false}
if(st.q&&skip!='q'){var hay=(it[0]+' '+it[2]+' '+it[4]+' '+it[5]+' '+surf(it)+' '+(it[8]||'')).toLowerCase(),w=st.q.toLowerCase().split(/\s+/);
for(var j=0;j<w.length;j++)if(w[j]&&hay.indexOf(w[j])<0)return false}return true}
var PKL={you:'you pasted',generated:'generated',tool:'from a tool',app:'app record'};
var PICS=PAGE=='images'?(window.PICS||[]).map(function(p){var s=(typeof p[3]=='number'?ITEMS[p[3]]:p[3])||[],o=[s[0]||'',p[2],s[2]||'',s[3]||'',s[4]||'',s[5]||'',s[6]||'',s[7]||0,s[8]||''];
o.d=parseIso(p[2]);o.file=p[0];o.pk=p[1];return o}):[];
function byDate(a,b){return (b.d?b.d.getTime():0)-(a.d?a.d.getTime():0)}
function ordered(st){return ITEMS.filter(function(it){return match(it,st,'')}).sort(byDate)}

if(PAGE=='list'||PAGE=='images')listPage();else if(PAGE=='session'){initShow();sessionPage()}else docPage();
enhance();if(PAGE=='session')goPic();refreshAgo();setInterval(refreshAgo,60000);

function listPage(){var fixedApp=B.getAttribute('data-app')||'';var st=readState();if(fixedApp)st.app=fixedApp;
var GAL=PAGE=='images',NOUN=GAL?['picture','pictures']:['session','sessions'],ROW=GAL?'figure.pic':'li',STEP=GAL?240:400,pks=document.getElementById('pks');
var limit=STEP,list=document.getElementById('list'),info=document.getElementById('info'),q=document.getElementById('q'),
reset=document.getElementById('reset'),alldet=document.getElementById('alldet'),sel=-1;
/* days show one line per session; "Show details" opens a day (all days when searching, or after "Show all details") */
var DET='pahest-details',allOpen=false,dayOpen={};try{allOpen=localStorage.getItem(DET)=='1'}catch(e){}
function isOpen(dn){return dayOpen.hasOwnProperty(dn)?dayOpen[dn]:(allOpen||!!st.q)}
function setDay(h,open){var dn=h.getAttribute('data-day');dayOpen[dn]=open;var ul=h.nextElementSibling;if(ul)ul.classList.toggle('one',!open);
h.querySelector('.det').textContent=open?'Hide details':'Show details'}
function setAll(open){if(GAL)return;allOpen=open;dayOpen={};try{localStorage.setItem(DET,open?'1':'0')}catch(e){}
[].forEach.call(list.querySelectorAll('h3.day'),function(h){setDay(h,open)});dayOpen={};alldet.textContent=open?'Hide all details':'Show all details'}
if(alldet)alldet.textContent=allOpen?'Hide all details':'Show all details';
/* dates at the side: years; the year in view opens to months, its month to weeks, its week to days. Click to jump. */
var aside=document.getElementById('dates'),filtersEl=document.getElementById('filters'),ents=[],byId={},paths={},activeDay=null,jumpY=null;
var DOW=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
function mon3(m){return MONTHS[m].slice(0,3)}
function buildDates(hits){ents=[];byId={};paths={};hits.forEach(function(it,i){var d=it.d,k=dkey(d),ids;
if(!d)ids=[['u','Undated']];else{var y=d.getFullYear(),m=d.getMonth(),ws=new Date(y,m,d.getDate()-(d.getDay()+6)%7),we=new Date(ws.getFullYear(),ws.getMonth(),ws.getDate()+6),
a=ws.getMonth()==m?ws.getDate():1,b=we.getMonth()==m?we.getDate():new Date(y,m+1,0).getDate();
ids=[['y'+y,''+y],['m'+y+'-'+m,MONTHS[m]],['w'+y+'-'+m+'-'+a,mon3(m)+' '+a+(a==b?'':' – '+b)],['d'+k,DOW[d.getDay()]+' '+d.getDate()]]}
paths[k]=ids.map(function(x){return x[0]});
ids.forEach(function(x,lvl){var e=byId[x[0]];if(!e){e=byId[x[0]]={id:x[0],label:x[1],lvl:lvl,n:0,first:k,i:i,parent:lvl?ids[lvl-1][0]:''};ents.push(e)}e.n++})})}
function drawDates(){if(!aside)return;var act=paths[activeDay]||paths[ents.length?ents[0].first:'']||[];
aside.innerHTML=ents.length?'<div class="dh">Jump to</div>'+ents.filter(function(e){return e.lvl==0||act[e.lvl-1]==e.parent}).map(function(e){
return '<a href="#" data-go="'+e.id+'" class="l'+e.lvl+(act[e.lvl]==e.id?' on'+(e.lvl==act.length-1?' cur':''):'')+'" title="'+e.n+' '+(e.n==1?NOUN[0]:NOUN[1])+'">'+
esc(e.label)+'<span>'+e.n+'</span></a>'}).join(''):'';
var on=aside.querySelectorAll('a.on');on=on[on.length-1];if(on&&on.scrollIntoViewIfNeeded)on.scrollIntoViewIfNeeded(false)}
function stickTop(){if(aside&&filtersEl)aside.style.top=(filtersEl.getBoundingClientRect().height+40)+'px'}
/* where the list starts under the bars that stay on screen (the filters stick only once the page scrolls) */
function stuck(){var cs=getComputedStyle(filtersEl),nav=document.querySelector('nav.top');
return cs.position=='sticky'?(parseFloat(cs.top)||0)+filtersEl.offsetHeight:(nav?nav.offsetHeight:0)}
function spy(){if(jumpY!==null){if(window.pageYOffset===jumpY)return;jumpY=null}var top=stuck()+6,hs=list.querySelectorAll('h3.day'),cur=hs[0];
for(var i=0;i<hs.length;i++){if(hs[i].getBoundingClientRect().top<=top)cur=hs[i];else break}
var k=cur?cur.getAttribute('data-key'):null;if(k!=activeDay){activeDay=k;drawDates()}}
var spyT=null;window.addEventListener('scroll',function(){if(!spyT)spyT=setTimeout(function(){spyT=null;spy()},60)});
window.addEventListener('resize',stickTop);
function jump(e){if(e.i>=limit){limit=Math.ceil((e.i+1)/STEP)*STEP;draw()}var h=list.querySelector('h3.day[data-key="'+e.first+'"]');if(!h)return;
window.scrollTo(0,h.getBoundingClientRect().top+window.pageYOffset-stuck()-4);
activeDay=e.first;jumpY=window.pageYOffset;drawDates()}
if(aside)aside.addEventListener('click',function(ev){var a=ev.target.closest('a[data-go]');if(!a)return;ev.preventDefault();var e=byId[a.getAttribute('data-go')];if(e)jump(e)});
if(alldet)alldet.addEventListener('click',function(){setAll(!allOpen)});
var pool=GAL?PICS:fixedApp?ITEMS.filter(function(it){return it[2]==fixedApp}):ITEMS;
function counted(key){var c={};pool.forEach(function(it){var v=val(it,key);c[v]=(c[v]||0)+1});return c}
var ORDER={app:['Claude Code','Codex','Claude desktop','claude.ai','ChatGPT'],surface:['Desktop app','Terminal','Code editor','Automation','Other'],kind:['Conversations','Helpers']};
function options(key){if(key=='range')return RANGES;var c=counted(key),vals=Object.keys(c);
if(ORDER[key])vals.sort(function(a,b){return ORDER[key].indexOf(a)-ORDER[key].indexOf(b)});else vals.sort(function(a,b){return c[b]-c[a]||a.localeCompare(b)});
return [['All','All']].concat(vals.map(function(v){return [v,v=='Helpers'?'Subagents & reviews':v]}))}
var OPTS={};['app','where','surface','kind','range'].forEach(function(k){OPTS[k]=options(k)});
function fill(key){var s=document.querySelector('select[data-key="'+key+'"]');if(!s)return;
if(OPTS[key].length<3&&key!='range'){s.parentNode.style.display='none';return}
s.innerHTML=OPTS[key].map(function(o){var n=0;for(var i=0;i<pool.length;i++){var it=pool[i];if(!match(it,st,key))continue;
if(key=='range'?inRange(it.d,o[0]):(o[0]=='All'||val(it,key)==o[0]))n++}
return '<option value="'+esc(o[0])+'"'+(st[key]==o[0]?' selected':'')+(n||o[0]=='All'||st[key]==o[0]?'':' disabled')+'>'+esc(o[1])+' ('+n.toLocaleString()+')</option>'}).join('');
s.className=st[key]=='All'?'':'set'}
function dirty(){return KEYS.some(function(k){return (k!='app'||!fixedApp)&&(k!='pk'||GAL)&&st[k]!=null&&st[k]!==def(k)})}
function kindsBox(){if(!pks)return;var c={};pool.forEach(function(it){if(match(it,st,'pk'))c[it.pk]=(c[it.pk]||0)+1});
[].forEach.call(pks.querySelectorAll('input[data-pk]'),function(x){var k=x.getAttribute('data-pk');x.checked=(','+st.pk+',').indexOf(','+k+',')>=0;
x.parentNode.querySelector('.n').textContent='('+(c[k]||0).toLocaleString()+')'})}
function save(){var h=stateHash(fixedApp?Object.assign({},st,{app:'All'}):st);try{history.replaceState(null,'',h?'#'+h:location.pathname)}catch(e){}}
function tag(k,v,label,cls){var on=st[k]==v;return '<button type="button" class="tag'+(cls?' '+cls:'')+(on?' on':'')+'" data-k="'+k+'" data-v="'+esc(v)+
'" title="'+(on?'Show all':'Show only '+esc(v))+'">'+esc(label)+'</button>'}
function draw(){['app','where','surface','kind','range'].forEach(fill);kindsBox();var hits=pool.filter(function(it){return match(it,st,'')}).sort(byDate);
info.textContent=hits.length.toLocaleString()+' '+(hits.length==1?NOUN[0]:NOUN[1]);reset.hidden=!dirty();var out=[],day=null,link=stateHash(st,SELF);
if(GAL){drawPics(hits);return}
var per={},dl=[];for(var i=0;i<hits.length&&i<limit;i++){dl[i]=dayLabel(hits[i].d);per[dl[i]]=(per[dl[i]]||0)+1}
for(i=0;i<hits.length&&i<limit;i++){var it=hits[i],dn=dl[i];if(dn!=day){if(day!==null)out.push('</ul>');var op=isOpen(dn);
out.push('<h3 class="day" data-day="'+esc(dn)+'" data-key="'+dkey(it.d)+'"><span>'+esc(dn)+'</span><span class="dc">· '+per[dn]+'</span><button type="button" class="det">'+
(op?'Hide details':'Show details')+'</button></h3><ul class="items'+(op?'':' one')+'">');day=dn}
var when=it.d?pad(it.d.getHours())+':'+pad(it.d.getMinutes())+' · <span class="ago" data-bare="1" data-iso="'+it[1]+'">'+esc(ago(it.d))+'</span>':'';
var tags=(fixedApp?'':tag('app',it[2],it[2],'app'))+tag('surface',surf(it),surf(it))+(it[5]?tag('where',it[5],it[5]):'')+
(it[7]?tag('kind','Helpers',it[4].indexOf('review')>=0?'automatic review':'subagent'):'')+
(it[4]&&!it[7]?'<span class="tag'+(it[4].indexOf('deleted')>=0?' warn':'')+'">'+esc(it[4])+'</span>':'');
function mini(k,v,label){return '<button type="button" class="'+(st[k]==v?'on':'')+'" data-k="'+k+'" data-v="'+esc(v)+'" title="'+
(st[k]==v?'Show all':'Show only '+esc(v))+'">'+esc(label)+'</button>'}
var meta=[];if(it[5])meta.push(mini('where',it[5],it[5]));if(!fixedApp)meta.push(mini('app',it[2],it[2]));
if(it[7])meta.push(mini('kind','Helpers',it[4].indexOf('review')>=0?'automatic review':'subagent'));
if(it[4]&&!it[7]&&it[4].indexOf('deleted')>=0)meta.push('<span class="warn">deleted at source</span>');
out.push('<li><div class="r1"><a href="'+esc(ROOT+it[3])+'#'+link+'">'+esc(it[0])+'</a><span class="meta">'+meta.join(' · ')+'</span>'+
'<span class="when">'+when+'</span></div>'+
(it[8]?'<div class="pv">'+esc(it[8])+'</div>':'')+'<div class="tags">'+tags+'</div></li>')}
if(day!==null)out.push('</ul>');finish(out,hits)}
function finish(out,hits){if(hits.length>limit)out.push('<button type="button" class="more" id="more">Show more ('+(hits.length-limit).toLocaleString()+' left)</button>');
list.innerHTML=out.join('');sel=-1;buildDates(hits);activeDay=null;stickTop();spy();drawDates();var more=document.getElementById('more');if(more)more.onclick=function(){limit+=STEP;draw()};save()}
/* the pictures page: a grid per day; a picture opens its session at the place it is shown */
var galHits=[],lb=null,lbI=-1;
function picFile(it){return ROOT+it.file}
function picGo(it){return ROOT+it[3]+'#pic='+encodeURIComponent(it.file.slice(it.file.lastIndexOf('/')+1))+'&at='+it.pk}
function drawPics(hits){galHits=hits;var out=[],day=null,per={},dl=[];for(var i=0;i<hits.length&&i<limit;i++){dl[i]=dayLabel(hits[i].d);per[dl[i]]=(per[dl[i]]||0)+1}
for(i=0;i<hits.length&&i<limit;i++){var it=hits[i],dn=dl[i];if(dn!=day){if(day!==null)out.push('</div>');
out.push('<h3 class="day" data-day="'+esc(dn)+'" data-key="'+dkey(it.d)+'"><span>'+esc(dn)+'</span><span class="dc">· '+per[dn]+'</span></h3><div class="grid">');day=dn}
out.push('<figure class="pic" data-i="'+i+'"><a class="pa" href="'+esc(picFile(it))+'" title="Show bigger"><img loading="lazy" src="'+esc(picFile(it))+'" alt=""></a>'+
'<figcaption><span class="t" title="'+esc(it[0])+'">'+esc(it[0])+'</span><small>'+(it.d?pad(it.d.getHours())+':'+pad(it.d.getMinutes())+' · ':'')+esc(PKL[it.pk]||it.pk)+
(fixedApp?'':' · '+esc(it[2]))+'</small><a class="vc" href="'+esc(picGo(it))+'">View in chat</a></figcaption></figure>')}
if(day!==null)out.push('</div>');finish(out,hits)}
/* the popup: the picture large on top of the page; ← → move through the pictures shown, Esc or a click outside closes it */
function lbOpen(i){var it=galHits[i];if(!it)return;
if(!lb){lb=document.createElement('div');lb.className='lb';lb.hidden=true;lb.setAttribute('role','dialog');lb.setAttribute('aria-modal','true');lb.setAttribute('aria-label','Picture');
lb.innerHTML='<button type="button" class="lbx" title="Close (Space or Esc)" aria-label="Close">×</button><button type="button" class="lbp" title="Previous (←)" aria-label="Previous">‹</button>'+
'<button type="button" class="lbn" title="Next (→)" aria-label="Next">›</button><figure><img alt=""><figcaption></figcaption></figure>';document.body.appendChild(lb);
lb.addEventListener('click',function(e){var t=e.target;if(t==lb||t.tagName=='FIGURE'||t.classList.contains('lbx'))lbClose();else if(t.classList.contains('lbp'))lbOpen(lbI-1);
else if(t.classList.contains('lbn'))lbOpen(lbI+1)});
document.addEventListener('keydown',function(e){if(lb.hidden||e.metaKey||e.ctrlKey||e.altKey)return;var k=e.key;
if(k=='Escape'||k==' ')lbClose();else if(k=='ArrowLeft'||k=='k')lbOpen(lbI-1);else if(k=='ArrowRight'||k=='j')lbOpen(lbI+1);
else if(k=='Enter'){location.href=picGo(galHits[lbI])}else if(k=='Tab')return;else{e.stopImmediatePropagation();return}
e.preventDefault();e.stopImmediatePropagation()},true)}
lbI=i;var img=lb.querySelector('img');img.src=picFile(it);img.alt=it[0];
lb.querySelector('figcaption').innerHTML='<b>'+esc(it[0])+'</b><span class="lm"> · '+esc(shown(it.d))+' · '+esc(PKL[it.pk]||it.pk)+' · '+esc(it[2])+'</span><br>'+
'<a class="lc" href="'+esc(picGo(it))+'" title="Enter">View in chat</a> · <a href="'+esc(picFile(it))+'" target="_blank" rel="noopener">Open image</a>'+
'<span class="lm"> · '+(i+1).toLocaleString()+' of '+galHits.length.toLocaleString()+'</span>';
lb.querySelector('.lbp').disabled=i<=0;lb.querySelector('.lbn').disabled=i>=galHits.length-1;
if(lb.hidden){lb.hidden=false;document.documentElement.style.overflow='hidden'}
var nx=galHits[i+1];if(nx)(new Image()).src=picFile(nx)}
function lbClose(){lb.hidden=true;document.documentElement.style.overflow='';var all=list.querySelectorAll(ROW),fig=list.querySelector('figure.pic[data-i="'+lbI+'"]');
if(!fig)return;if(sel>=0&&all[sel])all[sel].classList.remove('sel');sel=[].indexOf.call(all,fig);fig.classList.add('sel');fig.scrollIntoView({block:'nearest'})}
document.getElementById('filters').addEventListener('change',function(e){var s=e.target;
if(s.getAttribute('data-pk')){st.pk=[].filter.call(pks.querySelectorAll('input[data-pk]'),function(x){return x.checked}).map(function(x){return x.getAttribute('data-pk')}).join(',');limit=STEP;draw();return}
if(s.tagName!='SELECT')return;st[s.getAttribute('data-key')]=s.value;limit=STEP;draw()});
list.addEventListener('click',function(e){var pa=e.target.closest('a.pa');
if(pa&&!(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button)){e.preventDefault();lbOpen(+pa.parentNode.getAttribute('data-i'));return}
var d=e.target.closest('button.det');if(d){var h=d.parentNode;setDay(h,!isOpen(h.getAttribute('data-day')));return}
var b=e.target.closest('button[data-k]');if(!b)return;var k=b.getAttribute('data-k'),v=b.getAttribute('data-v');
st[k]=st[k]==v?'All':v;limit=STEP;draw()});
reset.addEventListener('click',function(){KEYS.forEach(function(k){if(!(k=='app'&&fixedApp))st[k]=def(k)});q.value='';limit=STEP;draw()});
q.value=st.q;q.addEventListener('input',function(){st.q=q.value.trim();limit=STEP;draw()});
/* the pictures grid: up and down go to the nearest picture in the row above or below */
function moveRow(dir){var all=list.querySelectorAll(ROW);if(!all.length)return;if(sel<0){move(1);return}
var cur=all[sel].getBoundingClientRect(),best=-1,bt=0,bx=0;
for(var i=0;i<all.length;i++){var r=all[i].getBoundingClientRect();if(dir>0?r.top<=cur.top+5:r.top>=cur.top-5)continue;
var dt=Math.abs(r.top-cur.top),dx=Math.abs(r.left-cur.left);if(best<0||dt<bt-5||(Math.abs(dt-bt)<=5&&dx<bx)){best=i;bt=dt;bx=dx}}
if(best>=0)move(best-sel)}
function move(by){var li=list.querySelectorAll(ROW);if(!li.length)return;if(sel>=0&&li[sel])li[sel].classList.remove('sel');sel=Math.max(0,Math.min(li.length-1,sel+by));
li[sel].classList.add('sel');li[sel].scrollIntoView({block:'nearest'})}
document.addEventListener('keydown',function(e){if(e.metaKey||e.ctrlKey||e.altKey)return;
if(e.key=='Escape'&&e.target==q){if(q.value){q.value='';st.q='';draw()}else q.blur();return}
if(typing(e))return;if(e.key=='/'){e.preventDefault();q.focus();q.select()}
else if(GAL&&(e.key=='ArrowDown'||e.key=='ArrowUp')){e.preventDefault();moveRow(e.key=='ArrowDown'?1:-1)}
else if(GAL&&(e.key=='ArrowRight'||e.key=='ArrowLeft')){e.preventDefault();move(e.key=='ArrowRight'?1:-1)}
else if(GAL&&e.key==' '&&sel>=0){e.preventDefault();lbOpen(+list.querySelectorAll(ROW)[sel].getAttribute('data-i'))}
else if(e.key=='j'||e.key=='ArrowDown'){e.preventDefault();move(1)}else if(e.key=='k'||e.key=='ArrowUp'){e.preventDefault();move(-1)}
else if(e.key=='d'&&!GAL){var li=list.querySelectorAll('li')[sel],h=li?li.parentNode.previousElementSibling:null;
if(h&&h.classList.contains('day'))setDay(h,!isOpen(h.getAttribute('data-day')));else setAll(!allOpen)}
else if((e.key=='Enter'||e.key=='o')&&sel>=0){var r=list.querySelectorAll(ROW)[sel];
var a=r.querySelector(GAL?'a.vc':'a');if(a)location.href=a.href}});
draw()}

function expandAll(open){[].forEach.call(document.querySelectorAll('[data-fold]'),function(el){el.classList.toggle('clip',!open);
var b=el.nextElementSibling;if(b&&b.classList.contains('expand'))b.textContent=open?'Collapse':b.getAttribute('data-label')});
[].forEach.call(document.querySelectorAll('main details'),function(d){d.open=open});var ex=document.getElementById('expandall');
if(ex)ex.textContent=open?'Collapse all':'Expand all';expanded=open}
var expanded=false,printOpened=false;
window.addEventListener('beforeprint',function(){printOpened=!expanded;if(printOpened)expandAll(true)});
window.addEventListener('afterprint',function(){if(printOpened)expandAll(false);printOpened=false});
(function(){var ex=document.getElementById('expandall'),pr=document.getElementById('print');
if(ex)ex.addEventListener('click',function(){expandAll(!expanded)});if(pr)pr.addEventListener('click',function(){window.print()});
if(ex)document.addEventListener('keydown',function(e){if(!(e.metaKey||e.ctrlKey||e.altKey||typing(e))&&e.key=='e')expandAll(!expanded)})})();
/* session pages: "Show" hides kinds of parts (on screen, in print and when copying); the choice is remembered */
function off(n){var c=n.classList;if(n.tagName=='IMG')return !!HID.pics;if(!c)return false;
return !!((HID.say&&c.contains('say'))||(HID.think&&(c.contains('think')||(c.contains('note')&&n.tagName=='P')))||
(HID.tool&&(c.contains('tool')||c.contains('res')))||(HID.app&&c.contains('ctx')))}
function applyShow(h){HID=h;var n=SHOWK.filter(function(k){return h[k]}).length;SHOWK.forEach(function(k){B.classList.toggle('hide-'+k,!!h[k])});
if(n||anyGone){[].forEach.call(document.querySelectorAll('section.msg.ai'),function(s){var ks=(s.getAttribute('data-k')||'').split(' ').filter(Boolean);
s.classList.toggle('gone',ks.length>0&&ks.every(function(k){return h[k]}))});anyGone=n>0}
var m=document.getElementById('showm');if(m){[].forEach.call(m.querySelectorAll('input[data-show]'),function(c){c.checked=!h[c.getAttribute('data-show')]});
m.classList.toggle('set',n>0);m.querySelector('summary').textContent=n?'Show: '+(SHOWK.length-n)+' of '+SHOWK.length:'Show'}
var note=document.getElementById('showing');if(note)note.hidden=!n}
function saveShow(){try{localStorage.setItem('pahest-show',SHOWK.filter(function(k){return HID[k]}).join(','))}catch(e){}}
function initShow(){var m=document.getElementById('showm');if(!m)return;var h={},counted=false;
try{(localStorage.getItem('pahest-show')||'').split(',').forEach(function(k){if(SHOWK.indexOf(k)>=0)h[k]=true})}catch(e){}
var meta=document.querySelector('main dl.meta'),note=document.createElement('p');note.className='showing';note.id='showing';note.hidden=true;
note.innerHTML='Some parts of this session are hidden (the <b>Show</b> menu at the top). <button type="button">Show everything</button>';
if(meta)meta.parentNode.insertBefore(note,meta.nextSibling);
note.querySelector('button').onclick=function(){applyShow({});saveShow()};
var Q={you:'.msg.you',say:'.msg.ai .say',think:'.msg.ai details.think,.msg.ai p.note',tool:'.msg.ai .tool,.msg.ai .res',
app:'.ctxb,.anote,.msg.auto,.msg.ai>.mb>details.ctx',pics:'main .msg img,main .ctxb img,main .anote img'};
m.addEventListener('toggle',function(){if(!m.open||counted)return;counted=true;   /* counted when first opened: big pages open faster */
[].forEach.call(m.querySelectorAll('label'),function(l){var k=l.querySelector('input').getAttribute('data-show'),n=document.querySelectorAll(Q[k]).length;
l.querySelector('.n').textContent=n.toLocaleString();if(!n)l.classList.add('none')})});
m.addEventListener('change',function(e){var k=e.target.getAttribute('data-show');if(!k)return;var h2=Object.assign({},HID);h2[k]=!e.target.checked;applyShow(h2);saveShow()});
m.addEventListener('click',function(e){var b=e.target.closest('button[data-preset]');if(!b)return;var keep=b.getAttribute('data-preset').split(',').filter(Boolean),h2={};
if(keep.length)SHOWK.forEach(function(k){if(keep.indexOf(k)<0&&k!='pics')h2[k]=true});applyShow(h2);saveShow()});
document.addEventListener('click',function(e){if(m.open&&!m.contains(e.target))m.open=false});
document.addEventListener('keydown',function(e){if(e.key=='Escape'&&m.open){m.open=false;e.stopImmediatePropagation()}},true);
applyShow(h)}
/* #pic=NAME (from the pictures page): open the place the picture is shown and point at it */
function picKind(i){if((i.getAttribute('alt')||'')=='generated image')return 'generated';
if(i.closest('.msg.auto,.msg.sum,.divider,.ctxb,.anote,details.ctx'))return 'app';return i.closest('.msg.you')?'you':'tool'}
function goPic(){var m=/(?:^#|&)pic=([^&]+)/.exec(location.hash);if(!m)return;var name='/'+decodeURIComponent(m[1]),at=/(?:^#|&)at=(\w+)/.exec(location.hash),img=null;
var all=[].filter.call(document.querySelectorAll('main img'),function(i){var s=i.getAttribute('src')||'';return s.slice(-name.length)==name});
img=all.filter(function(i){return at&&picKind(i)==at[1]})[0]||all[0];   /* where the pictures page says it is (you pasted it, a tool…) */
if(!img)return;if(SHOWK.some(function(k){return HID[k]}))applyShow({});      /* everything, for this visit (not remembered) */
for(var p=img.parentNode;p&&p!=B;p=p.parentNode){if(p.tagName=='DETAILS')p.open=true;
if(p.classList&&p.classList.contains('clip')){p.classList.remove('clip');var x=p.nextElementSibling;if(x&&x.classList.contains('expand'))x.textContent='Collapse'}}
img.classList.add('hit');img.loading='eager';
/* pictures above it load later and push it down: keep it in the middle for a few seconds, until you scroll yourself */
var stop=false,until=Date.now()+4000;function center(){if(stop||Date.now()>until)return;     /* a tall picture: its top under the bar */
img.scrollIntoView({block:img.getBoundingClientRect().height>window.innerHeight-70?'start':'center'})}
['wheel','touchstart','keydown','mousedown'].forEach(function(ev){window.addEventListener(ev,function(){stop=true},{once:true,passive:true})});
center();var main=document.querySelector('main');if(window.ResizeObserver&&main){var ro=new ResizeObserver(center);ro.observe(main);setTimeout(function(){ro.disconnect()},4000)}
else [200,600,1200,2500].forEach(function(t){setTimeout(center,t)})}
function sessionPage(){var st=readState(),listPage=st.from||B.getAttribute('data-list')||'index.html';
var me=ITEMS.filter(function(it){return it[3]==SELF})[0];var seq=ordered(st),i=-1;
for(var k=0;k<seq.length;k++)if(seq[k][3]==SELF){i=k;break}
if(i<0&&me){st={app:me[2],where:'All',surface:'All',kind:kind(me),range:'All',q:''};listPage=B.getAttribute('data-list')||listPage;
seq=ordered(st);for(k=0;k<seq.length;k++)if(seq[k][3]==SELF){i=k;break}}
if(i<0)return;var h=stateHash(st,listPage),back=ROOT+listPage+(stateHash(st)?'#'+stateHash(st):'');
function side(it,cls,label){if(!it)return '<span class="'+cls+'">'+label+'</span>';
return '<a class="'+cls+'" href="'+esc(ROOT+it[3])+'#'+h+'"><b>'+label+'</b><small>'+esc(it[0])+'</small><small>'+esc(shown(it.d))+'</small></a>'}
var html=side(seq[i-1],'prev','← Previous')+'<a class="up" href="'+esc(back)+'">↑ List<small>'+(i+1)+' of '+seq.length+'</small></a>'+side(seq[i+1],'next','Next →');
[].forEach.call(document.querySelectorAll('nav.pn'),function(n){n.innerHTML=html});
document.addEventListener('keydown',function(e){if(e.metaKey||e.ctrlKey||e.altKey||typing(e))return;
if((e.key=='ArrowLeft'||e.key=='k')&&seq[i-1])location.href=ROOT+seq[i-1][3]+'#'+h;
else if((e.key=='ArrowRight'||e.key=='j')&&seq[i+1])location.href=ROOT+seq[i+1][3]+'#'+h;
else if(e.key=='Escape'||e.key=='u')location.href=back})}

function docPage(){var main=document.querySelector('main'),h1=main.querySelector('h1'),st={range:'All'};
location.hash.replace(/^#/,'').split('&').forEach(function(kv){var p=kv.split('=');if(p[0]=='range'&&p[1])st.range=decodeURIComponent(p[1])});
var rows=[].slice.call(document.querySelectorAll('tr')).filter(function(tr){return tr.querySelector('td[data-date]')});
var days=[].slice.call(document.querySelectorAll('h2[data-date]'));if(rows.length+days.length<3)return;
var bar=document.createElement('div');bar.className='filters';bar.innerHTML='<label>Date <select data-key="range"></select></label><span class="count" id="info"></span>';
if(h1&&h1.nextSibling)main.insertBefore(bar,h1.nextSibling);else main.insertBefore(bar,main.firstChild);
var s=bar.querySelector('select'),info=bar.querySelector('#info');
function dateOf(el){return parseIso((el.querySelector('td[data-date]')||el).getAttribute('data-date'))}
function sectionOf(h){var out=[],n=h.nextElementSibling;while(n&&n.tagName!='H2'&&n.tagName!='H1'){out.push(n);n=n.nextElementSibling}return out}
function visible(t){return [].slice.call(t.querySelectorAll('tbody tr')).some(function(r){return r.style.display!='none'})}
function draw(){var shownN=0;rows.forEach(function(tr){var ok=inRange(dateOf(tr),st.range);tr.style.display=ok?'':'none';if(ok)shownN++});
days.forEach(function(h){var ok=inRange(dateOf(h),st.range);h.style.display=ok?'':'none';sectionOf(h).forEach(function(e){e.style.display=ok?'':'none'});if(ok)shownN++});
[].slice.call(main.querySelectorAll('h2:not([data-date])')).forEach(function(h){var sec=sectionOf(h),tables=sec.filter(function(e){return e.className=='table'});
if(!tables.length)return;var any=tables.some(visible);h.style.display=any?'':'none';sec.forEach(function(e){e.style.display=(e.className=='table'?visible(e):any)?'':'none'})});
s.innerHTML=RANGES.map(function(r){var n=rows.concat(days).filter(function(e){return inRange(dateOf(e),r[0])}).length;
return '<option value="'+r[0]+'"'+(st.range==r[0]?' selected':'')+(n||r[0]=='All'||st.range==r[0]?'':' disabled')+'>'+r[1]+' ('+n+')</option>'}).join('');
s.className=st.range=='All'?'':'set';info.textContent=shownN+' shown';try{history.replaceState(null,'',st.range=='All'?location.pathname:'#range='+st.range)}catch(e){}}
s.addEventListener('change',function(){st.range=s.value;draw()});draw()}
})();
"""


def _shown(iso: str) -> str:
    from .render import MONTHS
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", iso or "")
    return f"{m.group(1)} {MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(4)}:{m.group(5)}" if m else ""


def _shown_stamp(stamp: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})", stamp)
    return _shown(f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}") if m else stamp
