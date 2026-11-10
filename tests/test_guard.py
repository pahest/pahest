"""The read-only guard: during a run the tool can change nothing outside its own folders."""
import contextlib
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path
from unittest import mock

from helpers import TempDirTest, write

from pahest import guard, paths, precheck, versions
from pahest.store import Store, clonefile


class GuardTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.app = self.tmp / "app-data"             # stands for ~/.claude, ~/.codex, ~/Library/...
        self.src = write(self.app / "session.jsonl", "keep me\n")
        self.ok = self.tmp / "backups"
        self.ok.mkdir()
        guard.arm([self.ok])

    def tearDown(self):
        guard.disarm()
        super().tearDown()

    def refused(self, fn, *a, **kw):
        with self.assertRaises(PermissionError):
            fn(*a, **kw)

    def test_writes_inside_own_folders_work(self):
        (self.ok / "a.txt").write_text("x")
        os.rename(self.ok / "a.txt", self.ok / "b.txt")
        os.chmod(self.ok / "b.txt", 0o600)
        os.makedirs(self.ok / "x" / "y")
        write(self.ok / "x" / "y" / "z.txt", "z")
        shutil.rmtree(self.ok / "x")                 # uses dir_fd-relative calls internally
        import tempfile
        d = tempfile.mkdtemp()
        Path(d, "copy.db").write_bytes(b"")
        self.assertEqual(guard.violations, [])

    def test_every_kind_of_change_to_app_data_is_refused(self):
        self.refused(open, self.src, "a")
        self.refused(open, self.src, "r+")
        self.refused(open, self.app / "new.txt", "w")
        self.refused(os.open, str(self.app / "new2.txt"), os.O_CREAT | os.O_WRONLY)
        self.refused(os.remove, self.src)
        self.refused(os.rename, self.src, self.ok / "moved.jsonl")       # moving out = deleting there
        self.refused(os.replace, self.ok, self.app / "x")
        self.refused(os.mkdir, self.app / "sub")
        self.refused(os.chmod, self.src, 0o777)
        self.refused(os.utime, self.src, (0, 0))
        self.refused(shutil.copyfile, self.ok, self.app / "c")
        self.refused(shutil.rmtree, self.app)
        self.refused(os.symlink, "/etc/hosts", self.app / "link")
        if os.name == "posix" and sys.platform == "darwin":
            self.refused(clonefile, self.src, self.app / "clone.jsonl")
        if sys.version_info >= (3, 10):                          # Python 3.9 has no sqlite3 audit event
            self.refused(sqlite3.connect, str(self.app / "state.sqlite"))
            self.refused(sqlite3.connect, (self.app / "state.sqlite").as_uri() + "?mode=ro", uri=True)
        self.assertEqual(self.src.read_text(), "keep me\n")
        self.assertEqual(sorted(p.name for p in self.app.iterdir()), ["session.jsonl"])
        self.assertTrue(guard.violations)

    def test_store_cannot_write_into_app_data(self):
        st = Store(self.app / "backup-here")
        self.refused(st.add_bytes, "x.json", b"{}")
        self.assertFalse((self.app / "backup-here").exists())

    def test_only_zstd_may_run(self):
        self.refused(subprocess.run, ["/bin/ls", str(self.app)], capture_output=True)
        self.refused(subprocess.run, ["/bin/sh", "-c", "true"])
        self.refused(subprocess.run, ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
                     capture_output=True)                                # no Keychain at all
        self.refused(subprocess.run, ["zstd", "-d", str(self.app / "x.zst")], capture_output=True)  # writes next to it
        self.refused(os.system, "true")

    def test_no_network_at_all(self):
        import socket
        with mock.patch.object(urllib.request.OpenerDirector, "_open", side_effect=AssertionError("sent")):
            self.refused(urllib.request.urlopen, "https://claude.ai/api/organizations")   # even a plain GET
        self.refused(socket.socket, socket.AF_INET, socket.SOCK_STREAM)
        self.refused(socket.getaddrinfo, "chatgpt.com", 443)
        self.assertTrue(any("network" in v for v in guard.violations))

    def test_disarm_restores_normal_behaviour(self):
        guard.disarm()
        write(self.app / "after.txt", "fine")
        self.assertTrue((self.app / "after.txt").exists())


class DestinationTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        (self.home / "Library" / "Application Support" / "Google" / "Chrome").mkdir(parents=True)
        (self.home / "Library" / "Mobile Documents" / "com~apple~CloudDocs").mkdir(parents=True)
        (self.home / ".claude").mkdir()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_backups_never_go_into_app_data(self):
        h = self.home
        for bad in (h, h / ".claude" / "backups", h / ".codex" / "b", h / "Library" / "Application Support" / "x",
                    h / "Library" / "Application Support" / "Google" / "Chrome" / "b", h / ".agents" / "b",
                    self.tmp):
            self.assertTrue(precheck.destination_error(bad), bad)
            self.assertFalse(bad.exists() and bad.name == "b")
        for good in (h / "pahest-backups", h / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "rb"):
            self.assertEqual(precheck.destination_error(good), "", good)
        self.assertNotIn(str(h / "Library"), [str(p) for p in paths.cloud_folders()])


