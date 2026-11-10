import unittest

import helpers  # noqa: F401  (adds src/ to sys.path)
from fixtures import chatgpt_conv, claude_conv

from pahest import render


class ClaudeRenderTest(unittest.TestCase):
    def test_artifacts_versions_and_created_files(self):
        arts, refs, problems = render.claude_artifacts(claude_conv())
        self.assertEqual(problems, [])
        self.assertEqual(arts["itinerary"]["versions"], ["# Day 1\nLouvre", "# Day 1\nLouvre, Orsay"])
        self.assertEqual(arts["itinerary"]["ext"], "md")
        f = arts["file:/mnt/user-data/outputs/budget.csv"]
        self.assertEqual(f["ext"], "csv")
        self.assertEqual(f["versions"][0], "item,eur\nhotel,300\n")
        self.assertEqual(refs[("m4", 0)], ("itinerary", 2))

    def test_markdown_shows_current_branch_only(self):
        conv = claude_conv()
        arts, refs, _ = render.claude_artifacts(conv)
        md = render.claude_markdown(conv, {"f1": "../files/f1/photo.png"}, refs, arts, "../artifacts/c1", {})
        self.assertIn("# Plan a trip", md)
        self.assertIn("Add Orsay", md)
        self.assertNotIn("OLD BRANCH QUESTION", md)
        self.assertIn("Branches:** 2", md)
        self.assertIn("![photo.png](../files/f1/photo.png)", md)
        self.assertIn("../artifacts/c1/itinerary/v2.md", md)
        self.assertIn("Attachment: notes.txt", md)

    def test_failed_update_is_reported(self):
        conv = claude_conv()
        conv["chat_messages"][3]["content"][0]["input"]["old_str"] = "NOT THERE"
        _arts, _refs, problems = render.claude_artifacts(conv)
        self.assertTrue(problems)


class ChatGPTRenderTest(unittest.TestCase):
    def test_canvas_rebuilt_with_updates(self):
        docs, problems = render.chatgpt_canvas(chatgpt_conv())
        self.assertEqual(problems, [])
        d = list(docs.values())[0]
        self.assertEqual(d["title"], "Essay")
        self.assertEqual(d["versions"], ["Hello world", "Hello there"])
        self.assertEqual(d["ext"], "md")

    def test_file_and_sandbox_refs(self):
        conv = chatgpt_conv()
        ids = {fid for fid, _n, _m in render.chatgpt_file_refs(conv)}
        self.assertEqual(ids, {"file-UPLOAD1", "file_GEN1"})
        self.assertEqual(render.chatgpt_sandbox_refs(conv), [("a3", "/mnt/data/out.csv")])

    def test_markdown_current_branch_and_images(self):
        conv = chatgpt_conv()
        md = render.chatgpt_markdown(conv, {"file_GEN1": "../files/file_GEN1/x.png",
                                            "file-UPLOAD1": "../files/file-UPLOAD1/me.png"}, {"Archived": "yes"})
        self.assertIn("Here is the picture.", md)
        self.assertNotIn("OLD BRANCH ANSWER", md)
        self.assertIn("![image](../files/file_GEN1/x.png)", md)
        self.assertIn("Attachment: [me.png](../files/file-UPLOAD1/me.png)", md)
        self.assertIn("**Archived:** yes", md)
        self.assertNotIn("is_visually_hidden", md)


class FixesTest(unittest.TestCase):
    def test_long_created_file_paths_get_distinct_folders(self):
        base = "file:/mnt/user-data/outputs/" + "x" * 90 + "/widgets/"
        a = render.artifact_folder(base + "ChartSales.tsx")
        b = render.artifact_folder(base + "ChartRevenue.tsx")
        c = render.artifact_folder("file:/other/" + "x" * 90 + "/widgets/ChartSales.tsx")
        self.assertEqual(len({a, b, c}), 3)
        self.assertEqual(render.artifact_folder("itinerary"), "itinerary")

    def test_sandbox_links_with_spaces_and_same_name_in_two_messages(self):
        def msg(mid, text):
            return {"message": {"id": mid, "author": {"role": "assistant"}, "content": {"parts": [text]}}}
        conv = {"mapping": {"a": msg("m1", "[r](sandbox:/mnt/data/My Report.xlsx)"),
                            "b": msg("m2", "again sandbox:/mnt/data/plot.png"),
                            "c": msg("m3", "[p](sandbox:/mnt/data/plot.png)")}}
        refs = sorted(render.chatgpt_sandbox_refs(conv))
        self.assertEqual(refs, [("m1", "/mnt/data/My Report.xlsx"), ("m2", "/mnt/data/plot.png"),
                                ("m3", "/mnt/data/plot.png")])

    def test_json_with_lone_surrogate(self):
        obj = {"t": "broken \ud83d emoji"}
        data = render.jdump(obj)
        import json
        self.assertEqual(json.loads(data.decode("utf-8")), obj)
        self.assertEqual(render.utf8("x\ud83d"), b"x?")


class HelpersTest(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(render.safe_name("a/b:c?.png"), "a_b_c_.png")
        self.assertEqual(render.safe_name("  "), "file")
        long = render.safe_name("x" * 300 + ".pdf")
        self.assertTrue(long.endswith(".pdf") and len(long) <= 120)
        self.assertEqual(render.safe_name(".."), "file")

    def test_index(self):
        md = render.index_markdown("T", [{"title": "a|b", "md": "c/1.md", "json": "c/1.json",
                                          "updated": "2026 October 24, 10:00"},
                                         {"title": "z", "md": "c/2.md", "json": "c/2.json",
                                          "updated": "2026 November 2, 09:00"}])
        self.assertLess(md.index("[z]"), md.index("a\\|b"))      # by date, not alphabetically

    def test_dates_are_shown_in_words_and_read_back(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 10, 24, 8, 5, tzinfo=timezone.utc)
        shown = render.human_time(dt)
        self.assertRegex(shown, r"^2026 October 2[34], \d\d:05$")
        self.assertEqual(render.parse_shown(shown), dt.astimezone().replace(tzinfo=None))
        self.assertEqual(render.parse_shown("2026-10-24 10:00"), datetime(2026, 10, 24, 10, 0))
        self.assertEqual(render.human_time(dt, with_time=False), shown.split(",")[0])
        self.assertIsNone(render.parse_shown("Health endpoint"))
