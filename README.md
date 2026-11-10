# Pahest

*Pahest* (պահեստ) is Armenian for “reserve”.

Pahest makes a backup of your **Claude Code** and **Codex** sessions on a Mac, and turns it into web pages you can read and search offline. If an app deletes old sessions, or you lose an account, your history is still on your disk.

- It only reads the apps' files. It never changes them and never connects to the internet.
- The backup is ordinary files in `~/pahest-backups`. You need no app and no account to read it.
- Free and open source (MIT license). Not made by, or connected to, Anthropic or OpenAI.

## Screenshots

<!-- Put the image files in docs/screenshots/ and replace each line below with ![…](docs/screenshots/NAME.png) -->

- *Screenshot: the list of all sessions (`index.html`)*
- *Screenshot: one session as a web page*
- *Screenshot: the Pictures page*
- *Screenshot: a run in the Terminal*

## Install and run

You need a Mac. Open the **Terminal** app and paste these two lines (this needs [Homebrew](https://brew.sh)):

```sh
brew install pahest/pahest/pahest
pahest
```

Without Homebrew:

```sh
git clone https://github.com/pahest/pahest.git
cd pahest
./pahest
```

If macOS offers to install the “command line developer tools”, click **Install**, wait, and paste the lines again.

Pahest shows where your backups are and the last three of them, then asks:

```
? Make a backup now? [Y/n]
```

Press **Enter** to start. Press **Ctrl+C** to stop at any time. At the end it shows the backup folder and links to your chats and to the report. Hold **Cmd** and click a link to open it.

To make another backup later, run `pahest` again. Every run makes a new, complete backup.

## Limits

- **macOS only.** On Windows or Linux it stops with a message.
- **Only what is on your Mac.** Chats on claude.ai and chatgpt.com are on the companies' servers, and their terms do not allow a tool to download them. Use each app's own export: *Settings → Privacy → Export data* (Claude) and *Settings → Data controls → Export data* (ChatGPT).
- **Some reasoning cannot be read.** The apps store part of the model's private reasoning encrypted; it is kept, but nobody except the company can read it.
- **Early version (0.1).** Tested on few Macs.

## More

- [Everything in detail](docs/details.md): what is saved, the options, how the backup is checked, disk space.
- [How it is built](AGENTS.md): design rules for people and AI agents who change the code.
- [License](LICENSE): MIT.
