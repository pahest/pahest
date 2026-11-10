import contextlib
import io
import json
import os
import pty
import re
import select
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

from helpers import ROOT, TempDirTest, write

from pahest import cli, profile
from pahest.store import Zstd

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")


class FakeHomeTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        h = self.home
        write(h / ".claude/projects/-p/s1.jsonl", '{"type":"user","version":"2.1.0"}\n')
        write(h / ".claude/projects/-p/s2.jsonl", '{"type":"user"}\n')
        write(h / ".claude/history.jsonl", '{"display":"hi"}\n')
        write(h / ".claude/settings.json", '{"cleanupPeriodDays": 3650}')
        write(h / ".claude/.credentials.json", "SECRET-CRED")
        write(h / ".codex/history.jsonl", '{"t":1}\n')
        write(h / ".codex/auth.json", '{"tokens": "SECRET-AUTH"}')
        z = Zstd()
        plain = b'{"type":"session_meta","payload":{"cli_version":"0.162.0"}}\n'
        if z.module:
            write(h / ".codex/sessions/2026/11/08/rollout-a.jsonl.zst", z.module.compress(plain))
        elif z.program:
            out = subprocess.run([z.program, "-q", "-c"], input=plain, capture_output=True, check=True).stdout
            write(h / ".codex/sessions/2026/11/08/rollout-a.jsonl.zst", out)
        else:
            write(h / ".codex/sessions/2026/11/08/rollout-a.jsonl", plain)
        self.env = mock.patch.dict(os.environ, {"HOME": str(h), "PATH": "/usr/bin:/bin"})
        self.env.start()
        for k in ("CLAUDE_CONFIG_DIR", "CODEX_HOME"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def save_profile(self, **kw):
        a = profile.Answers(**kw)
        profile.save("default", a)

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def backups(self):
        root = self.home / "pahest-backups"
        return sorted(d for d in root.iterdir() if d.is_dir() and d.name[:4].isdigit())


class ProfileRunTest(FakeHomeTest):
    def test_profile_run_makes_full_verified_backup(self):
        self.save_profile()
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 0, out)
        [b] = self.backups()
        self.assertTrue(STAMP.match(b.name))
        for name in ("report.html", "backup.log", "backup.json", "app-versions.json", "checksums.sha256",
                     "claude-code/projects/-p/s1.jsonl", "codex/history.jsonl"):
            self.assertTrue((b / name).exists(), name)
        if Zstd().available:
            self.assertTrue((b / "codex/sessions/2026/11/08/rollout-a.jsonl").exists())
        r = subprocess.run(["shasum", "-a", "256", "-c", "checksums.sha256"], cwd=b, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        everything = b"".join(p.read_bytes() for p in b.rglob("*") if p.is_file())
        self.assertNotIn(b"SECRET-CRED", everything)
        self.assertNotIn(b"SECRET-AUTH", everything)
        logs = self.home / "pahest-backups" / "logs"
        for name in (f"{b.name}.log", f"{b.name}.html", f"{b.name}.json", "index.html"):
            self.assertTrue((logs / name).exists(), name)
        log_text = (b / "backup.log").read_text()
        self.assertIn("── Verification", log_text)
        self.assertIn("Prechecks", log_text)
        data = json.loads((b / "backup.json").read_text())
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["mode"], "profile")
        self.assertEqual(data["verification"]["problems"], [])
        self.assertIn("apps", json.loads((b / "app-versions.json").read_text()))
        self.assertIn(b.name, (logs / "index.html").read_text())

    def test_second_run_carries_deleted_session(self):
        self.save_profile()
        self.assertEqual(self.run_cli("--profile")[0], 0)
        (self.home / ".claude/projects/-p/s1.jsonl").unlink()
        time.sleep(1.1)
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 0, out)
        first, second = self.backups()
        self.assertTrue((second / "claude-code/projects/-p/s1.jsonl").exists())
        self.assertIn("claude-code/projects/-p/s1.jsonl", (second / "deleted-at-source.txt").read_text())
        data = json.loads((second / "backup.json").read_text())
        cc = [r for r in data["results"] if r["id"] == "claude-code"][0]
        self.assertEqual(cc["compared_to"], first.name)
        self.assertEqual(cc["items"], 2)

    def test_leftover_in_progress_folder_is_renamed(self):
        self.save_profile()
        left = self.home / "pahest-backups" / "2026-01-01-00-00-00-in-progress"
        left.mkdir(parents=True)
        self.assertEqual(self.run_cli("--profile")[0], 0)
        self.assertFalse(left.exists())
        self.assertTrue((self.home / "pahest-backups" / "2026-01-01-00-00-00-interrupted").exists())

    def test_interrupt_marks_backup_and_leaves_no_temp_files(self):
        self.save_profile()

        def boom(ctx):
            write(ctx.store.root / "codex" / ".half.jsonl.rb-tmp-1", "partial")
            raise KeyboardInterrupt

        with mock.patch("pahest.sources.codex.run", side_effect=boom):
            code, out = self.run_cli("--profile")
        self.assertEqual(code, 130, out)
        [b] = self.backups()
        self.assertTrue(b.name.endswith("-interrupted"))
        self.assertTrue((b / "report.html").exists())
        self.assertFalse(list(b.rglob("*.rb-tmp-*")))
        self.assertEqual(json.loads((b / "backup.json").read_text())["status"], "interrupted")
        # An interrupted backup is never used as "previous": the next run still compares with nothing.
        self.assertEqual(self.run_cli("--profile")[0], 0)

    def test_lock_prevents_second_run(self):
        self.save_profile()
        lock = self.home / "pahest-backups" / cli.LOCK_NAME
        lock.write_text(str(os.getpid()))
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 2)
        self.assertIn("still working", out)

    def test_missing_profile(self):
        code, out = self.run_cli("--profile", "nope")
        self.assertEqual(code, 2)
        self.assertIn("not found", out)

    def test_no_terminal_without_profile(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("--profile", out)

    def test_backups_folder_from_profile(self):
        other = self.tmp / "elsewhere"
        self.save_profile(backups_folder=str(other))
        self.assertEqual(self.run_cli("--profile")[0], 0)
        self.assertEqual(len([d for d in other.iterdir() if STAMP.match(d.name)]), 1)
        self.assertTrue((self.home / "pahest-backups" / "logs" / "index.html").exists())


class RobustnessTest(FakeHomeTest):
    def test_symlinked_claude_files_are_backed_up(self):
        h = self.home
        dot = self.tmp / "dotfiles"
        write(dot / "CLAUDE.md", "my memory")
        os.symlink(dot / "CLAUDE.md", h / ".claude" / "CLAUDE.md")
        real_projects = self.tmp / "elsewhere-projects"
        (h / ".claude" / "projects").rename(real_projects)
        os.symlink(real_projects, h / ".claude" / "projects")
        self.save_profile()
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 0, out)
        [b] = self.backups()
        self.assertEqual((b / "claude-code/config/CLAUDE.md").read_text(), "my memory")
        self.assertTrue((b / "claude-code/projects/-p/s1.jsonl").exists())
        self.assertFalse((b / "claude-code/config/CLAUDE.md").is_symlink())

    def test_truncated_compressed_session_is_reported_not_fatal(self):
        if not Zstd().available:
            self.skipTest("no zstd")
        write(self.home / ".codex/sessions/2026/11/08/rollout-bad.jsonl.zst", b"\x28\xb5\x2f\xfd" + b"\x00" * 30)
        self.save_profile()
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 1, out)
        [b] = self.backups()
        self.assertTrue(STAMP.match(b.name))
        data = json.loads((b / "backup.json").read_text())
        codex_res = [r for r in data["results"] if r["id"] == "codex"][0]
        self.assertEqual(codex_res["status"], "problems")
        self.assertTrue(any("rollout-bad" in f for f in codex_res["failed"]))
        self.assertTrue((b / "codex/sessions/2026/11/08/rollout-bad.jsonl.zst").exists())  # original kept
        self.assertFalse(list(b.rglob(".rb-tmp*")))

    def test_unexpected_error_in_one_source_does_not_stop_the_others(self):
        self.save_profile()
        with mock.patch("pahest.sources.claude_code.run", side_effect=ValueError("boom")):
            code, out = self.run_cli("--profile")
        self.assertEqual(code, 1, out)
        [b] = self.backups()
        self.assertTrue((b / "codex/history.jsonl").exists())
        self.assertTrue((b / "report.html").exists())
        self.assertIn("boom", (b / "backup.json").read_text())

    def test_unusable_backups_folder_stops_cleanly(self):
        locked = self.tmp / "locked"
        locked.mkdir()
        os.chmod(locked, 0o500)
        self.save_profile(backups_folder=str(locked / "backups"))
        try:
            code, out = self.run_cli("--profile")
        finally:
            os.chmod(locked, 0o700)
        self.assertEqual(code, 2, out)
        self.assertIn("cannot be used", out)

    def test_disconnected_disk_is_not_created_on_the_boot_disk(self):
        self.save_profile(backups_folder="/Volumes/pahest-test-disk-that-is-not-there/backups")
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 2, out)
        self.assertIn("not connected", out)
        self.assertFalse(Path("/Volumes/pahest-test-disk-that-is-not-there").exists())

    def test_token_typed_at_a_menu_is_never_logged(self):
        from pahest.log import Log
        out = io.StringIO()
        log = Log(out)
        log.attach(self.tmp / "t.log")
        with mock.patch("builtins.input", side_effect=["sk-ant-sid01-SECRETVALUE", "x", "p"]):
            self.assertEqual(log.ask("[p] paste, [s] skip:", "s", choices="ps"), "p")
        log.detach_all()
        text = (self.tmp / "t.log").read_text()
        self.assertNotIn("SECRETVALUE", text)
        self.assertNotIn("SECRETVALUE", out.getvalue())
        self.assertIn("not logged", text)


