"""Step 5: report.html + backup.json in the backup, copies in logs/, and logs/index.html."""
from __future__ import annotations

import html
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from . import ABOUT, HOME_URL, NAME, TOOL_NAMES, __version__, tool_version
from .log import fmt_dur, human

STATUS_CLASS = {"ok": "ok", "completed": "ok", "problems": "warn", "completed with problems": "warn",
                "skipped": "muted", "not found": "muted", "failed": "bad", "interrupted": "bad",
                "cancelled": "muted"}

CSS = """
:root{--bg:#fbfaf8;--fg:#1d1d1f;--muted:#6e6e73;--line:#e3e1dc;--card:#fff;--ok:#1f7a3a;--warn:#9a6200;
--bad:#b3261e;--okbg:#e7f4ea;--warnbg:#fdf1dc;--badbg:#fbe9e7;--mutedbg:#efeeeb;--link:#0b57d0;--code:#f3f2ef}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161618;--fg:#ececec;--muted:#a1a1a6;
--line:#2e2e32;--card:#1e1e21;--ok:#6fd08c;--warn:#f0b75a;--bad:#ff8a80;--okbg:#1b3524;--warnbg:#3a2c12;
--badbg:#3d1d1a;--mutedbg:#2a2a2d;--link:#8ab4f8;--code:#26262a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 60px}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 10px}h3{font-size:15px;margin:18px 0 6px}
.sub{color:var(--muted)}a{color:var(--link)}code{background:var(--code);padding:1px 5px;border-radius:4px;
font:13px ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:13px;font-weight:600}
.ok{color:var(--ok);background:var(--okbg)}.warn{color:var(--warn);background:var(--warnbg)}
.bad{color:var(--bad);background:var(--badbg)}.muted{color:var(--muted);background:var(--mutedbg)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:13px}td.num{text-align:right;font-variant-numeric:tabular-nums}
ul{margin:6px 0;padding-left:20px}li{margin:3px 0}details summary{cursor:pointer;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.stat b{display:block;font-size:20px}.stat span{color:var(--muted);font-size:13px}
.brand{font-weight:700;margin:0 0 12px}.brand a{color:var(--fg);text-decoration:none}.made{margin-top:28px;font-size:13px}
"""


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def badge(status: str) -> str:
    return f'<span class="badge {STATUS_CLASS.get(status, "muted")}">{e(status)}</span>'


def result_dict(r) -> dict:
    d = asdict(r)
    d.pop("expected", None)
    d.pop("uncertain", None)
    return d


def build_data(meta: dict, versions: dict, prechecks: dict, results: list, verification, totals: dict) -> dict:
    return {
        "tool": "pahest", "format": 1, **meta,
        "versions": versions, "prechecks": prechecks,
        "results": [result_dict(r) for r in results],
        "verification": asdict(verification) if verification else None,
        "totals": totals,
    }


def _list(items: List[str], limit: int = 200) -> str:
    if not items:
        return ""
    lis = "".join(f"<li>{e(x)}</li>" for x in items[:limit])
    more = f"<li>… and {len(items) - limit:,} more (see backup.json)</li>" if len(items) > limit else ""
    return f"<ul>{lis}{more}</ul>"


BRAND = f"<div class=brand><a href='{HOME_URL}' rel='noopener'>{NAME}</a></div>"


def made_with(version) -> str:
    return (f"<p class='sub made'>Made with <a href='{HOME_URL}' rel='noopener'>{NAME}</a> {e(version or '?')}, "
            f"{ABOUT}</p>")


