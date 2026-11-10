"""Readable copies: transcripts in the apps' real formats become Markdown + image files."""
import base64
import json
import re
import sqlite3

from helpers import TempDirTest, quiet_log

from pahest import readable
from pahest.result import Ctx
from pahest.store import Store, Zstd

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PNG_B64 = base64.b64encode(PNG).decode()


def jl(*objs) -> bytes:
    return b"".join(json.dumps(o).encode() + b"\n" for o in objs)


def cc_session() -> bytes:
    base = {"cwd": "/Users/me/projects/shop", "sessionId": "s1", "version": "2.1.319", "gitBranch": "main"}
    return jl(
        {**base, "type": "user", "timestamp": "2026-11-08T09:59:00.000Z",
         "message": {"role": "user", "content": "<command-name>/clear</command-name><command-args></command-args>"}},
        {**base, "type": "user", "timestamp": "2026-11-08T10:00:00.000Z",
         "message": {"role": "user", "content": "<system-reminder>hidden</system-reminder>Fix the ```login``` page"}},
        {"type": "api-request-blob", "blob": "x" * 5000},
        {**base, "type": "user", "isMeta": True, "timestamp": "2026-11-08T10:00:01Z",
         "message": {"role": "user", "content": "META CAVEAT"}},
        {**base, "type": "assistant", "timestamp": "2026-11-08T10:00:05Z",
         "message": {"role": "assistant", "model": "claude-opus-5-5", "content": [
             {"type": "thinking", "thinking": "Look at the form first.", "signature": "sig"}]}},
        {**base, "type": "assistant", "timestamp": "2026-11-08T10:00:06Z",
         "message": {"role": "assistant", "model": "claude-opus-5-5", "content": [
             {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls src", "description": "List"}}]}},
        {**base, "type": "user", "timestamp": "2026-11-08T10:00:07Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": [
                 {"type": "text", "text": "login.tsx\n" + "line\n" * 200},
                 {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG_B64}}]}]}},
        {**base, "type": "assistant", "timestamp": "2026-11-08T10:00:09Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "The page is fixed."}]}},
        {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-11-08T10:01:00Z"},
        {**base, "type": "user", "timestamp": "2026-11-08T10:02:00Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "Here is a screenshot"},
                                                 {"type": "image", "source": {"type": "base64",
                                                                              "media_type": "image/png",
                                                                              "data": PNG_B64}}]}},
        {**base, "type": "user", "timestamp": "2026-11-08T10:03:00Z",
         "origin": {"kind": "task-notification", "producer": "x"},
         "message": {"role": "user", "content": "<task-notification>\n<summary>Build finished</summary>\n</task-notification>"}},
        {**base, "type": "user", "timestamp": "2026-11-08T10:03:30Z",          # an older session: no origin
         "message": {"role": "user", "content": "<task-notification>\n<summary>Old style</summary>\n</task-notification>"}},
        {**base, "type": "user", "timestamp": "2026-11-08T10:04:00Z", "origin": {"kind": "peer"},
         "message": {"role": "user", "content": "Another Claude session sent a message: done"}},
        {**base, "type": "user", "timestamp": "2026-11-08T10:05:00Z", "origin": {"kind": "human"},
         "message": {"role": "user", "content": "<command-message>loop</command-message>\n<command-name>/loop</command-name>\n"
                                                "<command-args>5m check it</command-args>"}},
        {"type": "ai-title", "aiTitle": "Fix the login page", "sessionId": "s1"},
    ) + b'{"type":"user","message":{"content":"half a line'


def codex_session() -> bytes:
    sid = "019a0000-0000-7000-8000-00000000abcd"
    return jl(
        {"timestamp": "2026-11-07T09:00:00Z", "type": "session_meta",
         "payload": {"id": sid, "cwd": "/Users/me/projects/api", "cli_version": "0.162.0", "originator": "codex_cli_rs",
                     "git": {"branch": "dev"}, "base_instructions": {"text": "SECRET SYSTEM PROMPT"}}},
        {"timestamp": "2026-11-07T09:00:00Z", "type": "turn_context", "payload": {"model": "gpt-5.5-codex"}},
        {"timestamp": "2026-11-07T09:00:01Z", "type": "response_item", "payload": {
            "type": "message", "role": "developer", "content": [{"type": "input_text", "text": "DEV INSTRUCTIONS"}]}},
        {"timestamp": "2026-11-07T09:00:01Z", "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "<environment_context>\n<cwd>/x</cwd>\n</environment_context>"},
                {"type": "input_text", "text": "Add a health endpoint"},
                {"type": "input_text", "text": "<goal_context>\nGOAL BOOKKEEPING\n</goal_context>"},
                {"type": "input_text", "text": "<div>my own pasted html</div>"},
                {"type": "input_text", "text": "<send_user_message_question_reply>Use port 8080"
                                               "</send_user_message_question_reply>"},
                {"type": "input_image", "image_url": "data:image/png;base64," + PNG_B64}]}},
        {"timestamp": "2026-11-07T09:00:02Z", "type": "event_msg", "payload": {"type": "token_count", "info": {}}},
        {"timestamp": "2026-11-07T09:00:03Z", "type": "response_item", "payload": {
            "type": "reasoning", "summary": [], "encrypted_content": "gAAAA-ENCRYPTED"}},
        {"timestamp": "2026-11-07T09:00:04Z", "type": "response_item", "payload": {
            "type": "function_call", "name": "shell", "call_id": "c1",
            "arguments": json.dumps({"command": ["rg", "health"], "workdir": "/Users/me/projects/api"})}},
        {"timestamp": "2026-11-07T09:00:05Z", "type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "c1", "output": json.dumps({"output": "no matches"})}},
        {"timestamp": "2026-11-07T09:00:06Z", "type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "apply_patch", "call_id": "c2",
            "input": "*** Begin Patch\n*** Add File: health.py\n+def ok(): return 200\n*** End Patch"}},
        {"timestamp": "2026-11-07T09:00:07Z", "type": "response_item", "payload": {
            "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Added /health."}]}},
    )