class SecondReviewCliTest(FakeHomeTest):
    def test_unreadable_folder_is_a_problem_and_its_files_are_kept_unmarked(self):
        self.save_profile()
        self.assertEqual(self.run_cli("--profile")[0], 0)
        locked = self.home / ".claude/projects/-p"
        os.chmod(locked, 0o000)
        try:
            time.sleep(1.1)
            code, out = self.run_cli("--profile")
        finally:
            os.chmod(locked, 0o700)
        self.assertEqual(code, 1, out)
        second = self.backups()[-1]
        self.assertTrue((second / "claude-code/projects/-p/s1.jsonl").exists())
        self.assertFalse((second / "deleted-at-source.txt").exists())
        self.assertIn("could not read the folder", (second / "backup.json").read_text())

    def test_crash_in_a_source_keeps_its_previous_copy(self):
        self.save_profile()
        self.assertEqual(self.run_cli("--profile")[0], 0)
        time.sleep(1.1)
        with mock.patch("pahest.sources.claude_code.copy_items", side_effect=RuntimeError("bug")):
            code, out = self.run_cli("--profile")
        self.assertEqual(code, 1, out)
        second = self.backups()[-1]
        self.assertTrue((second / "claude-code/projects/-p/s1.jsonl").exists())
        self.assertFalse((second / "deleted-at-source.txt").exists())
        data = json.loads((second / "backup.json").read_text())
        cc = [r for r in data["results"] if r["id"] == "claude-code"][0]
        self.assertEqual(cc["status"], "failed")
        self.assertTrue(cc["kept_previous"])

    def test_backup_without_checksums_is_not_used_as_previous(self):
        self.save_profile()
        self.assertEqual(self.run_cli("--profile")[0], 0)
        (self.backups()[0] / "checksums.sha256").unlink()
        time.sleep(1.1)
        self.assertEqual(self.run_cli("--profile")[0], 0)
        data = json.loads((self.backups()[-1] / "backup.json").read_text())
        self.assertTrue(all(not r["compared_to"] for r in data["results"]))

    def test_folder_that_contains_the_app_data_is_refused(self):
        self.save_profile(backups_folder=str(self.home))
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 2, out)
        self.assertIn("your home folder", out)
        self.save_profile(backups_folder=str(self.home.parent))
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 2, out)
        self.assertIn("contains ~/.claude", out)

    def test_database_retry_leaves_no_stale_wal(self):
        import sqlite3
        db = self.home / ".codex/state_5.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("create table t(x)")
        con.commit()
        con.close()
        wal = self.home / ".codex/state_5.sqlite-wal"
        wal.write_bytes(b"")   # a -wal that Codex will "checkpoint away" during the copy
        from pahest.sources import codex as codex_mod
        real_sig = codex_mod._db_signature
        calls = {"n": 0}

        def sig(path):
            calls["n"] += 1
            if calls["n"] == 2 and wal.exists():   # after the first copy: Codex quits and removes the -wal
                from pahest import guard
                guard._armed = False                # this is Codex acting, not the backup tool
                try:
                    wal.unlink()
                    db.touch()
                finally:
                    guard._armed = True
            return real_sig(path)
        self.save_profile()
        with mock.patch.object(codex_mod, "_db_signature", side_effect=sig):
            code, out = self.run_cli("--profile")
        self.assertEqual(code, 0, out)
        [b] = self.backups()
        self.assertTrue((b / "codex/databases/state_5.sqlite").exists())
        self.assertFalse((b / "codex/databases/state_5.sqlite-wal").exists())


