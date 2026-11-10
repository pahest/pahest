"""Pahest (Armenian for "reserve"): full local backups of AI chat apps."""

__version__ = "0.1.0"
NAME = "Pahest"
SLOGAN = "local backup for AI apps"
HOME_URL = "https://github.com/emirn/pahest"
ABOUT = "open source (MIT license). Pahest is Armenian for “reserve”."
TOOL_NAMES = ("pahest", "revdoku-backup")     # backup.json "tool": the second is the name before the rename


def tool_version(versions) -> str:
    """The version of this tool recorded in a backup (also one made before the rename)."""
    v = versions if isinstance(versions, dict) else {}
    return str(v.get("pahest") or v.get("revdoku_backup") or "?")
