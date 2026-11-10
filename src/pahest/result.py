"""Shared data types: the per-part result, and the context each source gets."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .log import Log
from .store import Previous, Store, Zstd


@dataclass
class Result:
    id: str                         # unique part id, e.g. "claude-code"
    source: str                     # claude-code | codex | claude-desktop
    name: str                       # "Claude desktop"
    part: str                       # "local sessions"
    folder: str                     # path inside the backup, e.g. "claude-code"
    item_label: str = "files"
    status: str = "ok"              # ok | problems | failed | skipped | not found | interrupted
    items: Optional[int] = None     # sessions / chats in this backup (incl. carried forward)
    files: int = 0
    bytes: int = 0
    new: int = 0                    # files not in the previous backup
    changed: int = 0                # files that differ from the previous backup
    carried: int = 0                # files carried forward (deleted at source)
    carried_items: int = 0          # sessions / chats deleted at source, still kept
    kept_previous: bool = False     # whole part copied from the previous backup
    compared_to: str = ""           # name of the previous backup used for new/changed counts
    sources: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)   # projects, artifacts, archived chats, …
    expected: List[str] = field(default_factory=list)      # paths that must exist (verification)
    uncertain: List[str] = field(default_factory=list)     # paths/prefixes that could not be read this run
    failed: List[str] = field(default_factory=list)        # real problems
    unavailable: List[str] = field(default_factory=list)   # expected gaps (expired files, …)
    notes: List[str] = field(default_factory=list)         # warnings: console + report
    info: List[str] = field(default_factory=list)          # background facts: report only
    seconds: float = 0.0

    def problem(self, text: str) -> None:
        self.failed.append(text)

    def finish_status(self) -> None:
        if self.status == "ok" and self.failed:
            self.status = "problems"


@dataclass
class Ctx:
    store: Store
    log: Log
    previous: Dict[str, Optional[Previous]]   # part id -> previous good backup of that part
    today: str
    zstd: Zstd
    extra: Dict[str, Any] = field(default_factory=dict)

    def prev(self, part_id: str) -> Optional[Previous]:
        return self.previous.get(part_id)