class ThirdReviewCliTest(FakeHomeTest):
    def test_login_files_are_never_copied_even_through_links(self):
        os.makedirs(self.home / ".claude/skills", exist_ok=True)
        os.symlink(self.home / ".codex", self.home / ".claude/skills/codex-link")   # leads to auth.json
        write(self.home / ".claude/sessions/1.key", "SESSION-KEY-SECRET")
        os.symlink(self.home / ".claude/sessions", self.home / ".claude/skills/sessions-link")
        self.save_profile()
        # Tests run under /private/var (a "not your data" place); switch that rule off here so
        # the login-file backstop itself is what keeps the secrets out.
        with mock.patch("pahest.sources.local.not_data_roots", return_value=[]):
            code, out = self.run_cli("--profile")
        self.assertEqual(code, 0, out)
        [b] = self.backups()
        everything = b"".join(p.read_bytes() for p in b.rglob("*") if p.is_file())
        self.assertNotIn(b"SECRET-AUTH", everything)
        self.assertNotIn(b"SESSION-KEY-SECRET", everything)
        self.assertIn("login file, never copied", (b / "backup.json").read_text())
        self.assertTrue((b / "claude-code/config/skills/codex-link/history.jsonl").exists())  # the rest is kept

    def test_unreadable_compressed_session_keeps_its_plain_copy(self):
        if not Zstd().available:
            self.skipTest("no zstd")
        self.save_profile()
        self.assertEqual(self.run_cli("--profile")[0], 0)
        zst = self.home / ".codex/sessions/2026/11/08/rollout-a.jsonl.zst"
        os.chmod(zst, 0o000)
        try:
            time.sleep(1.1)
            code, out = self.run_cli("--profile")
        finally:
            os.chmod(zst, 0o644)
        self.assertEqual(code, 1, out)
        second = self.backups()[-1]
        self.assertTrue((second / "codex/sessions/2026/11/08/rollout-a.jsonl.zst").exists())
        self.assertTrue((second / "codex/sessions/2026/11/08/rollout-a.jsonl").exists())
        self.assertFalse((second / "deleted-at-source.txt").exists())


