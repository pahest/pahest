# Pahest in detail

*Pahest* (պահեստ) is Armenian for “reserve”: something kept aside in case it is needed.

Pahest makes full local backups of your AI coding sessions on macOS. It is open source (MIT license): [github.com/pahest/pahest](https://github.com/pahest/pahest). One command saves everything these apps keep on your Mac:

- **Claude Code**: every session transcript and the files around it (plans, to-do lists, file checkpoints, pasted images, settings, skills)
- **Codex**: the CLI, the code-editor extension and the desktop app (sessions, pictures, its databases, settings)
- **Claude desktop**: what the app keeps locally (Cowork files and its session disk image, MCP settings)

The backup is plain files on your disk. Open `index.html` in a browser to read and search every session, with no app and no account. If an app deletes old sessions, or you lose access to an account, your history is still there.

**It is a local backup.** It reads only files on this Mac, never connects to the internet, and never changes the apps' files. Your claude.ai and chatgpt.com chats are on the companies' servers, not on your Mac; see [Your online chats](#your-online-chats).

> **Status: early version (0.1), macOS only.** On Windows or Linux it stops at once with a message and reads nothing. It has not been tested on many Macs yet. The tool is not made by, or connected to, Anthropic or OpenAI.

## Quick start

You need macOS and Python 3.9 or newer. The `python3` that comes with Apple's Command Line Tools works. Nothing else needs to be installed.

```sh
git clone https://github.com/pahest/pahest.git
cd pahest
./pahest
```

Or install it as a command with `pipx install git+https://github.com/pahest/pahest` (or `uv tool install …`) and run `pahest`.

Each run checks what is on the Mac, asks one question, makes a **new, complete backup** in a folder named after the start time, verifies it and writes a report. Nothing is ever skipped because it "did not change".

## Options

| Command | What it does |
|---|---|
| `pahest` | Prechecks, questions, backup, verification, report. |
| `pahest --profile` | The same, but with no questions: it uses the answers saved as `default`. |
| `pahest --profile NAME` | The same, with the answers saved as `NAME`. |
| `pahest --templates` | Shows the folder with the templates of the pages and reports. |

Just before the backup starts, an interactive run asks whether to save your answers. A profile is a small JSON file in `~/pahest-backups/profiles/`. You can edit it by hand:

```json
{ "answers": { "backups_folder": "~/pahest-backups", "without_zstd": "continue" } }
```

This version has no scheduler. Run it yourself, or call `pahest --profile` from your own automation.

Exit codes: `0` means OK, `1` means the backup finished with problems (see the report), `2` means it was cancelled or could not start, and `130` means it was interrupted.

## Where things go

```
~/pahest-backups/                  settings, logs and (by default) the backups
  profiles/default.json             saved answers
  logs/index.html                   every run, newest first, with links
  logs/2026-11-08-23-34-12.log/.html/.json
  2026-11-08-23-34-12/              one complete backup
    index.html                      open this first: every session, with search and filters
    README.md                       what each folder holds
    report.html                     what was saved and how it was checked
    backup.log                      everything shown in the terminal
    app-versions.json               versions of the apps whose data was saved
    checksums.sha256                SHA-256 of every file
    source-manifest.jsonl           original path and attributes of every file, folder and link
    deleted-at-source.txt           items the apps deleted that this backup still keeps
    claude-code/  codex/  claude-desktop/   the apps' own files, exactly as found
    readable/                       Markdown and web pages, pictures, databases as JSON
```

A run that is still going is called `…-in-progress`. A run that was stopped is renamed `…-interrupted`.

## What is saved

| App | Saved |
|---|---|
| Claude Code (`~/.claude`) | `projects/` (every session transcript, with subagents, tool output and memory), `history.jsonl` (everything you typed), `plans/`, `todos/`, `file-history/` (file checkpoints), `paste-cache/`, the desktop app's Claude Code sessions, and your settings, `CLAUDE.md`, skills, agents, commands, output styles and hooks |
| Codex (`~/.codex`) | `sessions/` and `archived_sessions/` from the CLI, the code-editor extension and the desktop app, `history.jsonl`, pasted images, generated images, visualizations, ChatGPT project files, the thread list, goals and memories databases, and your config, `AGENTS.md`, rules and skills |
| Claude desktop (local data) | The Cowork files and scheduled tasks, the Cowork session disk image, and `claude_desktop_config.json` (MCP servers) |

The apps' own files are kept exactly as found. Codex compresses its sessions (`.jsonl.zst`); the backup keeps each original and also writes a plain `.jsonl` next to it.

### Readable copies

**Open `index.html` in the backup folder with your web browser.** It lists every session, newest first and grouped by day ("2026 November 9 · Today · 5"). Each day shows one line per session: its title, the folder and app, and the time with how long ago it was ("16:09 · 3h ago"). **Show details** next to a day (or `d` on the keyboard) adds the start of your first message and small tags for the app, where it was opened and the folder; **Show all details** does this for every day, and a search shows details by itself. Click a folder, app or tag to show only those sessions, and click it again to show all.

On a wide window, **Jump to** at the right lists the years. The year you are looking at opens to its months, the month to its weeks, and the week to its days, each with the number of sessions (after your filters). Click one to jump there; the highlight follows as you scroll.

The time-ago text is worked out when you open the page. The bar at the top of every page has **Pictures**, a **More** menu (the backup report, what the folders hold, the original paths and attributes, and each app's own pages, such as everything you typed and Codex's databases) and a **View** menu (light or dark colours, and the font: mono (the default), sans or serif, from the fonts on your Mac). Without a choice, the pages follow your Mac's light or dark mode. Nothing is loaded from the internet: no fonts, styles or scripts.

On a session page, pictures are shown small; click one to see it large (← → move, Esc closes). `[Image #2]` in your message is a link to the picture it stands for.

Five filters at the top narrow the list. Each starts at **All** and shows how many sessions each choice gives. You can combine them with the search box, which also searches the start of each session. **Reset** clears them all:

- **App:** Claude Code, Codex, Claude desktop.
- **Folder:** the project folder the session ran in, with its full path. This one is a box you can type in: type a part of a path, or choose from its list, sorted by the number of sessions or A–Z.
- **Opened in:** Desktop app, Terminal, Code editor, or Automation (sessions started by another program). This comes from what each session recorded.
- **Type:** conversations with you, or subagents and automatic reviews that an app ran by itself.
- **Date:** Today, Yesterday, Last 7 days, Last 30 days, Year to date.

The filters you choose stay in the page address, so they are still set when you come back from a session. Each app has its own list page (in the top bar of every page), made from the same template with the same filters. All pages share one stylesheet and one script in `readable/assets/`, and one list of sessions, `readable/items.js`.

Each session page has **← Previous** and **Next →** at the top and the bottom. They follow the list you came from: if you filtered to "Codex, last 7 days", Next opens the next session in that list, and "↑ List" takes you back to it with your filters.

**Keyboard shortcuts.** On a list: `/` search, `j` / `k` (or ↓ / ↑) move through the list, `Enter` open, `d` details for that day. On a session: `←` / `→` (or `k` / `j`) previous / next, `e` expand all, `Esc` back to the list. Dates are shown as "2026 October 24, 10:00" in your Mac's time zone. File names keep the form 2026-10-24, so they sort by date in Finder.

Every session opens as a web page made from HTML templates: your messages and each answer as separate blocks, the model's visible thinking (click to open), and each tool call as a card with its result, with pictures shown inline. Messages that an app sent in your place, such as "a background task finished" or a message from another session, are marked with who sent them and are not counted as yours. Every message and every code block has a copy button that shows when you point at it; a message is copied as Markdown, the way it was written. Long code blocks, results and messages are folded, with **Expand** to see them in full. At the top, **Show** chooses what the page shows: your messages, the AI's answers, its thinking, tool calls and results, what the app added, and pictures, with the quick choices *Only my messages* and *Conversation only*. Your choice is remembered on every session page, and printing and copying follow it; a line under the header says when parts are hidden. **Expand all** (or `e`) opens everything, **Print / PDF** prints the whole session with everything open (also with ⌘P), and **Markdown** opens the session's `.md` file. It works offline, straight from the disk. Text from the sessions is shown as text and never runs as code in the browser. The same content is also saved as Markdown (`.md`, opens in any text editor), so `readable/` holds:

- **One Markdown file and one web page per session**, with an index per app (by project or month).
- **Pictures as image files**: images you pasted, screenshots that tools took (including the browser screenshots in Codex's own records), and generated images, saved once each. An app stores a picture inside the transcript as base64 text; the page shows the picture, never that text, and the image file has exactly the same bytes. When a picture is part of a longer text that is shown as stored (for example a tool result that an app saved as one piece of JSON text), the picture is also shown below that text.
- **A Pictures page** (`readable/images.html`, linked at the top of the session lists): every picture from every session, each once, newest first by day, with the same filters as the lists and checkboxes for where a picture came from: *You pasted*, *Generated*, *From tools* (what the AI looked at) and *App records* (such as Codex's browser screenshots). It starts with the pictures you pasted and the generated ones. Click a picture, or select it with the arrow keys and press Space, to see it large on top of the page, like Quick Look on a Mac (← → for the previous and next one, Space or Esc to close). **View in chat**, or Enter, opens its session at that picture.
- **Everything you typed**, by date, for Claude Code and for Codex.
- **The Codex databases as JSON**: thread list, goals, memories, one file per table.

**Nothing is shortened, on the web pages or in the Markdown copies.** Every session shows, in full:

- everything you typed, including messages you sent while the model was working, and messages an app sent in your place (marked with who sent them);
- everything the model wrote: text, visible thinking, and every tool call with all of its inputs;
- every tool result with all of its parts (text, pictures, documents, exit codes and other details);
- everything the app added to the conversation: instructions (CLAUDE.md, AGENTS.md), the system prompt, reminders, attached files, hook output, settings, and notices such as "Worked for 2m 44s". These are folded under "Added by Claude Code" or "Added by Codex"; click to open them. When an app repeats the same long text word for word, it is shown in full the first time, and later copies say which one they are the same as. After Codex compacts a session it stores another copy of the earlier conversation; the page lists how many of those items are already shown above and shows the rest in full. Codex also keeps its own record of every step, which mostly repeats the conversation but sometimes holds more: the full output of a command when the model saw a shortened one, MCP tool results, web search results with their links, goals and workspace settings. For each record the page shows, folded, only what is not already on the page, including any picture in it that the page does not show yet, such as the screenshot the browser tool took. Wherever a page shows less than every byte (such a repeat, a compacted copy, or reasoning that is encrypted), it says so and links to the record in the raw transcript, with its line number ("Original: rollout-….jsonl, line 1,234").

Only bookkeeping stays in the raw transcript alone: ids, time stamps, token counts, process ids, settings flags, copies of the API requests, and the apps' own backups of the files they edited. Some reasoning is encrypted by the company and cannot be read by anyone else: Codex stores the model's private reasoning encrypted with OpenAI's key, and Claude Code sometimes stores reasoning encrypted with Anthropic's key. The pages say where it was; the encrypted data itself is kept in the raw transcript. The apps' own files, such as the raw `.jsonl` transcripts, are never changed or shortened; the raw transcript is linked at the top of each page. The prompt histories include the full text of everything you pasted (Claude Code keeps a long paste in its paste cache instead; the page shows that file's text, or says that Claude Code no longer had it), and the Codex databases are exported with every value. Text is never changed on the way to a page: for example, Ruby's `@@class_variables` and diff lines such as `@@@ -1 +1 @@@` stay exactly as they were.

**Cowork** (the Claude desktop app's agent mode) runs in a small virtual machine and keeps its session data in a disk image, `sessiondata.img`, in the app's own format. The backup keeps that file exactly as it is, in `claude-desktop/local/cowork-vm/`, so it can be put back into the app. Its contents cannot be made readable without the app.

### Rebuild the pages of an existing backup

A newer version of pahest can make better pages. To redo them for a backup you already have, without backing up again:

In a normal run you can do the same without a new backup: at the question press `o` (options), then `r`.

```
pahest --regenerate                                       # the newest backup
pahest --regenerate ~/pahest-backups/2026-11-09-17-29-11  # that backup
```

This rebuilds `index.html`, `README.md`, `readable/` and `report.html` from the files already in the backup. It reads no app, and writes only in that backup folder (and the copy of its report in `~/pahest-backups/logs/`). The old pages are kept aside until the new ones are complete and checked; if anything goes wrong, the old ones are put back. `checksums.sha256` is updated for the new pages, the report notes when the pages were rebuilt, and the backup's own files are not touched.

### More about what is kept

**Data that apps deleted is kept.** If an app deletes something that an earlier backup has, each new backup still includes it. An example is Claude Code's 30-day cleanup. These items are listed in `deleted-at-source.txt` and marked in the report and the indexes. So the newest backup is always the most complete one.

**If a part cannot be backed up**, the new backup takes that part's files from the last good backup, and the report says so. Files or folders that cannot be read in one run (for example, no permission) are kept from the last good backup too, without being marked as deleted.

**Symbolic links** (for example a `CLAUDE.md` or `skills/` folder linked from a dotfiles repository) are followed. The backup stores the real files. Links are not followed into caches, installed software (such as `node_modules`), the backups themselves, or back into a folder that contains them; these, and broken links, are listed in the report. Login files are never copied, even when a link leads to them.

**Databases** (Codex's thread list, goals and memories) are copied as plain files together with their `-wal` file. If Codex writes to them during the copy, the copy is made again.

**Original paths and attributes.** `source-manifest.jsonl` at the top of each backup has one line per original file, folder and symbolic link: where it was (as the app saw it, and the real path if a link led there), its type, permissions, owner and group, size, its modified, accessed, changed and created times (to the nanosecond), macOS file flags and extended attributes, link targets, and its SHA-256. The first line names the computer, user and home folder. This is everything needed to put the files back exactly where and how they were, also into another user's home folder. The plain copies of Codex sessions are marked as made from their compressed original. The readable pages have no entry, because the tool made them. Each session page also shows its original file.

**Never copied:** login files (`~/.codex/auth.json`, `~/.claude/.credentials.json`, `~/.claude/sessions/*.key`), `shell-snapshots/` and `session-env/` (these can hold environment variables), and Codex's log and cache databases.

> Claude Code deletes sessions older than 30 days unless you change it. The prechecks warn you if `cleanupPeriodDays` is not set. Add `"cleanupPeriodDays": 3650` to `~/.claude/settings.json` to keep them.

## Your online chats

Your claude.ai and chatgpt.com chats (including the chats in the Claude and ChatGPT desktop apps) are stored on the companies' servers, not on your Mac. The terms of both services forbid downloading them with a script, even for a backup, so this tool does not do it. To keep a copy, use each service's own export:

- **Claude:** Settings → Privacy → Export data. The download link arrives by email and expires after 24 hours.
- **ChatGPT:** Settings → Data controls → Export data. The download link arrives by email.

Keep the ZIP files that you download. A later version of this tool will be able to read them into the backup, offline.

Sessions that run only on a server (Claude Code on the web, Codex cloud tasks) are not on your Mac either, unless you bring them to your computer.

## The tool only reads

The backup never changes anything that belongs to the apps, and it never goes online:

- **Files.** It reads the apps' folders and writes only to three places: the backup folder, `~/pahest-backups`, and a private temporary folder that it removes at the end. A backup folder inside an app's data is refused, for example `~/.claude`, `~/.codex`, `/Applications`, or anything in `~/Library` except iCloud Drive and other cloud folders. The tool compares folders by their identity on disk, so different letter case or a symbolic link cannot get around this check. File names from an older backup can never lead outside the backup folder. Databases are never opened where the apps keep them: the tool copies them first and opens only its own copy, read-only.
- **No network.** The tool has no code that connects to the internet, and it uses no logins, no cookies and no Keychain.
- **A guard enforces both.** During a run, Python's audit hooks check every file operation. Any attempt to write, rename, delete, lock or change a file outside those three places is refused and reported as a problem, so a bug cannot slip through unnoticed. This also covers links, already-open files, and paths typed in a different letter case. The guard also refuses every network connection and name lookup, and it allows only one program, `zstd` (to decompress Codex sessions).
- **The apps' programs are never run.** Versions are read from the apps' `Info.plist` files and install folders.

## Verification

After each backup, the tool checks the new folder:

- Every file is read back, and its size and SHA-256 must match what was written. The checksums are saved in `checksums.sha256`, so you can check again any time: `shasum -a 256 -c checksums.sha256`.
- Every `.zst` file must decompress to exactly its plain copy.
- Copied databases must pass SQLite's integrity check. The check runs on a temporary copy, so the backup itself is not changed.
- Everything a source reported as saved must exist, and no temporary files may be left over.
- Every JSON file and every line of every JSONL file is parsed. If a file copied from an app has a line that does not parse, it is a warning, because the backup is still byte-for-byte the same as the app's own file (often the last line of a session that the app was still writing). JSON files larger than 512 MB are checked by checksum only.
- Images must start like images (a mismatch is a warning).

Problems are listed in `report.html`, and they set exit code 1. Warnings are listed too, but do not change the exit code.

## Disk space

Every backup is complete, but it does not have to use the full space each time:

- **Same APFS disk as the apps** (the normal case on a Mac): files are stored as **clones**. A clone is a complete, independent copy that shares disk blocks with the original until one of them changes. Copying gigabytes takes seconds and uses almost no new space. Deleting any other backup, or the original file, does not affect it.
- **Unchanged generated files** (plain copies of Codex sessions, readable copies) that are byte-for-byte the same as in the previous backup are cloned from it in the same way.
- **On another disk** (for example an exFAT USB drive), files are copied in full.

The first backup of Codex's compressed sessions needs about three times their compressed size for the plain copies, and the readable copies add about 15% of the transcripts' size. The prechecks show the free space and an estimate, such as `1.8+ GB`: the run can need more, for example when a new version of Pahest changes every web page.

## Development

```sh
python3 -m unittest discover -s tests -t tests      # no network, uses a fake home folder
```

The tests never touch your real data or the internet.

The look of the pages and reports is in `src/pahest/templates/`, not in the Python code. `pahest --templates` shows the full path of that folder; after you edit a template, `pahest --regenerate` applies it to a backup:

- `page.html`, `list.html`, `images.html`, `session.html`: the web pages.
- `report.html`, `logs.html`: the backup report and the list of runs.
- `style.css`, `report.css`, `app.js`: the style sheets and the pages' script.

They use a small subset of [Mustache](https://mustache.github.io): `{{name}}` (escaped), `{{{name}}}` (as it is), `{{#name}}…{{/name}}` (lists and conditions), `{{^name}}…{{/name}}` and `{{> file}}`. `src/pahest/template.py` describes it in full. Only the text of the conversations themselves (Markdown to HTML) is built in code. After changing a template, run `pahest --regenerate` to see it on an existing backup.

Each backup keeps a copy of the templates that its pages were made from, in `readable/templates/`. A rebuild replaces only the pages, never the apps' files. A page, a Markdown file or a picture that comes out the same as before is stored as a clone of the old one, so a rebuild takes new disk space only for the pages that changed.

## License

MIT. See [LICENSE](../LICENSE). Claude is a trademark of Anthropic. ChatGPT and Codex are trademarks of OpenAI.
