import sqlite3

from helpers import TempDirTest, quiet_log, write

from pahest import verify
from pahest.result import Result
from pahest.store import Store, Zstd


class VerifyTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp / "b")
        self.res = Result("x", "x", "X", "part", "chatgpt")

    def run_verify(self):
        return verify.run(self.store, [self.res], quiet_log(), Zstd())

    def test_clean_backup_passes(self):
        self.store.add_bytes("chatgpt/a.json", b'{"a": 1}')
        self.store.add_bytes("claude-code/s.jsonl", b'{"a":1}\n{"b":2}\n')
        db = self.tmp / "src.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("create table t(x)")
        con.commit()
        con.close()
        self.store.add_file(db, "codex/databases/state_5.sqlite")
        v = self.run_verify()
        self.assertEqual(v.problems, [])
        self.assertEqual((v.json_ok, v.jsonl_ok, v.sqlite_ok), (1, 1, 1))
        self.assertEqual(list((self.tmp / "b" / "codex" / "databases").iterdir())[0].name, "state_5.sqlite")

    def test_changed_file_is_a_problem(self):
        self.store.add_bytes("chatgpt/a.json", b'{"a": 1}')
        (self.tmp / "b" / "chatgpt" / "a.json").write_bytes(b'{"a": 2}')
        v = self.run_verify()
        self.assertTrue(any("does not match" in p for p in v.problems))

    def test_missing_expected_and_leftover_tmp(self):
        self.res.expected.append("chatgpt/never-written.json")
        write(self.tmp / "b" / "chatgpt" / ".x.json.rb-tmp-1", "partial")
        v = self.run_verify()
        self.assertTrue(any("expected but not saved" in p for p in v.problems))
        self.assertTrue(any("leftover temporary" in p for p in v.problems))

    def test_invalid_json_from_download_is_a_problem_but_live_jsonl_tail_is_a_warning(self):
        self.store.add_bytes("chatgpt/bad.json", b'{"a": ')
        self.store.add_bytes("claude-code/live.jsonl", b'{"a":1}\n{"b":')
        v = self.run_verify()
        self.assertTrue(any("not valid JSON: chatgpt/bad.json" in p for p in v.problems))
        self.assertFalse(any("live.jsonl" in p for p in v.problems))
        self.assertTrue(any("live.jsonl" in w and "still writing" in w for w in v.warnings))

    def test_zst_plain_copy_mismatch(self):
        z = Zstd()
        if not z.available:
            self.skipTest("no zstd")
        plain = b'{"a":1}\n'
        if z.module:
            comp = z.module.compress(plain)
        else:
            import subprocess
            comp = subprocess.run([z.program, "-q", "-c"], input=plain, capture_output=True, check=True).stdout
        self.store.add_bytes("codex/sessions/rollout-x.jsonl.zst", comp)
        self.store.add_bytes("codex/sessions/rollout-x.jsonl", b'{"a":2}\n')
        v = self.run_verify()
        self.assertTrue(any("plain copy differs" in p for p in v.problems))

    def test_unknown_file_is_a_warning(self):
        write(self.tmp / "b" / "chatgpt" / "stray.txt", "x")
        v = self.run_verify()
        self.assertEqual(v.problems, [])
        self.assertTrue(any("stray.txt" in w for w in v.warnings))


class VerifyPathTest(TempDirTest):
    def test_sqlite_check_in_folder_with_special_characters(self):
        store = Store(self.tmp / "Backup #3 ?x%20" / "b")
        db = self.tmp / "src.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("create table t(x)")
        con.commit()
        con.close()
        store.add_file(db, "codex/databases/state_5.sqlite")
        v = verify.run(store, [], quiet_log(), Zstd())
        self.assertEqual(v.problems, [])
        self.assertEqual(v.sqlite_ok, 1)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["Backup #3 ?x%20", "src.sqlite"])

    def test_corrupt_sqlite_is_a_problem(self):
        store = Store(self.tmp / "b")
        store.add_bytes("codex/databases/state_5.sqlite", b"SQLite format 3\x00" + b"\xff" * 4000)
        v = verify.run(store, [], quiet_log(), Zstd())
        self.assertTrue(any("database copy is not readable" in p for p in v.problems))