class LocalOnlyCliTest(FakeHomeTest):
    def test_a_run_never_touches_the_network_or_the_keychain(self):
        import socket
        self.save_profile()
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("network")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("a program was run")):
            code, out = self.run_cli("--profile")
        self.assertEqual(code, 0, out)
        self.assertIn("never goes online", out)
        self.assertNotIn("Keychain", out)
        data = json.loads((self.backups()[-1] / "backup.json").read_text())
        self.assertEqual({r["id"] for r in data["results"]},
                         {"claude-code", "codex", "claude-desktop-local", "readable"})
        self.assertEqual(data["read_only"]["refused"], [])

    def test_old_profile_with_login_answers_still_loads(self):
        p = profile.path_for("default")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"format": 1, "answers": {"backups_folder": "~/pahest-backups",
                                                          "claude_login": "auto", "chatgpt_login": "auto"}}))
        self.assertEqual(profile.load("default").backups_folder, "~/pahest-backups")


class SourceManifestTest(FakeHomeTest):
    def test_original_paths_and_attributes_are_recorded(self):
        import base64
        import ctypes
        h = self.home
        session = h / ".claude/projects/-p/s1.jsonl"
        os.chmod(session, 0o640)
        os.utime(session, ns=(1_700_000_000_123_456_789, 1_700_000_000_123_456_789))
        libc = ctypes.CDLL(None)
        libc.setxattr(os.fsencode(str(session)), b"com.example.note", b"kept", 4, 0, 0)
        write(self.tmp / "dotfiles/skills/s/SKILL.md", "skill")
        os.symlink(self.tmp / "dotfiles/skills", h / ".claude/skills")
        self.save_profile()
        code, out = self.run_cli("--profile")
        self.assertEqual(code, 0, out)
        b = self.backups()[-1]
        lines = [json.loads(x) for x in (b / "source-manifest.jsonl").read_text().splitlines()]
        head, recs = lines[0], {r["rel"]: r for r in lines[1:]}
        self.assertEqual(head["home"], str(h))
        r = recs["claude-code/projects/-p/s1.jsonl"]
        self.assertEqual(r["path"], str(session))
        self.assertEqual((r["kind"], r["mode"], r["mtime_ns"]), ("file", "0640", 1_700_000_000_123_456_789))
        self.assertEqual(base64.b64decode(r["xattrs"]["com.example.note"]), b"kept")
        sums = dict(reversed(line.split("  ", 1)) for line in (b / "checksums.sha256").read_text().splitlines())
        self.assertEqual(r["sha256"], sums["claude-code/projects/-p/s1.jsonl"])
        self.assertEqual(recs["claude-code/projects"]["kind"], "dir")
        link = recs["claude-code/config/skills#link"]
        self.assertEqual((link["kind"], link["target"]), ("link", str(self.tmp / "dotfiles/skills")))
        skill = recs["claude-code/config/skills/s/SKILL.md"]
        self.assertEqual(skill["path"], str(h / ".claude/skills/s/SKILL.md"))     # as the app sees it
        self.assertTrue(skill["real"].endswith("dotfiles/skills/s/SKILL.md"))
        plain = [x for x in recs.values() if x.get("kind") == "derived"]
        if Zstd().available:
            self.assertTrue(plain and plain[0]["from"].endswith(".jsonl.zst"))
        self.assertIn("source-manifest.jsonl", sums)                              # covered by the checksums
        self.assertFalse(any(k.startswith("readable/") for k in recs))            # made by the tool: no original