class ReadableCase(TempDirTest):
    """A backup folder (self.store) for the readable step to work on."""

    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp / "b")
        self.ctx = Ctx(self.store, quiet_log(), {}, "2026-11-09", Zstd())

    def read(self, rel):
        return (self.tmp / "b" / rel).read_text()

    def js_data(self, rel: str, name: str):
        """The value of `window.<name>` in one of the pages' data files (items.js, images.js)."""
        [line] = [x for x in self.read(rel).split("\n") if x.startswith(f"window.{name}=")]
        return json.loads(line[len(f"window.{name}="):].rstrip(";"))


class ReadableTest(ReadableCase):

    def test_claude_code_session_becomes_readable_markdown(self):
        s = self.store
        s.add_bytes("claude-code/projects/-Users-me-projects-shop/s1.jsonl", cc_session())
        s.add_bytes("claude-code/projects/-Users-me-projects-shop/s1/subagents/agent-a1.jsonl", jl(
            {"type": "user", "isSidechain": True, "message": {"content": "Find the bug"}, "timestamp": "2026-11-08T10:00:10Z"},
            {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "Found it"}]}}))
        s.add_bytes("claude-code/history.jsonl", jl(
            {"display": "Fix the login page", "timestamp": 1762596000000, "project": "/Users/me/projects/shop"},
            {"display": "Use these records [Pasted text #1 +40 lines] and [Pasted text #2 +9 lines]",
             "timestamp": 1762596100000, "project": "/Users/me/projects/shop",
             "pastedContents": {"1": {"id": 1, "type": "text", "contentHash": "0c32bf4016e1325f"},
                                "2": {"id": 2, "type": "text", "contentHash": "77aa00bb11cc22dd"}}}))
        s.add_bytes("claude-code/paste-cache/0c32bf4016e1325f.txt", b";; Domain: example.com\n;; Exported")
        res = readable.run(self.ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        idx = self.read("readable/claude-code/index.md")
        self.assertIn("Fix the login page", idx)
        self.assertNotIn("Find the bug", idx)                         # subagents are not separate sessions
        [md_rel] = [r for r in s.manifest if r.startswith("readable/claude-code/") and r.endswith(").md")
                    and "/subagents/" not in r]
        md = self.read(md_rel)
        self.assertTrue(md.startswith("# Fix the login page"))
        self.assertIn("Fix the ```login``` page", md)
        you = md.split("### You · 2026 November 8, 14:00")[1].split("<details>")[0]
        self.assertNotIn("hidden", you)                              # app-added text is not shown as yours …
        self.assertIn("Added by Claude Code: System reminder</summary>\n\n```\nhidden\n```", md)   # … but kept
        self.assertIn("Added by Claude Code: Note from Claude Code</summary>\n\n```\nMETA CAVEAT\n```", md)
        self.assertIn("> Look at the form first.", md)
        self.assertIn("```bash\nls src\n```", md)
        self.assertNotIn("more characters", md)                       # nothing is ever shortened
        self.assertEqual(md.count("\nline"), 200)
        self.assertIn("The page is fixed.", md)
        self.assertIn("shortened here to fit", md)
        self.assertIn("claude-opus-5-5", md)
        self.assertIn("### Background task · ", md)                  # sent by the app, not typed by you
        self.assertEqual(md.count("### Background task · "), 2)
        self.assertIn("### Another session · ", md)
        self.assertIn("`/loop 5m check it`", md)                      # a slash command, shown short
        self.assertNotIn("<command-message>", md)
        raw_link = md.split("Raw transcript | [s1.jsonl](")[1].split(")")[0].strip("<>")
        self.assertTrue((self.tmp / "b" / md_rel).parent.joinpath(raw_link).resolve().is_file())
        img = md.split("![image](")[1].split(")")[0].strip("<>")
        self.assertEqual((self.tmp / "b" / md_rel).parent.joinpath(img).read_bytes(), PNG)
        self.assertEqual(sum(1 for r in s.manifest if "/images/" in r), 1)   # same picture saved once
        sub = [r for r in s.manifest if "/subagents/" in r and r.startswith("readable/") and r.endswith(".md")]
        self.assertEqual(len(sub), 1)
        self.assertIn("Found it", self.read(sub[0]))
        history = self.read("readable/claude-code/prompt-history.md")
        self.assertIn("Fix the login page", history)
        self.assertIn("> [Pasted 1]\n> ;; Domain: example.com\n> ;; Exported", history)   # from the paste cache
        self.assertIn("paste cache, which no longer had it", history)                     # said when it is gone
        readme = self.read("README.md")
        self.assertIn("readable/claude-code/index.md", readme)

    def test_codex_session_becomes_readable_markdown(self):
        s = self.store
        rel = "codex/sessions/2026/11/07/rollout-2026-11-07T09-00-00-019a0000-0000-7000-8000-00000000abcd.jsonl"
        s.add_bytes(rel, codex_session())
        s.add_bytes("codex/session_index.jsonl", jl({"id": "019a0000-0000-7000-8000-00000000abcd",
                                                    "thread_name": "Health endpoint", "updated_at": "x"}))
        s.deleted[rel] = "2026-11-08"
        db = self.tmp / "state_5.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("create table threads(id text, title text, data blob)")
        con.execute("insert into threads values ('t1', 'Health endpoint', x'0102')")
        con.commit()
        con.close()
        s.add_file(db, "codex/databases/state_5.sqlite")
        res = readable.run(self.ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        [md_rel] = [r for r in s.manifest if r.startswith("readable/codex/2026-11/") and r.endswith(".md")]
        md = self.read(md_rel)
        self.assertTrue(md.startswith("# Health endpoint"))
        self.assertIn("Add a health endpoint", md)
        you = md.split("### You · ")[1].split("<details>")[0]
        self.assertNotIn("environment_context", you)            # context Codex added is not shown as yours …
        self.assertNotIn("GOAL BOOKKEEPING", you)
        self.assertIn("Added by Codex: Environment context</summary>", md)            # … but kept, folded
        self.assertIn("GOAL BOOKKEEPING", md)
        self.assertIn("<div>my own pasted html</div>", md)      # your own words are never hidden
        self.assertIn("Use port 8080", md)
        self.assertNotIn("send_user_message_question_reply", md)
        self.assertIn("Added by Codex: Instructions from Codex</summary>\n\n```\nDEV INSTRUCTIONS", md)
        self.assertIn("Added by Codex: Codex system instructions</summary>\n\n```\nSECRET SYSTEM PROMPT", md)
        self.assertNotIn("ENCRYPTED", md)                        # encrypted reasoning cannot be read by anyone
        self.assertIn("Reasoning (encrypted by OpenAI; not readable)", md)
        self.assertIn("rg health", md)
        self.assertIn("no matches", md)
        self.assertIn("+def ok(): return 200", md)
        self.assertIn("Added /health.", md)
        self.assertIn("gpt-5.5-codex", md)
        self.assertIn("deleted at source on 2026-11-08", md)
        self.assertIn("deleted at source", self.read("readable/codex/index.md"))
        rows = json.loads(self.read("readable/codex/databases/state_5.sqlite/threads.json"))
        self.assertEqual(rows, [{"id": "t1", "title": "Health endpoint", "data": {"base64": "AQI="}}])
        self.assertIn("Codex sessions", self.read("README.md"))

    def test_a_broken_transcript_does_not_stop_the_others(self):
        s = self.store
        s.add_bytes("claude-code/projects/-p/bad.jsonl", b"\xff\xfe not json at all\n")
        s.add_bytes("claude-code/projects/-p/good.jsonl", cc_session())
        res = readable.run(self.ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        self.assertIn("Fix the login page", self.read("readable/claude-code/index.md"))


class OddInputTest(ReadableCase):
    def test_strange_dates_deep_nesting_and_odd_lines_do_not_stop_the_step(self):
        store, ctx = self.store, self.ctx
        deep = "[" * 100000 + "]" * 100000
        store.add_bytes("claude-code/projects/-p/odd.jsonl", jl(
            {"type": "user", "timestamp": "0001-01-01T00:00:00Z", "message": {"content": "year one"}},
            {"type": "user", "timestamp": "9999-12-31T23:59:59Z", "message": "not a dict"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "still here"}]}},
        ) + deep.encode() + b"\n")
        store.add_bytes("claude-code/history.jsonl", jl({"display": "x", "timestamp": "0001-01-01T00:00:00Z"}))
        res = readable.run(ctx, "s")
        self.assertEqual(res.failed, [])
        md = [r for r in store.manifest if r.startswith("readable/claude-code/p/") and r.endswith(".md")]
        self.assertEqual(len(md), 1)
        text = (self.tmp / "b" / md[0]).read_text()
        self.assertIn("year one", text)
        self.assertIn("still here", text)


