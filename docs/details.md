# Pahest: reference

Pahest makes a local backup of your sessions with Claude Code and Codex on a Mac. It also makes web pages from the backup, so you can read and search your sessions offline.

The guide with screenshots is at [pahest.revdoku.site](https://pahest.revdoku.site).

- Pahest does not back up your projects. It saves the sessions, not the code and the documents in your project folders.
- Pahest only reads the files of the apps. It does not change them.
- Pahest does not connect to the internet.
- Pahest is an early version (0.1) for macOS only. It is not affiliated with Anthropic or OpenAI.

## Install

You need a Mac with [Homebrew](https://brew.sh).

```sh
brew install pahest/pahest/pahest
pahest
```

To update, run `brew upgrade pahest`.

You can also run Pahest from the source code. You need Python 3.9 or newer.

```sh
git clone https://github.com/pahest/pahest.git
cd pahest
./pahest
```

## Commands

| Command | Result |
|---|---|
| `pahest` | Shows what is on the Mac, asks one question, makes a backup and writes a report. |
| `pahest --profile` | Makes a backup without questions, with the answers that you saved as `default`. |
| `pahest --profile NAME` | The same, with the answers that you saved as `NAME`. |
| `pahest --regenerate` | Rebuilds the pages of the newest backup. Makes no new backup. |
| `pahest --regenerate FOLDER` | Rebuilds the pages of the backup in `FOLDER`. |
| `pahest --templates` | Shows the folder with the templates of the pages and reports. |
| `pahest --version` | Shows the version. |
| `pahest --help` | Shows the help text. |

Each run makes a new, full backup in a new folder. To stop a run, press Ctrl+C. Pahest keeps the files that it saved before you stopped it.

## The question

A run without `--profile` asks `Make a backup now? [Y/n]  (o = options)`.

| Key | Result |
|---|---|
| Enter, or `y` | The backup starts. |
| `n` | Pahest stops and saves nothing. |
| `o`, then `r` | Rebuilds the pages of the last backup. |
| `o`, then `f` | Asks for another backups folder, for this run only. |
| `o`, then `s` | Saves your answers as a profile. |

## The backups folder

Pahest puts the backups in `~/pahest-backups`. To use another folder, press `o` and then `f` at the question, and type the full path.

- The parent folder must exist. Pahest makes only the last folder of the path.
- The folder cannot be in the data of an app: `~/.claude`, `~/.codex`, `/Applications` or `~/Library`.
- On a disk other than the disk of your home folder, Pahest copies each file in full. The backup then takes more time and uses its full size.

Pahest always keeps your profiles and the list of all runs in `~/pahest-backups`.

## Run without questions

A profile is a file with your answers, in `~/pahest-backups/profiles/`.

1. Run `pahest`.
2. If you want another backups folder, press `o`, then `f`, and type the folder.
3. Press `o`, then `s`.
4. Press Enter to use the name `default`, or type a name.

Then run `pahest --profile`, or `pahest --profile NAME`. Pahest has no scheduler. Your script or your automation must start it.

| Exit code | Meaning |
|---|---|
| `0` | The backup is completed and has no problems. |
| `1` | The backup is completed, but it has problems. The report lists them. |
| `2` | You cancelled, or Pahest did not start. |
| `130` | You stopped the backup with Ctrl+C. |

## Rebuild the pages

A rebuild makes the pages of a backup again with your version of Pahest. Use it after an update of Pahest, or after you change a template.

```sh
pahest --regenerate                                       # the newest backup
pahest --regenerate ~/pahest-backups/2026-11-09-17-29-11  # that backup
```

A rebuild does not read the apps, and it does not change the files that Pahest copied from them.

## What Pahest saves

| App | Folder on your Mac | What Pahest saves |
|---|---|---|
| Claude Code | `~/.claude` | The sessions with their subagents and tool output. The text that you typed. Plans, to-do lists, file checkpoints and pasted pictures. Your settings, `CLAUDE.md`, skills, agents, commands and hooks. |
| Codex | `~/.codex` | The sessions and the archived sessions. The text that you typed. Pasted pictures, generated pictures and visualizations. The files of ChatGPT projects. The databases with the thread list, the goals and the memories. Your settings, `AGENTS.md`, rules and skills. |
| Claude desktop | The data folder of the app | The Cowork files, the Cowork disk image, and `claude_desktop_config.json`. |

Pahest does not copy the login files of the apps. The settings files in a backup can hold API keys, so keep the backup private.

A new backup also keeps the sessions that an app deleted after an earlier backup. Thus the newest backup is the most complete one.

## The files of a backup

Each backup is one folder in `~/pahest-backups`. The name of the folder is the date and time of the start.

| File or folder | Content |
|---|---|
| `index.html` | The list of all sessions, with search and filters. Open this file first. |
| `report.html` | What Pahest saved, and the problems that it found. |
| `readable/` | The copies that you can read: one web page and one Markdown file for each session, and each picture as an image file. |
| `claude-code/`, `codex/`, `claude-desktop/` | The files of the apps, without a change. |
| `backup.log` | The text that Pahest printed during the run. |
| `checksums.sha256` | A SHA-256 checksum of each file. |
| `source-manifest.jsonl` | The original path of each file on your Mac. |
| `deleted-at-source.txt` | The items that an app deleted and that this backup keeps. |

`~/pahest-backups/logs/index.html` lists all runs.

## Limits

- Pahest runs on macOS only. On Windows or Linux it stops with a message.
- Pahest saves only the files on your Mac. It does not save your chats on claude.ai and chatgpt.com, or sessions that run only on a server. Use **Export data** in the settings of Claude and of ChatGPT for these chats.
- A part of the reasoning of the AI is encrypted by Anthropic or OpenAI. Pahest keeps it, but you cannot read it.
- Pahest keeps the Cowork disk image of the Claude desktop app, but you cannot read its content without the app.
- Pahest has no command that puts a session back into an app.

## Help and development

To report a problem, open an [issue](https://github.com/pahest/pahest/issues). To change the code, read [CONTRIBUTING.md](../CONTRIBUTING.md) and [AGENTS.md](../AGENTS.md).

## License

MIT. See [LICENSE](../LICENSE). Claude is a trademark of Anthropic. ChatGPT and Codex are trademarks of OpenAI.
