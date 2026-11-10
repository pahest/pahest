# Pahest: notes for people and AI agents who change the code

Pahest makes full local backups of Claude Code, Codex and Claude desktop data on macOS, and makes them readable offline. Read this before you change anything. The user guide is `README.md` and `docs/details.md`.

## Rules that must not be broken

1. **Read only.** Never write to, or run, the apps (`~/.claude`, `~/.codex`, `~/Library`, `/Applications`). `guard.py` enforces this with an audit hook: writes are allowed only in the backup folder, `~/pahest-backups` and a private temp folder. Do not weaken the guard to make something work.
2. **No network, ever.** The guard refuses sockets, DNS and HTTP. Do not add code that downloads chats from claude.ai or chatgpt.com: the companies' terms do not allow scripted access, even for a backup. Online chats are covered only by the apps' own "Export data".
3. **Nothing is shortened.** Web pages and Markdown copies show every part of a session in full. The raw app files are copied byte for byte and never changed. Where a page shows less than every byte (a repeat, a compacted copy, encrypted data), it says so and links to the line in the raw transcript.
4. **Every run is a full backup** in a new folder named by its start time. Nothing is skipped as "unchanged"; APFS clones only save disk space.
5. **Plain files, no dependencies.** Python 3.9+ standard library only. No database of our own, no server, no scheduler.
6. **Text from sessions is never trusted.** It is escaped in HTML, never run, and can never name a path outside the backup.

## How a run works

`cli.py`: prechecks (`precheck.py`) → questions, or a saved profile (`profile.py`) → copy each source (`sources/`, through `store.py`) → readable copies (`readable.py`) → verification (`verify.py`) → report (`report.py`). `--regenerate` (`regenerate.py`) rebuilds only the readable copies and reports of an existing backup.

| File | What it does |
|---|---|
| `store.py` | Writes files into the backup: clone or copy, SHA-256, carry-forward of items an app deleted. |
| `readable.py` | Reads the raw transcripts of a backup and builds a conversation (`Conv`), then Markdown and web pages. |
| `htmlview.py` | Markdown to HTML, and the values for the page templates. |
| `template.py`, `templates/` | All HTML, CSS and the page script, as Mustache-style templates. Keep markup out of Python. |
| `guard.py` | The read-only and no-network guard. |
| `verify.py`, `report.py` | Checks after the run; `report.html`, `backup.json` and the list of runs. |

## Working on it

- Tests: `python3 -m unittest discover -s tests -t tests`. They use a fake home folder, no network, and must pass on Python 3.9 (`/usr/bin/python3`) and a current Python.
- The page script (`templates/app.js`) has no unit tests. After changing it, open the pages in a browser, or drive them with headless Chrome.
- To try a change on a real backup without making a new one: `./pahest --regenerate`.
- A new app (Gemini CLI, …) needs: a source in `sources/`, a reader in `readable.py`, its list page in `APP_LISTS` and its own pages (prompt history, databases) in `APP_PAGES`. The top bar, the More menu and the filters are built from these tables.
- Pages load nothing from the internet: no CDN, no remote fonts, styles or scripts. Fonts are the computer's own.
- When you add a kind of record or field from an app, show it in full, or list it as bookkeeping in `readable.py`. Add a test in `tests/test_readable.py` that the text is on the page.
- Write messages and documentation in plain, short English: the users are not all technical.

## Limits to keep in mind

- macOS only; `cli.py` stops on other systems.
- Only data on the Mac. claude.ai and chatgpt.com chats are not on the Mac (see rule 2).
- Reasoning that the apps store encrypted cannot be made readable.
- The Cowork disk image of Claude desktop is copied as it is; its contents are not readable without the app.
- Pages can be large (tens of MB); keep the page script free of work that grows with page size at load.