def snapshot(root: Path, skip: str) -> dict:
    """Everything about every file and folder under root (except `skip`)."""
    import hashlib
    out = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != skip]
        for name in dirs + files:
            p = Path(dirpath) / name
            st = os.lstat(p)
            entry = (st.st_mode, st.st_size, st.st_mtime_ns, st.st_ino)
            if os.path.islink(p):
                entry += (os.readlink(p),)
            elif p.is_file():
                entry += (hashlib.sha256(p.read_bytes()).hexdigest(),)
            out[str(p.relative_to(root))] = entry
    return out


class ReadOnlyTest(FakeHomeTest):
    def test_a_full_run_changes_nothing_in_the_apps_folders(self):
        import sqlite3

        from pahest import guard
        h = self.home
        write(h / ".claude/plans/p.md", "# plan")
        write(h / "Library/Application Support/Claude/local-agent-mode-sessions/s/t.jsonl", '{"type":"user"}\n')
        write(h / "Library/Application Support/Claude/claude_desktop_config.json", "{}")
        (h / ".codex").mkdir(exist_ok=True)
        con = sqlite3.connect(str(h / ".codex/state_5.sqlite"))      # Codex is running: WAL file is live
        con.execute("pragma journal_mode=wal")
        con.execute("create table threads(id, title)")
        con.execute("insert into threads values (1, 'hello')")
        con.commit()
        try:
            before = snapshot(h, "pahest-backups")
            self.assertTrue(any(k.endswith("state_5.sqlite-wal") for k in before))
            self.save_profile()
            code, out = self.run_cli("--profile")
            after = snapshot(h, "pahest-backups")
        finally:
            con.close()
        self.assertIn(code, (0, 1), out)
        self.assertEqual(before, after)                     # not one byte, time or permission changed
        self.assertEqual(guard.violations, [])
        data = json.loads((self.backups()[-1] / "backup.json").read_text())
        self.assertEqual(data["read_only"]["refused"], [])
        self.assertTrue(all(r.startswith(str(self.tmp.resolve())) or "pahest-" in r
                            for r in data["read_only"]["wrote_only_in"]), data["read_only"])
        self.assertTrue((self.backups()[-1] / "codex/databases/state_5.sqlite").exists())


