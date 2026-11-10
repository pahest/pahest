import hashlib
import os
import time
from pathlib import Path

from helpers import TempDirTest, write

from pahest.store import (Store, Zstd, iter_files, load_previous, read_checksums,
                                  write_checksums, write_deleted_list)


class StoreTest(TempDirTest):
    def test_add_file_records_hash_and_private_mode(self):
        src = write(self.tmp / "src" / "a.txt", "hello")
        os.chmod(src, 0o644)
        old = time.time() - 3600
        os.utime(src, (old, old))
        st = Store(self.tmp / "b1")
        e = st.add_file(src, "x/a.txt")
        out = self.tmp / "b1" / "x" / "a.txt"
        self.assertEqual(out.read_text(), "hello")
        self.assertEqual(e.sha, hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(e.size, 5)
        self.assertIn(e.how, ("clone-source", "copy"))
        self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")
        self.assertAlmostEqual(out.stat().st_mtime, old, delta=1)

    def test_clone_is_independent_of_source(self):
        src = write(self.tmp / "src" / "a.txt", "one")
        st = Store(self.tmp / "b1")
        st.add_file(src, "a.txt")
        src.write_text("two-changed")
        self.assertEqual((self.tmp / "b1" / "a.txt").read_text(), "one")

    def test_identical_content_reuses_previous_backup(self):
        st1 = Store(self.tmp / "b1")
        st1.add_bytes("c/x.json", b'{"a":1}')
        write_checksums(st1)
        prev = load_previous(self.tmp / "b1")
        st2 = Store(self.tmp / "b2")
        e = st2.add_bytes("c/x.json", b'{"a":1}', prev)
        self.assertIn(e.how, ("clone-previous", "write"))
        e2 = st2.add_bytes("c/y.json", b'{"a":2}', prev)
        self.assertEqual(e2.how, "write")
        self.assertEqual((self.tmp / "b2" / "c" / "x.json").read_bytes(), b'{"a":1}')

    def test_carry_missing_and_deleted_list(self):
        st1 = Store(self.tmp / "b1")
        st1.add_bytes("src/keep.txt", b"k")
        st1.add_bytes("src/gone.txt", b"g")
        st1.add_bytes("other/x.txt", b"x")
        write_checksums(st1)
        prev = load_previous(self.tmp / "b1")
        st2 = Store(self.tmp / "b2")
        st2.add_bytes("src/keep.txt", b"k")
        carried = st2.carry_missing(prev, ["src"], "2026-11-08")
        self.assertEqual(carried, ["src/gone.txt"])
        self.assertEqual(st2.deleted, {"src/gone.txt": "2026-11-08"})
        self.assertNotIn("other/x.txt", st2.manifest)
        write_deleted_list(st2)
        write_checksums(st2)
        # A third backup keeps the original date.
        prev2 = load_previous(self.tmp / "b2")
        self.assertEqual(prev2.deleted, {"src/gone.txt": "2026-11-08"})
        st3 = Store(self.tmp / "b3")
        st3.carry_missing(prev2, ["src"], "2026-12-01")
        self.assertEqual(st3.deleted["src/gone.txt"], "2026-11-08")

    def test_carry_refuses_corrupted_previous_file(self):
        st1 = Store(self.tmp / "b1")
        st1.add_bytes("src/a.txt", b"original")
        write_checksums(st1)
        (self.tmp / "b1" / "src" / "a.txt").write_bytes(b"tampered")
        prev = load_previous(self.tmp / "b1")
        st2 = Store(self.tmp / "b2")
        with self.assertRaises(OSError):
            st2.carry(prev, "src/a.txt", "2026-11-08")

    def test_checksums_roundtrip_with_spaces_in_names(self):
        st = Store(self.tmp / "b1")
        st.add_bytes("dir with space/file name.txt", b"z")
        p = write_checksums(st)
        got = read_checksums(p)
        self.assertEqual(got, {"dir with space/file name.txt": hashlib.sha256(b"z").hexdigest()})

    def test_iter_files_skips_symlinks_and_ds_store(self):
        write(self.tmp / "s" / "a.txt", "a")
        write(self.tmp / "s" / ".DS_Store", "x")
        os.symlink(self.tmp / "s" / "a.txt", self.tmp / "s" / "link.txt")
        os.symlink(self.tmp / "s", self.tmp / "s" / "loop")
        names = sorted(rel.as_posix() for _p, rel, _st in iter_files(self.tmp / "s"))
        self.assertEqual(names, ["a.txt"])

    def test_zstd_stream_matches_plain(self):
        z = Zstd()
        if not z.available:
            self.skipTest("no zstd available")
        plain = b'{"a":1}\n' * 1000
        src = self.tmp / "x.jsonl.zst"
        if z.module:
            src.write_bytes(z.module.compress(plain))
        else:
            import subprocess
            subprocess.run([z.program, "-q", "-o", str(src)], input=plain, check=True)
        st = Store(self.tmp / "b")
        e = st.add_stream("x.jsonl", lambda: z.open(src))
        self.assertEqual(e.sha, hashlib.sha256(plain).hexdigest())


class StoreFixesTest(TempDirTest):
    def test_long_file_name_can_be_saved(self):
        name = "p" * 245 + ".md"
        src = write(self.tmp / "src" / name, "plan")
        st = Store(self.tmp / "b")
        st.add_file(src, f"claude-code/plans/{name}")
        self.assertEqual((self.tmp / "b" / "claude-code" / "plans" / name).read_text(), "plan")

    def test_failed_stream_leaves_no_temp_file(self):
        class Broken:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                raise OSError("decompression failed")

        st = Store(self.tmp / "b")
        with self.assertRaises(OSError):
            st.add_stream("codex/x.jsonl", Broken)
        self.assertEqual([p.name for p in (self.tmp / "b" / "codex").iterdir()], [])

    def test_truncated_zst_is_an_oserror(self):
        z = Zstd()
        if not z.available:
            self.skipTest("no zstd")
        bad = write(self.tmp / "bad.jsonl.zst", b"\x28\xb5\x2f\xfd" + b"\x00" * 20)
        st = Store(self.tmp / "b")
        with self.assertRaises(OSError):
            st.add_stream("x.jsonl", lambda: z.open(bad))
        self.assertFalse(list((self.tmp / "b").glob(".rb-tmp*")))

    def test_symlinks_are_followed_once_and_never_into_the_backups(self):
        real = self.tmp / "dotfiles"
        write(real / "CLAUDE.md", "memory")
        write(real / "skills" / "s1" / "SKILL.md", "skill")
        src = self.tmp / "src"
        src.mkdir()
        os.symlink(real / "CLAUDE.md", src / "CLAUDE.md")
        os.symlink(real / "skills", src / "skills")
        os.symlink(src, src / "loop")                       # loop back to itself
        backups = self.tmp / "backups"
        write(backups / "old" / "x.txt", "old backup")
        os.symlink(backups, src / "backups-link")           # must never be walked
        os.symlink(self.tmp / "missing", src / "broken")
        write(self.tmp / "runtime" / "node_modules" / "pkg" / "index.js", "x")
        os.symlink(self.tmp / "runtime" / "node_modules", src / "node_modules")   # installed software
        skipped = []
        got = {rel.as_posix(): p for p, rel, _st in
               iter_files(src, follow=True, avoid_quietly=[backups], skipped=skipped)}
        self.assertEqual(sorted(got), ["CLAUDE.md", "skills/s1/SKILL.md"])
        self.assertEqual(got["CLAUDE.md"], Path(os.path.realpath(real / "CLAUDE.md")))
        self.assertTrue(any("broken" in s for s in skipped))
        self.assertTrue(any("loop" in s for s in skipped))
        self.assertTrue(any("node_modules" in s and "installed software" in s for s in skipped))
        self.assertFalse(any("backups-link" in s for s in skipped))
        # A starting folder inside a "not your data" location is still backed up; only links inside are judged.
        self.assertEqual(len(list(iter_files(real, follow=True, avoid=[self.tmp]))), 2)
        # A symlinked root folder works too.
        os.symlink(real, self.tmp / "linked-root")
        self.assertEqual(len(list(iter_files(self.tmp / "linked-root", follow=True))), 2)
        # Without follow=True links are ignored (used when reading backups).
        self.assertEqual(list(iter_files(src)), [])

    def test_keep_previous_copy_keeps_deleted_dates(self):
        st1 = Store(self.tmp / "b1")
        st1.add_bytes("src/old.txt", b"o")
        st1.deleted["src/old.txt"] = "2026-01-01"
        write_checksums(st1)
        write_deleted_list(st1)
        prev = load_previous(self.tmp / "b1")
        st2 = Store(self.tmp / "b2")
        st2.carry(prev, "src/old.txt", "2026-11-09", deleted=False)
        self.assertEqual(st2.deleted, {"src/old.txt": "2026-01-01"})


class WalkOrderTest(TempDirTest):
    def test_real_folder_wins_over_a_link_that_sorts_first(self):
        src = self.tmp / "src"
        write(src / "b" / "x.txt", "x")
        os.symlink(src / "b", src / "a-link")
        skipped = []
        rels = [rel.as_posix() for _p, rel, _st in iter_files(src, follow=True, skipped=skipped)]
        self.assertEqual(rels, ["b/x.txt"])
        self.assertTrue(any("a-link" in s and "already in the backup" in s for s in skipped))

    def test_unreadable_folder_is_reported(self):
        src = self.tmp / "src"
        write(src / "ok" / "a.txt", "a")
        write(src / "locked" / "b.txt", "b")
        os.chmod(src / "locked", 0o000)
        try:
            bad = []
            rels = [rel.as_posix() for _p, rel, _st in iter_files(src, follow=True, unreadable=bad)]
        finally:
            os.chmod(src / "locked", 0o700)
        self.assertEqual(rels, ["ok/a.txt"])
        self.assertEqual([b.as_posix() for b in bad], ["locked"])


class LinkSafetyTest(TempDirTest):
    def test_link_to_a_folder_that_contains_the_backups_never_walks_into_them(self):
        docs = self.tmp / "Documents"
        write(docs / "skill" / "SKILL.md", "s")
        write(docs / "pahest-backups" / "2026-01-01-00-00-00" / "huge.bin", "old backup")
        src = self.tmp / "src"
        src.mkdir()
        os.symlink(docs, src / "docs-link")
        rels = sorted(rel.as_posix() for _p, rel, _st in
                      iter_files(src, follow=True, avoid_quietly=[docs / "pahest-backups"]))
        self.assertEqual(rels, ["docs-link/skill/SKILL.md"])

    def test_link_to_an_ancestor_is_a_loop(self):
        root = self.tmp / "claude"
        write(root / ".credentials.json", "SECRET")
        write(root / "skills" / "s" / "SKILL.md", "s")
        os.symlink(root, root / "skills" / "up")
        skipped = []
        rels = sorted(rel.as_posix() for _p, rel, _st in iter_files(root / "skills", follow=True, skipped=skipped))
        self.assertEqual(rels, ["s/SKILL.md"])
        self.assertTrue(any("loop" in s for s in skipped))

    def test_readable_but_not_searchable_folder_is_reported(self):
        src = self.tmp / "src"
        write(src / "half" / "a.txt", "a")
        os.chmod(src / "half", 0o444)
        try:
            bad = []
            rels = [rel.as_posix() for _p, rel, _st in iter_files(src, follow=True, unreadable=bad)]
        finally:
            os.chmod(src / "half", 0o755)
        self.assertEqual(rels, [])
        self.assertEqual([b.as_posix() for b in bad], ["half/a.txt"])
