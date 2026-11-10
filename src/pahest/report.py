"""Step 5: report.html + backup.json in the backup, copies in logs/, and logs/index.html."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from . import ABOUT, HOME_URL, NAME, TOOL_NAMES, __version__, template, tool_version
from .log import fmt_dur, human

STATUS_CLASS = {"ok": "ok", "completed": "ok", "problems": "warn", "completed with problems": "warn",
                "skipped": "muted", "not found": "muted", "failed": "bad", "interrupted": "bad",
                "cancelled": "muted"}


def _badge(status: str) -> dict:
    """The values of templates/badge.html."""
    return {"status": status, "status_class": STATUS_CLASS.get(status, "muted")}


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


def _items(items, limit: int = 200) -> Optional[dict]:
    """The values of templates/list_items.html (None: nothing to list)."""
    if not items:
        return None
    return {"count": f"{len(items):,}", "items": list(items[:limit]),
            "more": f"{len(items) - limit:,}" if len(items) > limit else ""}


def _page(title: str, version) -> dict:
    """What every report page needs (templates/report_head.html and report_foot.html)."""
    return {"title": title, "tool": NAME, "home_url": HOME_URL, "about": ABOUT, "tool_version": version or "?"}


def _result(r: dict) -> dict:
    """One part of the backup, as shown in the table and under Details."""
    if r.get("status") in ("skipped", "not found") and not r.get("files"):
        since = "—"
    elif r.get("compared_to"):
        since = f"{r['new']:,} new, {r['changed']:,} changed, {r['carried_items'] or r['carried']:,} deleted at source (kept)"
    else:
        since = "first backup"
    return dict(
        _badge(r["status"]), name=r["name"], part=r["part"], folder=r["folder"], since=since,
        items=f"{r['items']:,} {r['item_label']}" if r.get("items") is not None else "—",
        files=f"{r['files']:,}", size=human(r["bytes"]), took=fmt_dur(r["seconds"]),
        sources=r.get("sources") or [],
        counts=[{"label": k.capitalize(), "value": f"{v:,}"} for k, v in (r.get("counts") or {}).items()],
        compared_to=r.get("compared_to") or "", new=f"{r.get('new') or 0:,}", changed=f"{r.get('changed') or 0:,}",
        carried=f"{r.get('carried') or 0:,}",
        failed=_items(r.get("failed")), notes=_items(r.get("notes")), unavailable=_items(r.get("unavailable")),
        info=_items(r.get("info")))


def _versions(vers: dict) -> List[dict]:
    rows = []
    for group in ("apps", "cli"):
        for name, v in (vers.get(group) or {}).items():
            if v:
                rows.append({"name": name, "path": v.get("path") or "", "where": "",
                             "version": f"{v.get('version')}" + (f" ({v['bundle_id']})" if v.get("bundle_id") else "")})
    rows += [{"name": name, "version": v, "path": "", "where": "written in the data"}
             for name, v in (vers.get("in_data") or {}).items() if v]
    rows.append({"name": "pahest", "version": tool_version(vers), "path": "",
                 "where": f"{vers.get('python_path')} (Python {vers.get('python')}), {vers.get('os')}"})
    return rows


def html_report(data: dict, base_href: Optional[str] = None) -> str:
    """report.html (templates/report.html) from the data of backup.json."""
    results = data.get("results") or []
    ver = data.get("verification") or {}
    totals = data.get("totals") or {}
    pre = data.get("prechecks") or {}
    vers = data.get("versions") or {}
    ro = data.get("read_only") or {}
    refused = ro.get("refused") or []
    wrote = ro.get("wrote_only_in") or []
    problems = list(data.get("problems") or [])
    problems += [f"{r['name']} — {p}" for r in results for p in r.get("failed") or []]
    problems += [f"Verification — {p}" for p in (ver.get("problems") or [])]
    count = lambda key: f"{ver.get(key, 0):,}"                      # noqa: E731
    values = dict(
        _page(f"AI backup {data.get('name')}", tool_version(vers)), **_badge(data.get("status", "")),
        base_href=base_href or "", name=data.get("name"),
        started=str(data.get("started") or "").replace("T", " "), took=fmt_dur(data.get("seconds") or 0),
        how=f"profile {data.get('profile')}" if data.get("profile") else "interactive",
        backup_folder=data.get("backup_folder"),
        regenerated=[{"at": str(rg.get("at") or "").replace("T", " "), "version": rg.get("version"),
                      "pages": f"{rg.get('pages', 0):,}",
                      "problems": f"{len(rg['problems']):,}" if rg.get("problems") else ""}
                     for rg in (data.get("regenerated") or [])[-1:]],       # the latest rebuild
        rebuilds=len(data.get("regenerated") or []),
        stats=[{"value": value, "label": label} for label, value in (
            ("files", f"{totals.get('files', 0):,}"), ("total size", human(totals.get("bytes", 0))),
            ("written in full (not cloned)", human(totals.get("new_space", 0))),
            ("deleted at source, kept", f"{totals.get('deleted_at_source', 0):,}"),
            ("verification", "passed" if ver and not ver.get("problems") else
             ("not run" if not ver else f"{len(ver.get('problems'))} problems")))],
        results=[_result(r) for r in results],
        problems=_items(problems),
        verification=dict(
            _badge("ok" if not ver.get("problems") else "problems"), files=count("files"),
            size=human(ver.get("bytes", 0)), json_ok=count("json_ok"), jsonl_ok=count("jsonl_ok"),
            zst_ok=count("zst_ok"), sqlite_ok=count("sqlite_ok"), images_ok=count("images_ok"),
            took=fmt_dur(ver.get("seconds", 0)), warnings=_items(ver.get("warnings"))) if ver else None,
        versions=_versions(vers),
        clones="yes" if pre.get("clone_ok") else "no (full copies)", free=human(pre.get("free", 0)),
        previous=pre.get("previous") or "", precheck_warnings=pre.get("warnings") or [],
        read_only=dict(
            _badge("failed" if refused else "ok"), refused_count=f"{len(refused):,}" if refused else "",
            refused=refused[:50],
            wrote_only_in=[{"path": x, "last": i == len(wrote) - 1} for i, x in enumerate(wrote)]) if ro else None,
        deleted_at_source=totals.get("deleted_at_source") or 0)
    return template.render("report.html", values)


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
    rows = []
    for d in runs:
        name = d.get("name", "")
        t = d.get("totals") or {}
        ver = d.get("verification") or {}
        nprob = sum(len(r.get("failed") or []) for r in d.get("results") or []) + len(ver.get("problems") or []) \
            + len(d.get("problems") or [])
        folder = d.get("backup_folder") or ""
        rows.append(dict(
            _badge(d.get("status", "")), name=name, mode=d.get("mode", ""), took=fmt_dur(d.get("seconds") or 0),
            files=f"{t.get('files', 0):,}", size=human(t.get("bytes", 0)), problems=f"{nprob:,}",
            folder=folder, folder_href=Path(folder).as_uri() if folder else "",
            log=(logs_dir / f"{name}.log").exists()))
    page = template.render("logs.html", dict(_page("AI backups", __version__), base_href="", count=len(runs), runs=rows))
    path = logs_dir / "index.html"
    path.write_text(page, encoding="utf-8", errors="replace")
    return path