class VersionsTest(TempDirTest):
    def test_versions_are_read_without_running_the_programs(self):
        native = write(self.tmp / "share/claude/versions/2.1.319", "#!/bin/sh\necho SHOULD NOT RUN\n")
        os.chmod(native, 0o755)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        os.symlink(native, bindir / "claude")
        rel = self.tmp / "codex/releases/0.162.0-aarch64-apple-darwin"
        write(rel / "codex-package.json", '{"version": "0.162.0"}')
        exe = write(rel / "bin" / "codex", "#!/bin/sh\n")
        os.chmod(exe, 0o755)
        os.symlink(exe, bindir / "codex")
        npm = self.tmp / "npm/lib/node_modules/@openai/codex"
        write(npm / "package.json", '{"name": "@openai/codex", "version": "0.150.2"}')
        js = write(npm / "bin" / "codex.js", "")
        os.chmod(js, 0o755)
        with mock.patch.dict(os.environ, {"PATH": str(bindir)}), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("a program was run")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("a program was run")):
            self.assertEqual(versions.cli_version("claude", [])["version"], "2.1.319")
            self.assertEqual(versions.cli_version("codex", [])["version"], "0.162.0")
            self.assertEqual(versions.cli_version("nothing-here", [js])["version"], "0.150.2")


class ReviewFindingsTest(TempDirTest):
    """Holes an independent review found; each must stay closed."""

    def setUp(self):
        super().setUp()
        self.app = self.tmp / "app-data"
        self.src = write(self.app / "settings.json", '{"keep": true}')
        self.ok = self.tmp / "backups"
        self.ok.mkdir()
        os.symlink(self.ok, self.app / "link-into-backup")     # an app's link that points into the backup
        guard.arm([self.ok])

    def tearDown(self):
        guard.disarm()
        super().tearDown()

    def refused(self, fn, *a, **kw):
        with self.assertRaises(PermissionError):
            fn(*a, **kw)

    def test_links_file_descriptors_and_locks_into_app_data_are_refused(self):
        import fcntl
        self.refused(os.remove, self.app / "link-into-backup")          # the link itself is app data
        self.refused(os.link, self.src, self.ok / "hard")                # same file, two names
        fd = os.open(str(self.src), os.O_RDONLY)
        try:
            self.refused(os.chmod, fd, 0o777)
            self.refused(os.utime, fd, (0, 0))
            self.refused(fcntl.flock, fd, fcntl.LOCK_EX)
        finally:
            os.close(fd)
        if hasattr(os, "O_EXLOCK"):
            self.refused(os.open, str(self.src), os.O_RDONLY | os.O_EXLOCK)
        self.refused(open, "relative-file.txt", "w")
        self.refused(subprocess.run, ["zstd", "-dcq", "--no-progress", "--", "x", "-o", str(self.app / "o")])
        self.assertEqual(self.src.read_text(), '{"keep": true}')
        self.assertTrue((self.app / "link-into-backup").is_symlink())

    def test_backup_folder_typed_in_another_letter_case_still_works(self):
        guard.disarm()
        guard.arm([Path(str(self.ok).upper())])                # macOS: the same folder
        write(self.ok / "x" / "y.txt", "y")
        shutil.rmtree(self.ok / "x")
        self.assertEqual(guard.violations, [])
        self.assertEqual(guard.allowed_roots()[0], os.path.realpath(str(self.ok).upper()))

    def test_pipes_to_allowed_programs_work(self):
        from pahest.store import Zstd
        z = Zstd()
        if not z.program:
            self.skipTest("no zstd program")
        r = subprocess.run([z.program, "-dcq", "--no-progress", "--", str(self.src)], input=b"",
                           capture_output=True)
        self.assertNotEqual(r.returncode, None)                 # it ran (the file is not zstd data)
        self.assertEqual(guard.violations, [])


class UnsafePathTest(TempDirTest):
    def test_paths_from_old_backups_or_servers_cannot_leave_the_backup(self):
        from pahest.store import UnsafePath, load_previous
        app = write(self.tmp / "home" / ".claude" / "settings.json", "ORIGINAL")
        st = Store(self.tmp / "home" / "backups" / "b1")
        for bad in ("../../.claude/settings.json", "/etc/x", "a/../../x", "a\\b", ""):
            with self.assertRaises(UnsafePath):
                st.add_bytes(bad, b"x")
        old = self.tmp / "home" / "backups" / "b0"
        write(old / "checksums.sha256", "0" * 64 + "  claude-code/projects/../../../../.claude/settings.json\n"
              + "1" * 64 + "  claude-code/ok.txt\n")
        prev = load_previous(old)
        self.assertEqual(list(prev.hashes), ["claude-code/ok.txt"])
        self.assertEqual(app.read_text(), "ORIGINAL")


class FolderCaseTest(TempDirTest):
    def test_app_folders_are_recognised_whatever_the_letter_case_or_links(self):
        home = self.tmp / "home"
        (home / ".claude").mkdir(parents=True)
        (home / "Library" / "Application Support" / "Claude").mkdir(parents=True)
        os.symlink(home / ".claude", home / "sneaky-link")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            if os.path.exists(home / ".CLAUDE"):                  # case-insensitive disk (the macOS default)
                self.assertTrue(precheck.destination_error(home / ".CLAUDE" / "bk"))
                self.assertTrue(precheck.destination_error(home / "library" / "Application Support" / "x"))
            self.assertTrue(precheck.destination_error(home / "sneaky-link" / "bk"))
            self.assertTrue(precheck.destination_error(home / ".codex" / "bk"))   # not created yet
            self.assertFalse((home / ".codex").exists())
            self.assertEqual(precheck.destination_error(home / "pahest-backups"), "")
            self.assertIn("home folder", precheck.destination_error(home))

    def test_settings_folder_linked_into_app_data_stops_the_run(self):
        from pahest import cli
        home = self.tmp / "home"
        (home / ".claude").mkdir(parents=True)
        os.symlink(home / ".claude", home / "pahest-backups")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(home)}), contextlib.redirect_stdout(out):
            code = cli.main(["--profile"])
        self.assertEqual(code, 2)
        self.assertIn("cannot use its settings folder", out.getvalue())
        self.assertEqual(os.listdir(home / ".claude"), [])