class RegenerateTest(FakeHomeTest):
    """--regenerate: the pages of an existing backup are rebuilt; nothing else changes."""

    def backup(self) -> Path:
        self.save_profile()
        code, out = self.run_cli("--profile")
        self.assertIn(code, (0, 1), out)
        return self.backups()[-1]

    def assert_checksums_match(self, b: Path):
        import hashlib
        for line in (b / "checksums.sha256").read_text().splitlines():
            sha, rel = line[:64], line[66:]
            self.assertEqual(hashlib.sha256((b / rel).read_bytes()).hexdigest(), sha, rel)

    def test_a_backup_made_before_the_tool_was_renamed_is_rebuilt(self):
        b = self.backup()
        data = json.loads((b / "backup.json").read_text())
        data["tool"] = "revdoku-backup"                                    # the tool's name until 2026-11-10
        data["versions"]["revdoku_backup"] = data["versions"].pop("pahest")
        (b / "backup.json").write_text(json.dumps(data))
        code, out = self.run_cli("--regenerate", str(b))
        self.assertEqual(code, 0, out)
        self.assertIn("with revdoku-backup 0.1.0", out)
        self.assertIn('Made with <a href="https://github.com/emirn/pahest"', (b / "report.html").read_text())
        self.assert_checksums_match(b)

    def test_pages_are_rebuilt_in_place_and_nothing_else_changes(self):
        from pahest import guard, regenerate
        b = self.backup()
        before = snapshot(b, "readable")
        apps_before = snapshot(self.home, "pahest-backups")
        (b / "index.html").write_text("a page from an older version")
        write(b / "readable/stale.html", "left over from an older version")
        code, out = self.run_cli("--regenerate", str(b / "index.html"))      # the folder, or a file in it
        self.assertEqual(code, 0, out)
        self.assertIn("Pages rebuilt", out)
        self.assertIn('data-page="list"', (b / "index.html").read_text())
        self.assertFalse((b / "readable/stale.html").exists())              # old pages are replaced, not mixed
        self.assertFalse((b / regenerate.ASIDE).exists())
        self.assert_checksums_match(b)
        after = snapshot(b, "readable")
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        self.assertTrue(changed <= {"index.html", "README.md", "checksums.sha256", "backup.json", "report.html",
                                    "backup.log"}, changed)             # the apps' copies are untouched
        self.assertEqual(apps_before, snapshot(self.home, "pahest-backups"))
        self.assertEqual(guard.violations, [])
        data = json.loads((b / "backup.json").read_text())
        self.assertEqual(len(data["regenerated"]), 1)
        self.assertIn("Pages last rebuilt", (b / "report.html").read_text())
        self.assertIn("Rebuild the pages", (b / "backup.log").read_text())
        code, out = self.run_cli("--regenerate")                              # default: the newest backup
        self.assertEqual(code, 0, out)
        self.assertIn(str(b), out)
        self.assertEqual(len(json.loads((b / "backup.json").read_text())["regenerated"]), 2)

    def test_a_failure_puts_the_old_pages_back(self):
        from pahest import readable, regenerate
        b = self.backup()
        before = snapshot(b, "")
        with mock.patch.object(readable, "run", side_effect=RuntimeError("boom")):
            code, out = self.run_cli("--regenerate", str(b))
        self.assertEqual(code, 1, out)
        self.assertIn("old pages are put back", out)
        after = snapshot(b, "")
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        self.assertEqual(changed - {"backup.log"}, set())
        self.assertFalse((b / regenerate.ASIDE).exists())
        self.assert_checksums_match(b)
        with mock.patch.object(regenerate, "write_checksums", side_effect=OSError(28, "No space left on device")):
            code, out = self.run_cli("--regenerate", str(b))              # fails after the pages were made
        self.assertEqual(code, 1, out)
        after = snapshot(b, "")
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        self.assertEqual(changed - {"backup.log"}, set())
        self.assert_checksums_match(b)

    def test_an_unfinished_run_is_undone_first(self):
        from pahest import regenerate
        b = self.backup()
        old_index = (b / "index.html").read_text()
        aside = b / regenerate.ASIDE                     # as if the computer stopped in the middle
        aside.mkdir()
        os.rename(b / "readable", aside / "readable")
        os.rename(b / "index.html", aside / "index.html")
        write(b / "readable/half.html", "half written")
        with mock.patch.object(regenerate.readable, "run", side_effect=KeyboardInterrupt):
            code, out = self.run_cli("--regenerate", str(b))
        self.assertEqual(code, 130, out)
        self.assertIn("did not finish", out)
        self.assertFalse((b / "readable/half.html").exists())
        self.assertEqual((b / "index.html").read_text(), old_index)
        self.assertFalse(aside.exists())
        self.assert_checksums_match(b)

    def test_only_finished_backups_are_accepted(self):
        b = self.backup()
        code, out = self.run_cli("--regenerate", str(self.tmp))
        self.assertEqual(code, 2, out)
        self.assertIn("not a pahest backup", out)
        busy = b.with_name(b.name + "-in-progress")
        b.rename(busy)
        code, out = self.run_cli("--regenerate", str(busy))
        self.assertEqual(code, 2, out)
        self.assertIn("still being made", out)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("--regenerate", "--profile")


