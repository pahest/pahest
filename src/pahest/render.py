"""Small helpers shared by the readable copies: JSON and UTF-8 output, safe file names, and dates."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional


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