def html_report(data: dict, base_href: Optional[str] = None) -> str:
    status = data.get("status", "")
    results = data.get("results") or []
    ver = data.get("verification") or {}
    totals = data.get("totals") or {}
    pre = data.get("prechecks") or {}
    out = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
           "<meta name=viewport content='width=device-width,initial-scale=1'>",
           f"<title>AI backup {e(data.get('name'))}</title>"]
    if base_href:
        out.append(f"<base href='{e(base_href)}'>")
    out.append(f"<style>{CSS}</style></head><body><main>{BRAND}")
    out.append(f"<h1>AI backup {e(data.get('name'))} {badge(status)}</h1>")
    how = f"profile {data.get('profile')}" if data.get("profile") else "interactive"
    started = str(data.get("started") or "").replace("T", " ")
    out.append(f"<div class=sub>Started {e(started)} · took {e(fmt_dur(data.get('seconds') or 0))} · "
               f"{e(how)}</div>")
    out.append(f"<p>Backup folder: <a href='./'><code>{e(data.get('backup_folder'))}</code></a></p>")
    for rg in data.get("regenerated") or []:
        out.append(f"<p class=sub>Pages rebuilt {e(str(rg.get('at') or '').replace('T', ' '))} with pahest "
                   f"{e(rg.get('version'))} ({rg.get('pages', 0):,} files"
                   + (f", {len(rg.get('problems') or []):,} problems" if rg.get("problems") else "") + ").</p>")

    out.append("<div class=grid>")
    for label, value in (("files", f"{totals.get('files', 0):,}"), ("total size", human(totals.get("bytes", 0))),
                         ("written in full (not cloned)", human(totals.get("new_space", 0))),
                         ("deleted at source, kept", f"{totals.get('deleted_at_source', 0):,}"),
                         ("verification", "passed" if ver and not ver.get("problems") else
                          ("not run" if not ver else f"{len(ver.get('problems'))} problems"))):
        out.append(f"<div class=stat><b>{e(value)}</b><span>{e(label)}</span></div>")
    out.append("</div>")

    out.append("<h2>What was backed up</h2><div class='card scroll'><table><tr><th>Source</th><th>Part</th>"
               "<th>Status</th><th class=num>Items</th><th class=num>Files</th><th class=num>Size</th>"
               "<th>Since previous backup</th><th>Folder</th></tr>")
    for r in results:
        items = f"{r['items']:,} {r['item_label']}" if r.get("items") is not None else "—"
        if r.get("status") in ("skipped", "not found") and not r.get("files"):
            since = "—"
        elif r.get("compared_to"):
            since = (f"{r['new']:,} new, {r['changed']:,} changed, {r['carried_items'] or r['carried']:,} "
                     f"deleted at source (kept)")
        else:
            since = "first backup"
        out.append(f"<tr><td>{e(r['name'])}</td><td>{e(r['part'])}</td><td>{badge(r['status'])}</td>"
                   f"<td class=num>{e(items)}</td><td class=num>{r['files']:,}</td>"
                   f"<td class=num>{e(human(r['bytes']))}</td><td>{e(since)}</td>"
                   f"<td><a href='{e(r['folder'])}/'><code>{e(r['folder'])}/</code></a></td></tr>")
    out.append("</table></div>")

    problems = list(data.get("problems") or [])
    problems += [f"{r['name']} — {p}" for r in results for p in r.get("failed") or []]
    problems += [f"Verification — {p}" for p in (ver.get("problems") or [])]
    if problems:
        out.append(f"<h2>Problems ({len(problems):,})</h2><div class=card>{_list(problems)}</div>")

    out.append("<h2>Verification</h2><div class=card>")
    if ver:
        out.append(f"<p>{badge('ok' if not ver.get('problems') else 'problems')} "
                   f"{ver.get('files', 0):,} files ({e(human(ver.get('bytes', 0)))}) were read back from the backup "
                   f"and matched their SHA-256 checksums. Checked: {ver.get('json_ok', 0):,} JSON files, "
                   f"{ver.get('jsonl_ok', 0):,} JSONL files (every line), {ver.get('zst_ok', 0):,} compressed files "
                   f"(decompressed and compared with the plain copy), {ver.get('sqlite_ok', 0):,} databases "
                   f"(integrity check), {ver.get('images_ok', 0):,} images. Took {e(fmt_dur(ver.get('seconds', 0)))}.</p>")
        if ver.get("warnings"):
            out.append(f"<details><summary>{len(ver['warnings']):,} warnings</summary>{_list(ver['warnings'])}</details>")
        out.append("<p class=sub>Check it again any time: <code>cd \"" + e(data.get("backup_folder")) +
                   "\" &amp;&amp; shasum -a 256 -c checksums.sha256</code></p>")
    else:
        out.append("<p>Verification did not run.</p>")
    out.append("</div>")

    out.append("<h2>Details</h2>")
    for r in results:
        out.append(f"<div class=card><h3>{e(r['name'])} — {e(r['part'])} {badge(r['status'])}</h3><ul>")
        out.append(f"<li>Folder: <a href='{e(r['folder'])}/'><code>{e(r['folder'])}/</code></a> "
                   f"({r['files']:,} files, {e(human(r['bytes']))}, {e(fmt_dur(r['seconds']))})</li>")
        for s in r.get("sources") or []:
            out.append(f"<li>Source: <code>{e(s)}</code></li>")
        for k, v in (r.get("counts") or {}).items():
            out.append(f"<li>{e(k.capitalize())}: {v:,}</li>")
        if r.get("compared_to"):
            out.append(f"<li>Compared with the backup of {e(r['compared_to'])}: {r['new']:,} new files, "
                       f"{r['changed']:,} changed, {r['carried']:,} files kept that the source no longer has</li>")
        out.append("</ul>")
        if r.get("failed"):
            out.append(f"<p><b>Problems</b></p>{_list(r['failed'])}")
        if r.get("notes"):
            out.append(f"<p><b>Notes</b></p>{_list(r['notes'])}")
        if r.get("unavailable"):
            out.append(f"<details><summary>{len(r['unavailable']):,} items the server no longer had</summary>"
                       f"{_list(r['unavailable'])}</details>")
        if r.get("info"):
            out.append(f"<details><summary>About these files</summary>{_list(r['info'])}</details>")
        out.append("</div>")

    out.append("<h2>App versions</h2><div class='card scroll'><table><tr><th>What</th><th>Version</th><th>Where</th></tr>")
    vers = dict(data.get("versions") or {})
    vers["pahest"] = tool_version(vers)
    for group in ("apps", "cli"):
        for name, v in (vers.get(group) or {}).items():
            if v:
                out.append(f"<tr><td>{e(name)}</td><td>{e(v.get('version'))}"
                           f"{(' (' + e(v.get('bundle_id')) + ')') if v.get('bundle_id') else ''}</td>"
                           f"<td><code>{e(v.get('path'))}</code></td></tr>")
    for name, v in (vers.get("in_data") or {}).items():
        if v:
            out.append(f"<tr><td>{e(name)}</td><td>{e(v)}</td><td>written in the data</td></tr>")
    out.append(f"<tr><td>pahest</td><td>{e(vers.get('pahest'))}</td><td>{e(vers.get('python_path'))} "
               f"(Python {e(vers.get('python'))}), {e(vers.get('os'))}</td></tr>")
    out.append("</table></div>")

    out.append("<h2>Prechecks</h2><div class=card><ul>")
    out.append(f"<li>Clones: {'yes' if pre.get('clone_ok') else 'no (full copies)'} · free space before: "
               f"{e(human(pre.get('free', 0)))}</li>")
    if pre.get("previous"):
        out.append(f"<li>Previous backup: {e(pre['previous'])}</li>")
    for w in pre.get("warnings") or []:
        out.append(f"<li>{e(w)}</li>")
    out.append("</ul></div>")

    ro = data.get("read_only") or {}
    if ro:
        refused = ro.get("refused") or []
        out.append("<h2>Read-only check</h2><div class=card><ul>")
        if refused:
            out.append(f"<li>{badge('failed')} The guard refused {len(refused):,} attempts to change files or send "
                       "something other than a read request. Nothing was changed, but this is a bug: please report it.</li>")
            out += [f"<li><code>{e(x)}</code></li>" for x in refused[:50]]
        else:
            out.append(f"<li>{badge('ok')} The apps' data was only read, and nothing was sent over the network. Files were written only "
                       "in: " + ", ".join(f"<code>{e(x)}</code>" for x in ro.get("wrote_only_in") or []) + "</li>")
        out.append("</ul></div>")
    out.append("<h2>Files in this backup folder</h2><div class=card><ul>"
               "<li><a href='index.html'>index.html</a> — start here: all your chats as web pages, with search</li>"
               "<li><a href='README.md'>README.md</a> — what each folder holds</li>"
               "<li><a href='readable/'>readable/</a> — every local session as Markdown, pictures as files</li>"
               "<li><a href='backup.log'>backup.log</a> — everything shown in the terminal during the run</li>"
               "<li><a href='app-versions.json'>app-versions.json</a> — versions of the apps whose data was read</li>"
               "<li><a href='checksums.sha256'>checksums.sha256</a> — SHA-256 of every file</li>"
               "<li><a href='backup.json'>backup.json</a> — this report as data</li>")
    if totals.get("deleted_at_source"):
        out.append("<li><a href='deleted-at-source.txt'>deleted-at-source.txt</a> — files the apps deleted that "
                   "this backup still keeps, with the date each one went missing</li>")
    out.append("</ul></div>")
    out.append(made_with(vers.get("pahest")) + "</main></body></html>")
    return "\n".join(out)