class CompletenessTest(ReadableCase):
    """Nothing in a conversation is left out or shortened: every text of every kind of record is on the
    web page and in the Markdown copy (only bookkeeping such as ids and times may be missing)."""

    def words(self, rel: str) -> str:
        import html as h
        text = (self.tmp / "b" / rel).read_text(encoding="utf-8")
        if rel.endswith(".html"):
            text = h.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>", " ", text, flags=re.S)))
        return " ".join(re.findall(r"\w+", text))

    def assert_all_shown(self, prefix: str, texts):
        [md] = [r for r in self.store.manifest if r.startswith(prefix) and r.endswith(").md")]
        for rel in (md, md[:-3] + ".html"):
            page = self.words(rel)
            for t in texts:
                self.assertIn(" ".join(re.findall(r"\w+", t)), page, f"{t!r} missing from {rel}")

    def test_every_kind_of_claude_code_record_is_shown_in_full(self):
        base = {"cwd": "/Users/me/p", "sessionId": "s9", "version": "2.1.400"}
        big = "\n".join(f"output line {i} of the build" for i in range(3000))       # 3,000 lines, all shown
        self.store.add_bytes("claude-code/projects/-Users-me-p/s9.jsonl", jl(
            {**base, "type": "user", "timestamp": "2026-11-08T10:00:00Z",
             "message": {"role": "user", "content": "Start the build please"}},
            {**base, "type": "attachment", "timestamp": "2026-11-08T10:00:01Z",
             "attachment": {"type": "instructions", "files": [{"path": "/Users/me/CLAUDE.md", "content": "Always use tabs"}]}},
            {**base, "type": "attachment", "timestamp": "2026-11-08T10:00:02Z",
             "attachment": {"type": "file", "filename": "/Users/me/p/notes.txt", "content": {"file": {"content": "my notes text"}}}},
            {**base, "type": "assistant", "timestamp": "2026-11-08T10:00:03Z", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"command": "make all", "description": "Build", "timeout": 600000, "run_in_background": True}},
                {"type": "tool_use", "id": "t2", "name": "Grep",
                 "input": {"pattern": "TODO", "path": "src", "output_mode": "content", "glob": "*.py"}},
                {"type": "tool_use", "id": "t3", "name": "WebFetch", "input": {"url": "https://example.com", "prompt": "summarise the page"}},
                {"type": "server_tool_use", "id": "t4", "name": "web_search", "input": {"query": "unusual block query"}}]}},
            {**base, "type": "user", "timestamp": "2026-11-08T10:00:04Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": big},
                {"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "tool_reference", "tool_name": "WebFetch"},
                                                                         {"type": "search_result", "title": "a search title", "content": "found text"}]},
                {"type": "text", "text": "<system-reminder>reminder about the plan</system-reminder>"}]}},
            {**base, "type": "attachment", "timestamp": "2026-11-08T10:00:05Z",
             "attachment": {"type": "queued_command", "prompt": "also run the tests while you are at it",
                            "origin": {"kind": "human"}, "commandMode": "prompt"}},
            {**base, "type": "attachment", "timestamp": "2026-11-08T10:00:06Z",
             "attachment": {"type": "queued_command", "prompt": "<task-notification>job 7 done</task-notification>",
                            "origin": {"kind": "task-notification"}}},
            {**base, "type": "system", "subtype": "away_summary", "timestamp": "2026-11-08T10:00:07Z",
             "content": "Recap of the build so far"},
            {**base, "type": "system", "subtype": "turn_duration", "durationMs": 164104, "timestamp": "2026-11-08T10:00:08Z"},
            {**base, "type": "system", "subtype": "brand_new_kind", "content": "a notice never seen before",
             "extra": {"detail": "kept too"}, "timestamp": "2026-11-08T10:00:09Z"},
            {**base, "type": "user", "isMeta": True, "timestamp": "2026-11-08T10:00:10Z",
             "message": {"role": "user", "content": "Caveat from the app"}},
            {**base, "type": "assistant", "timestamp": "2026-11-08T10:00:11Z", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Built. See [the log](missing/file.log) and [bad](javascript:alert(1))."}]}},
            {**base, "type": "attachment", "timestamp": "2026-11-08T10:00:12Z",
             "attachment": {"type": "instructions", "files": [{"path": "/Users/me/CLAUDE.md", "content": "Use tabs. " * 50}]}},
            {**base, "type": "attachment", "timestamp": "2026-11-08T10:00:13Z",
             "attachment": {"type": "instructions", "files": [{"path": "/Users/me/CLAUDE.md", "content": "Use tabs. " * 50}]}}))
        res = readable.run(self.ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        self.assert_all_shown("readable/claude-code/", [
            "Start the build please", "Always use tabs", "my notes text", "make all", "600000", "run_in_background",
            "TODO", "output_mode", "*.py", "summarise the page", "unusual block query", "output line 2999 of the build",
            "WebFetch", "a search title", "found text", "reminder about the plan", "also run the tests while you are at it",
            "job 7 done", "Recap of the build so far", "Worked for 2m 44s", "a notice never seen before", "kept too",
            "Caveat from the app", "missing/file.log", "javascript:alert(1)"])
        [html_rel] = [r for r in self.store.manifest if r.startswith("readable/claude-code/") and r.endswith(").html")]
        page = (self.tmp / "b" / html_rel).read_text()
        self.assertNotIn('href="javascript', page)
        # text repeated word for word is shown once; the copy links to its line in the raw transcript
        self.assertEqual(page.count("Use tabs. " * 49 + "Use tabs."), 1)          # one full copy
        self.assertIn("(the same as before)", page)
        self.assertIn('Original: <a href="../../../claude-code/projects/-Users-me-p/s9.jsonl">s9.jsonl, line 14</a>', page)
        md = (self.tmp / "b" / (html_rel[:-5] + ".md")).read_text()
        self.assertIn("Original: [s9.jsonl, line 14](../../../claude-code/projects/-Users-me-p/s9.jsonl)", md)
        self.assertIn("sent while Claude was working", page)
        self.assertIn('<b>Background task <span class="sub">sent while Claude was working', page)

    def test_every_kind_of_codex_item_is_shown_in_full(self):
        rel = "codex/sessions/2026/11/07/rollout-2026-11-07T09-00-00-019a0000-0000-7000-8000-00000000ffff.jsonl"
        item = lambda p: {"timestamp": "2026-11-07T09:00:01Z", "type": "response_item", "payload": p}
        self.store.add_bytes(rel, jl(
            {"timestamp": "2026-11-07T09:00:00Z", "type": "session_meta",
             "payload": {"id": "019a0000-0000-7000-8000-00000000ffff", "cwd": "/x", "base_instructions": {"text": "BASE RULES"},
                         "instructions": "user level instructions"}},
            {"timestamp": "2026-11-07T09:00:00Z", "type": "turn_context",
             "payload": {"turn_id": "a", "model": "gpt-5.5", "approval_policy": "never", "sandbox_policy": {"mode": "workspace-write"}}},
            item({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Find the slow query"}]}),
            item({"type": "reasoning", "summary": [], "encrypted_content": "gAAAA-HIDDEN"}),
            item({"type": "function_call", "name": "js", "namespace": "mcp__node_repl_ns", "call_id": "c0",
                  "arguments": json.dumps({"code": "1+1"})}),
            item({"type": "function_call", "name": "exec_command", "call_id": "c1",
                  "arguments": json.dumps({"cmd": "rg slow", "workdir": "/x", "yield_time_ms": 1000, "justification": "look for it"})}),
            item({"type": "function_call_output", "call_id": "c1",
                  "output": json.dumps({"output": "slow.sql:1", "metadata": {"exit_code": 0, "duration_seconds": 0.5}})}),
            item({"type": "web_search_call", "action": {"type": "search", "query": "postgres index", "queries": ["postgres index", "btree vs gin"]}}),
            item({"type": "tool_search_call", "call_id": "c2", "arguments": {"query": "node repl tools"}}),
            item({"type": "tool_search_output", "call_id": "c2", "tools": [{"name": "mcp__node_repl", "description": "runs js"}]}),
            item({"type": "agent_message", "author": "/root", "recipient": "/root/helper",
                  "content": [{"type": "input_text", "text": "check the index usage"}]}),
            item({"type": "image_generation_call", "revised_prompt": "a chart of query times", "status": "completed"}),
            item({"type": "brand_new_item", "text": "an item type never seen before"}),
            {"timestamp": "2026-11-07T09:00:01Z", "type": "event_msg", "payload": {
                "type": "item_completed", "turn_id": "t", "item": {"type": "CommandExecution", "id": "exec-1", "process_id": "77",
                "command": ["/bin/zsh", "-lc", "rg slow"], "aggregated_output": "slow.sql:1\nslow.sql:2 the line the model never saw"}}},
            {"timestamp": "2026-11-07T09:00:01Z", "type": "event_msg", "payload": {
                "type": "item_completed", "turn_id": "t", "item": {"type": "CommandExecution", "id": "exec-2",
                "command": ["/bin/zsh", "-lc", "rg slow"], "aggregated_output": "slow.sql:1"}}},
            {"timestamp": "2026-11-07T09:00:01Z", "type": "event_msg", "payload": {
                "type": "item_completed", "item": {"type": "Extension", "kind": "web.search", "query": "postgres index",
                "results": [{"title": "Indexes in Postgres", "url": "https://example.org/pg", "snippet": "a btree is the default"}]}}},
            {"timestamp": "2026-11-07T09:00:01Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total": 5}}},
            {"timestamp": "2026-11-07T09:00:02Z", "type": "compacted", "payload": {
                "message": "summary of the work so far", "window_number": 2, "replacement_history": [
                    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Find the slow query"}]},
                    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "only kept after compacting"}]},
                    {"type": "compaction", "encrypted_content": "gAAAA-SECRET"}]}},
            item({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Added an index."}]})))
        res = readable.run(self.ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        self.assert_all_shown("readable/codex/", [
            "BASE RULES", "user level instructions", "approval_policy", "workspace-write", "Find the slow query", "rg slow",
            "yield_time_ms", "look for it", "slow.sql:1", "exit_code", "duration_seconds", "postgres index", "btree vs gin",
            "node repl tools", "mcp__node_repl", "runs js", "mcp__node_repl_ns", "1+1", "check the index usage", "/root/helper",
            "a chart of query times", "an item type never seen before", "Added an index.",
            "summary of the work so far", "only kept after compacting",
            "the line the model never saw", "Indexes in Postgres", "https://example.org/pg", "a btree is the default"])
        [md] = [r for r in self.store.manifest if r.startswith("readable/codex/") and r.endswith(").md")]
        text = (self.tmp / "b" / md).read_text()
        self.assertIn("Codex kept 3 items. 1 of them are already shown above on this page. "
                      "1 are encrypted by OpenAI", text)
        kept = text.split("What Codex kept after compacting</summary>")[1].split("</details>")[0]
        self.assertNotIn("Find the slow query", kept)                       # a kept copy is not repeated
        self.assertIn("only kept after compacting", kept)                   # anything new is shown in full
        raw = "rollout-2026-11-07T09-00-00-019a0000-0000-7000-8000-00000000ffff.jsonl"
        self.assertIn(f"Original: [{raw}, line 14](", text)                 # where the full copy is
        self.assertIn(f"Reasoning (encrypted by OpenAI; not readable)* · Original: [{raw}, line 4](", text)
        page = (self.tmp / "b" / (md[:-3] + ".html")).read_text()
        self.assertIn(f'Original: <a href="../../../codex/sessions/2026/11/07/{raw}">{raw}, line 14</a>', page)
        self.assertIn("gAAAA-HIDDEN", (self.tmp / "b" / rel).read_text())   # every byte stays in the raw file
        self.assertEqual(text.count("Codex record: item completed (CommandExecution)"), 1)  # the repeat is not shown
        self.assertNotIn("token_count", text)
        self.assertNotIn("process_id", text)


def pic(n: int) -> bytes:
    """A small, distinct PNG (long enough to be recognised as a picture when stored as base64 text)."""
    return b"\x89PNG\r\n\x1a\n" + bytes([n]) * 200


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class PicturesTest(ReadableCase):
    """A picture stored as base64 text anywhere in a record is saved as an image file and shown as a
    picture (never as base64 text), and text is never changed by the way pages link to files."""

    def page_texts(self, prefix: str):
        [md] = [r for r in self.store.manifest if r.startswith(prefix) and r.endswith(").md")]
        return md, (self.tmp / "b" / md).read_text(), (self.tmp / "b" / (md[:-3] + ".html")).read_text()

    def gallery(self) -> dict:
        """The pictures page's list: picture file name -> where it came from."""
        rows = self.js_data("readable/images.js", "PICS")
        return {f.rsplit("/", 1)[1]: kind for f, kind, when, item in rows}

    def assert_picture(self, data: bytes, md: str, text: str, page: str):
        name = readable._pic_id(data) + ".png"
        files = [r for r in self.store.manifest if r.endswith("/images/" + name)]
        self.assertEqual(len(files), 1, name)
        self.assertEqual((self.tmp / "b" / files[0]).read_bytes(), data)            # the same bytes
        self.assertEqual(text.count(f"]({readable._rel(md, files[0])})"), 1)        # shown once in the Markdown
        self.assertEqual(page.count(f'<img src="{readable._rel(md, files[0])}"'), 1)  # and once on the page
        for t in (text, page):
            self.assertNotIn(b64(data)[:40], t)                                      # not as base64 text

    def test_pictures_in_codex_records_are_saved_and_shown(self):
        rel = "codex/sessions/2026/11/07/rollout-2026-11-07T09-00-00-019a0000-0000-7000-8000-00000000eeee.jsonl"
        a, b, c, d = pic(1), pic(2), pic(3), pic(4)
        item = lambda p: {"timestamp": "2026-11-07T09:00:01Z", "type": "response_item", "payload": p}
        event = lambda it: {"timestamp": "2026-11-07T09:00:02Z", "type": "event_msg",
                            "payload": {"type": "item_completed", "turn_id": "t", "item": it}}
        self.store.add_bytes(rel, jl(
            {"timestamp": "2026-11-07T09:00:00Z", "type": "session_meta",
             "payload": {"id": "019a0000-0000-7000-8000-00000000eeee", "cwd": "/x"}},
            item({"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "What is on this page?"},
                {"type": "input_image", "image_url": "data:image/png;base64," + b64(a)}]}),
            item({"type": "function_call", "name": "js", "namespace": "mcp__cua", "call_id": "c1",
                  "arguments": json.dumps({"code": "await tab.getScreenshot()"})}),
            item({"type": "function_call_output", "call_id": "c1", "output": [
                {"type": "input_text", "text": "the tab"},
                {"type": "input_image", "image_url": "data:image/png;base64," + b64(b), "detail": "original"}]}),
            event({"type": "McpToolCall", "id": "c1", "server": "cua", "tool": "js",
                   "result": {"content": [{"type": "text", "text": "the tab"},
                                          {"type": "image", "data": b64(b), "mimeType": "image/png"}],
                              "_meta": {"codex/toolSurface": {"kind": "browserUse",
                                                              "screenshot": {"url": "data:image/png;base64," + b64(c)}}}}}),
            event({"type": "ImageView", "id": "v1", "result": "data:image/png;base64," + b64(d)}),
            event({"type": "McpToolCall", "id": "c2", "server": "cua", "tool": "js",
                   "result": {"content": [{"type": "text", "text": json.dumps(
                       {"content": [{"type": "text", "text": "nested tab state"}],
                        "_meta": {"screenshot": {"url": "data:image/png;base64," + b64(pic(6))}}})}]}}),
            item({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "A login form."}]})))
        res = readable.run(self.ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        md, text, page = self.page_texts("readable/codex/")
        self.assert_picture(a, md, text, page)
        self.assert_picture(b, md, text, page)            # the model's copy; Codex's own copy is not repeated
        self.assert_picture(c, md, text, page)            # the browser screenshot in Codex's own record
        self.assert_picture(d, md, text, page)
        nested = text.split("nested tab state")[1]                         # JSON stored as text: kept as it is …
        self.assertIn(b64(pic(6))[:40], nested)
        name = readable._pic_id(pic(6)) + ".png"                            # … and its picture is shown too
        self.assertIn(f"](../images/{name})", nested)
        self.assertEqual((self.tmp / "b" / "readable/codex/images" / name).read_bytes(), pic(6))
        self.assertIn(f"(a picture, shown below as {readable._pic_id(c)}.png; the raw transcript has it as "
                      f"{len('data:image/png;base64,' + b64(c)):,} characters of base64 text)", text)
        self.assertIn("detail", text)                      # what came with a picture is shown too
        for t in (text, page):
            self.assertNotIn("\x00", t)
        n = lambda data: readable._pic_id(data) + ".png"
        self.assertEqual(self.gallery(), {n(a): "you", n(b): "tool", n(c): "app", n(d): "app", n(pic(6)): "app"})

    def test_text_that_looks_like_a_file_marker_is_never_changed(self):
        base = {"cwd": "/Users/me/p", "sessionId": "s7", "version": "2.1.400"}
        ruby = "class Alerts\n  @@notifiers = {}\n  def self.add(name)\n    @@notifiers[name] = true\n  end\nend"
        self.store.add_bytes("claude-code/projects/-Users-me-p/s7.jsonl", jl(
            {**base, "type": "user", "timestamp": "2026-11-08T10:00:00Z",
             "message": {"role": "user", "content": "Why does @@notifiers[name] reset? See @@@ -1,2 -1,2 +1,3 @@@ and x@@y."}},
            {**base, "type": "assistant", "timestamp": "2026-11-08T10:00:02Z", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Class variables like @@notifiers are shared:\n\n```ruby\n" + ruby + "\n```"},
                {"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": "/Users/me/p/a.rb", "content": ruby}}]}}))
        self.assertEqual(readable.run(self.ctx, "2026-11-09-10-00-00").failed, [])
        md, text, page = self.page_texts("readable/claude-code/")
        import html as h
        for t in (text, h.unescape(re.sub(r"<[^>]+>", "", page))):
            self.assertIn("Why does @@notifiers[name] reset? See @@@ -1,2 -1,2 +1,3 @@@ and x@@y.", t)
            self.assertEqual(t.count("    @@notifiers[name] = true"), 2)          # in the answer and in the file
            self.assertNotIn("\x00", t)

    def test_pictures_in_claude_code_notes_and_subagents_are_shown(self):
        base = {"cwd": "/Users/me/p", "sessionId": "s8", "version": "2.1.400"}
        e, f, g = pic(5), pic(7), pic(8)
        self.store.add_bytes("claude-code/projects/-Users-me-p/s8.jsonl", jl(
            {**base, "type": "user", "timestamp": "2026-11-08T10:00:00Z",
             "message": {"role": "user", "content": "Check the app"}},
            {**base, "type": "user", "isMeta": True, "timestamp": "2026-11-08T10:00:01Z",
             "message": {"role": "user", "content": [
                 {"type": "text", "text": "Screenshot from the app"},
                 {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64(e)}}]}},
            {**base, "type": "assistant", "timestamp": "2026-11-08T10:00:02Z", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "It looks fine."}]}}))
        self.store.add_bytes("claude-code/projects/-Users-me-p/s8/subagents/agent-a1.jsonl", jl(
            {**base, "type": "user", "isSidechain": True, "timestamp": "2026-11-08T10:00:03Z", "message": {"role": "user", "content": [
                {"type": "text", "text": "Compare with this picture"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64(f)}}]}},
            {**base, "type": "assistant", "isSidechain": True, "timestamp": "2026-11-08T10:00:04Z",
             "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "r1", "name": "Read",
                                                           "input": {"file_path": "/x/g.png"}}]}},
            {**base, "type": "user", "isSidechain": True, "timestamp": "2026-11-08T10:00:05Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "r1", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64(g)}}]}]}}))
        res = readable.run(self.ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        [md] = [r for r in self.store.manifest if r.startswith("readable/claude-code/") and r.endswith(").md")
                and "/subagents/" not in r]
        text, page = (self.tmp / "b" / md).read_text(), (self.tmp / "b" / (md[:-3] + ".html")).read_text()
        self.assert_picture(e, md, text, page)
        n = lambda data: readable._pic_id(data) + ".png"
        self.assertEqual(self.gallery(), {n(e): "app",        # a note from the app
                                          n(f): "tool",       # a subagent's task comes from the main agent
                                          n(g): "tool"})
        rows = self.js_data("readable/images.js", "PICS")
        [sub] = [r[3] for r in rows if r[0].endswith(n(f))]
        self.assertEqual(sub[4], "subagent")                  # a page not in the lists: its row is given here
        self.assertTrue((self.tmp / "b" / sub[3]).is_file())


class WebPagesTest(ReadableCase):
    def test_markdown_becomes_safe_html(self):
        from pahest import htmlview
        md = ("# Title <b>x</b>\n\n### You · 10:00\n\nHello <script>alert(1)</script> **bold** and `a<b`\n"
              "[bad](javascript:alert(1)) [web](https://example.com/a) [up](../../../../etc/passwd)\n\n"
              "### Claude · 10:01\n\n```\n<img src=x onerror=alert(1)>\n```\n\n"
              "| A | B |\n|---|---|\n| [s](<x y.md>) | c\\|d |\n\n- one\n  - nested\n- [x] done\n\n"
              "> **Thinking**\n>\n> deep\n\n*Result:*\n\n![pic](<images/a b.png>)\n")
        out = htmlview.md_to_html(md, htmlview.make_linker("readable/codex/2026-11/s.md",
                                                           "readable/codex/2026-11/s.html",
                                                           {"readable/codex/2026-11/x y.md": "readable/codex/2026-11/x y.html"}))
        self.assertNotIn("<script", out)
        self.assertNotIn("<img src=x", out)
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn('href="javascript', out)
        self.assertNotIn("passwd\"", out)
        self.assertIn('<a href="https://example.com/a">web</a>', out)
        self.assertIn('<h3 class="you">', out)
        self.assertIn('<h3 class="ai">', out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<code>a&lt;b</code>", out)
        self.assertIn('href="x%20y.html"', out)                 # links to other chats open their web page
        self.assertIn("<td>c|d</td>", out)
        self.assertIn("<ul><li>one<ul><li>nested", out)
        self.assertIn("☑ done", out)
        self.assertIn("<blockquote>", out)
        self.assertIn('class="label"', out)
        self.assertIn('src="images/a%20b.png"', out)
        typed = htmlview.md_to_html("run this:\n\n```I'd like you to set up the site\nstep two\n```", lambda u: None)
        self.assertIn("I&#x27;d like you to set up the site", typed)          # text right after ``` is kept
        self.assertIn('<code class="lang-py">', htmlview.md_to_html("```py\nx\n```", lambda u: None))
        nested = htmlview.md_to_html("see [https://x.example/a](https://x.example/a) now", lambda u: u)
        self.assertEqual(nested.count("<a "), 1)                       # no link inside a link
        grouped = htmlview.md_to_html("## 2026 October\n\n| Started | Session |\n|---|---|\n"
                                      "| 2026 October 21, 19:40 | x |\n\n## 2026 October 24\n\ntext\n", lambda u: None)
        self.assertIn("<h2>2026 October</h2>", grouped)                     # a month is not a day
        self.assertIn('<td data-date="2026-10-21T19:40">2026 October 21, 19:40</td>', grouped)
        self.assertIn('<h2 data-date="2026-10-24T00:00">', grouped)
        only = htmlview.make_linker("readable/x/s.md", "readable/x/s.html", {}, lambda rel: rel == "readable/x/real.png")
        self.assertIsNone(only("references/book.md"))         # a file of your project, not in the backup
        self.assertEqual(only("real.png"), "real.png")

    def test_backup_gets_index_html_and_a_page_per_conversation(self):
        store, ctx = self.store, self.ctx
        store.add_bytes("claude-code/projects/-Users-me-projects-shop/s1.jsonl", cc_session())
        store.add_bytes("codex/sessions/2026/11/07/rollout-2026-11-07T09-00-00-019a.jsonl", codex_session())
        res = readable.run(ctx, "2026-11-09-10-00-00")
        self.assertEqual(res.failed, [])
        b = self.tmp / "b"
        index = (b / "index.html").read_text()
        items = (b / "readable/items.js").read_text()
        for text in ("Fix the login page", "Add a health endpoint", "report.html", 'id="q"',
                     'data-page="list"', "readable/assets/style.css", "readable/assets/app.js", "readable/items.js"):
            self.assertIn(text, index)
        for text in ("Claude Code", "Codex", "Use port 8080"):     # the last one: a session preview
            self.assertIn(text, items)
        self.assertNotIn("```", items)                                         # previews are plain text
        self.assertNotIn('"/clear"', items)                                    # a slash command is not a preview
        self.assertTrue((b / "readable/assets/style.css").is_file() and (b / "readable/assets/app.js").is_file())
        self.assertNotIn("<h2>More</h2>", index)                              # the extra pages are in the footer
        self.assertIn("Backup report", index)
        codex_list = (b / "readable/codex/index.html").read_text()            # the same template, one app
        self.assertIn('data-app="Codex"', codex_list)
        self.assertIn('data-key="range"', codex_list)
        self.assertNotIn('data-key="app"', codex_list)
        hrefs = re.findall(r'href=\\?"([^"\\]+)\\?"', index)
        import urllib.parse
        for h in hrefs:
            if h.endswith(".html") and not h.startswith("http") and h != "report.html":
                self.assertTrue((self.tmp / "b" / urllib.parse.unquote(h)).is_file(), h)
        [cc] = [r for r in store.manifest if r.startswith("readable/claude-code/") and r.endswith(").html")]
        page = (self.tmp / "b" / cc).read_text()
        self.assertEqual(page.count('<nav class="pn">'), 2)                   # previous / next, top and bottom
        self.assertIn('<section class="msg you">', page)                      # built from the HTML templates
        self.assertIn('<section class="msg ai" data-k="say think tool">', page)    # what the turn holds (Show menu)
        self.assertIn('<div class="say"><p>The page is fixed.</p></div>', page)
        self.assertIn('<div class="tool"><div class="tn">Bash</div>', page)
        self.assertIn('<pre class="result">', page)
        self.assertEqual(page.count("\nline"), 200)                         # web pages are never shortened
        self.assertNotIn("more characters in the raw transcript", page)
        self.assertIn('<pre><code class="lang-bash">ls src</code></pre>', page)
        self.assertIn('<details class="think">', page)
        self.assertIn('<footer id="foot">', page)
        self.assertIn('<section class="msg auto"><div class="mh"><b>Background task</b>', page)
        self.assertIn("<dt>Your messages</dt><dd>4</dd>", page)                # the 3 sent by the app are not counted
        self.assertIn('id="expandall"', page)                                   # expand all, print, Markdown
        self.assertIn('id="print"', page)
        self.assertIn('href="' + urllib.parse.quote(cc.rsplit("/", 1)[1][:-5]) + '.md"', page)
        self.assertIn('id="dates"', index)                                      # dates at the side
        self.assertIn('id="alldet"', index)                                     # details on / off
        app_js = (b / "readable/assets/app.js").read_text()
        for text in ("Copy message", "function asText", "beforeprint", "Show details", "pahest-show", "function goPic",
                     "function drawPics", "function lbOpen", "View in chat", "function moveRow"):
            self.assertIn(text, app_js)
        # "Show": choose what a session page shows
        for p in (index, page, (b / "readable/images.html").read_text()):          # the name, the address, the license
            self.assertIn('<a class="brand" href="', p)
            self.assertIn('Made with <a href="https://github.com/emirn/pahest" rel="noopener">Pahest</a> 0.1.0, open source '
                          '(MIT license). Pahest is Armenian for “reserve”.', p)
        self.assertIn("Made by [Pahest](https://github.com/emirn/pahest) 0.1.0", (b / "README.md").read_text())
        self.assertIn('<details class="showm" id="showm">', page)
        self.assertEqual(re.findall(r'data-show="(\w+)"', page), ["you", "say", "think", "tool", "app", "pics"])
        self.assertIn('data-preset="you">Only my messages', page)
        # every picture on one page, linked from the lists
        self.assertIn('<a href="readable/images.html">Pictures (1)</a>', index)    # the same picture in two sessions: once
        gallery = (b / "readable/images.html").read_text()
        self.assertIn('data-page="images"', gallery)
        self.assertIn('<script src="images.js"></script><script src="assets/app.js">', gallery)
        self.assertIn('data-pk="you"', gallery)
        pics = self.js_data("readable/images.js", "PICS")
        [(file, kind, when, item)] = pics                                       # shown 3 times, listed once …
        self.assertEqual(kind, "you")                                           # … as one you pasted, the first time
        self.assertEqual((b / file).read_bytes(), PNG)
        self.assertEqual(when, "2026-11-07T13:00")
        items = self.js_data("readable/items.js", "ITEMS")
        self.assertEqual(items[item][2], "Codex")                               # its session
        self.assertNotIn("```", page)
        self.assertIn('data-page="session"', page)
        self.assertIn("<dt>Folder</dt>", page)
        self.assertNotIn("conversation -->", page)
        img = re.search(r'<img src="([^"]+)"', page).group(1)
        self.assertEqual((self.tmp / "b" / cc).parent.joinpath(urllib.parse.unquote(img)).read_bytes(), PNG)
        raw = re.search(r'<a href="([^"]+\.jsonl)"', page).group(1)
        self.assertTrue((self.tmp / "b" / cc).parent.joinpath(urllib.parse.unquote(raw)).resolve().is_file())
