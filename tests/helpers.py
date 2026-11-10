"""Test helpers: a quiet log, temporary folders and small file-system fixtures."""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pahest.log import Log  # noqa: E402

def quiet_log() -> Log:
    return Log(io.StringIO())


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pahest-test-")
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()


def write(path: Path, data: Union[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode()
    path.write_bytes(data)
    return path


def make_chromium_cookie_db(path: Path, rows: List[tuple], meta_version: int = 24) -> Path:
    """rows: (host_key, name, encrypted_value bytes, value str, expires_utc, last_access_utc)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR)")
    con.execute("INSERT INTO meta VALUES('version', ?)", (str(meta_version),))
    con.execute("CREATE TABLE cookies(host_key TEXT, name TEXT, encrypted_value BLOB, value TEXT, "
                "expires_utc INTEGER, last_access_utc INTEGER)")
    con.executemany("INSERT INTO cookies VALUES(?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


def chromium_time(unix: float) -> int:
    return int((unix + 11644473600) * 1_000_000)
