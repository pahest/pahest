import unittest

import helpers  # noqa: F401  (adds src/ to sys.path)

from pahest import render


class FixesTest(unittest.TestCase):
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

    def test_dates_are_shown_in_words_and_read_back(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 10, 24, 8, 5, tzinfo=timezone.utc)
        shown = render.human_time(dt)
        self.assertRegex(shown, r"^2026 October 2[34], \d\d:05$")
        self.assertEqual(render.parse_shown(shown), dt.astimezone().replace(tzinfo=None))
        self.assertEqual(render.parse_shown("2026-10-24 10:00"), datetime(2026, 10, 24, 10, 0))
        self.assertEqual(render.human_time(dt, with_time=False), shown.split(",")[0])
        self.assertIsNone(render.parse_shown("Health endpoint"))