def write_report(backup_root: Path, logs_dir: Path, data: dict) -> Dict[str, Path]:
    name = data["name"]
    paths = {}
    (backup_root / "report.html").write_text(html_report(data), encoding="utf-8", errors="replace")
    (backup_root / "backup.json").write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    for f in ("report.html", "backup.json"):
        os.chmod(backup_root / f, 0o600)
    paths["report"] = backup_root / "report.html"
    logs_dir.mkdir(parents=True, exist_ok=True)
    base = Path(data["backup_folder"]).as_uri() + "/"
    (logs_dir / f"{name}.html").write_text(html_report(data, base_href=base), encoding="utf-8", errors="replace")
    (logs_dir / f"{name}.json").write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    paths["log_report"] = logs_dir / f"{name}.html"
    write_logs_index(logs_dir)
    paths["index"] = logs_dir / "index.html"
    return paths


def write_logs_index(logs_dir: Path) -> Path:
    runs = []
    for p in logs_dir.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("tool") in TOOL_NAMES:
            runs.append(d)
    runs.sort(key=lambda d: d.get("name", ""), reverse=True)
    out = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
           "<meta name=viewport content='width=device-width,initial-scale=1'>",
           f"<title>AI backups</title><style>{CSS}</style></head><body><main>{BRAND}",
           "<h1>AI backups</h1>",
           f"<div class=sub>{len(runs)} runs, newest first. Every run is a full backup in its own folder.</div>",
           "<h2>Runs</h2><div class='card scroll'><table><tr><th>Backup</th><th>Status</th><th>Mode</th>"
           "<th class=num>Took</th><th class=num>Files</th><th class=num>Size</th><th class=num>Problems</th>"
           "<th>Folder</th><th>Log</th></tr>"]
    for d in runs:
        name = d.get("name", "")
        t = d.get("totals") or {}
        ver = d.get("verification") or {}
        nprob = sum(len(r.get("failed") or []) for r in d.get("results") or []) + len(ver.get("problems") or []) \
            + len(d.get("problems") or [])
        folder = d.get("backup_folder") or ""
        folder_link = f"<a href='{e(Path(folder).as_uri())}/'><code>{e(folder)}</code></a>" if folder else "—"
        log_link = f"<a href='{e(name)}.log'>log</a>" if (logs_dir / f"{name}.log").exists() else ""
        out.append(f"<tr><td><a href='{e(name)}.html'>{e(name)}</a></td><td>{badge(d.get('status', ''))}</td>"
                   f"<td>{e(d.get('mode', ''))}</td><td class=num>{e(fmt_dur(d.get('seconds') or 0))}</td>"
                   f"<td class=num>{t.get('files', 0):,}</td><td class=num>{e(human(t.get('bytes', 0)))}</td>"
                   f"<td class=num>{nprob:,}</td><td>{folder_link}</td><td>{log_link}</td></tr>")
    out.append("</table></div>" + made_with(__version__) + "</main></body></html>")
    path = logs_dir / "index.html"
    path.write_text("\n".join(out), encoding="utf-8", errors="replace")
    return path
