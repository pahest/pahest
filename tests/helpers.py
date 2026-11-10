"""Test helpers: a quiet log, temporary folders and small file-system fixtures."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Pages show local time; the tests expect UTC+4 whatever the computer's own time zone is.
os.environ["TZ"] = "Etc/GMT-4"
time.tzset()

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