class InteractiveTest(FakeHomeTest):
    def test_questions_through_a_terminal(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NO_COLOR="1")
        master, slave = pty.openpty()
        proc = subprocess.Popen([sys.executable, "-m", "pahest"], stdin=slave, stdout=slave,
                                stderr=slave, env=env, close_fds=True)
        os.close(slave)
        answers = [("Backup folder", "\n"),
                   ("Save these answers", "y\n"), ("Profile name", "\n"), ("Start the backup now", "y\n")]
        buf = b""
        deadline = time.time() + 120
        while time.time() < deadline:
            r, _, _ = select.select([master], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                if answers and answers[0][0].encode() in buf.split(b"\n")[-1]:
                    os.write(master, answers.pop(0)[1].encode())
            elif proc.poll() is not None:
                break
        proc.wait(timeout=30)
        os.close(master)
        text = buf.decode("utf-8", "replace")
        self.assertEqual(answers, [], text[-3000:])
        self.assertEqual(proc.returncode, 0, text[-3000:])
        saved = profile.load("default")
        self.assertEqual(saved.backups_folder, "~/pahest-backups")
        [b] = self.backups()
        log = (b / "backup.log").read_text()
        self.assertIn("? Start the backup now? [Y/n] y", log)
        self.assertIn("── Questions", log)
