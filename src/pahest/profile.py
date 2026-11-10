"""Saved answers ("profiles") for automated runs: ~/pahest-backups/profiles/<name>.json.

A profile holds only answers (the backup folder, what to do without zstd), never a secret.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import List

from . import paths

FORMAT = 1
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")


class ProfileError(Exception):
    pass


@dataclass
class Answers:
    backups_folder: str = "~/pahest-backups"
    without_zstd: str = "continue"   # continue (compressed copies only) | stop

    def folder(self) -> Path:
        return Path(os.path.expanduser(self.backups_folder)).resolve()

    def validate(self) -> None:
        if self.without_zstd not in ("continue", "stop"):
            raise ProfileError("without_zstd must be \"continue\" or \"stop\"")
        if not self.backups_folder or not os.path.isabs(os.path.expanduser(self.backups_folder)):
            raise ProfileError("backups_folder must be an absolute path (it may start with ~)")


def profiles_dir() -> Path:
    return paths.settings_home() / "profiles"


def path_for(name: str) -> Path:
    if not NAME_RE.match(name):
        raise ProfileError("a profile name may use letters, digits, - and _ (up to 40 characters)")
    return profiles_dir() / f"{name}.json"


def load(name: str) -> Answers:
    p = path_for(name)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(f"profile \"{name}\" not found ({p}). Run pahest once without --profile "
                           "and answer \"y\" when it offers to save your answers.") from None
    except (OSError, ValueError) as e:
        raise ProfileError(f"could not read {p}: {e}") from e
    known = {f.name for f in fields(Answers)}
    a = Answers(**{k: v for k, v in (data.get("answers") or {}).items() if k in known})
    a.validate()
    return a


def save(name: str, answers: Answers) -> Path:
    answers.validate()
    p = path_for(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "about": "Saved answers for `pahest --profile " + name + "`. No secrets are stored here. "
                 "without_zstd: \"continue\" or \"stop\".",
        "format": FORMAT,
        "answers": asdict(answers),
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return p


def names() -> List[str]:
    d = profiles_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []
