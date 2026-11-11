# How to contribute to Pahest

Thank you for your interest in Pahest. Pahest is an early version, and it was tested on few Macs. Each report, idea and correction helps.

This page tells you how to report a problem, how to propose an idea, and how to change the code or the documents.

## Ways to help

| What you can do | How |
| --- | --- |
| Report a problem | Open a [bug report](https://github.com/pahest/pahest/issues/new/choose). |
| Propose an idea | Open an [idea](https://github.com/pahest/pahest/issues/new/choose). |
| Test Pahest on your Mac | Run it and report what did not work. A report from another Mac, or from another version of an app, is useful. |
| Correct the documents | Change `README.md` or `docs/details.md`, then send a pull request. |
| Change the code | Read the rest of this page, then send a pull request. |

For a small correction, send a pull request at once. For a larger change, open an issue first. Then you and the maintainer can agree on the direction before you write the code.

## Keep your data private

Pahest reads private sessions, and each issue and pull request is public. Follow these rules in each issue, pull request, test and screenshot:

- Do not paste text from your sessions.
- Read all output and each log before you paste it. `backup.log` can show the names of your folders and projects.
- Replace your user name with `you`, so that your home folder is `/Users/you`.
- Do not add files from `~/pahest-backups` to a pull request. Invent the data for a test.
- Look at each screenshot before you add it.

## The rules of the project

Each change must keep these rules. [AGENTS.md](AGENTS.md) has the full text.

1. Read only. Pahest never writes to the data of the apps, and it never runs the apps.
2. No network. Pahest never connects to the internet, and its pages load nothing from the internet.
3. Nothing is shortened. The pages show each session in full, and the files of the apps are copied without a change.
4. Each run is a full backup in a new folder.
5. Plain files and no dependencies. The code uses only the standard library of Python, and it runs on Python 3.9.
6. Text from sessions is never trusted. It is shown as text, and it never runs as code.

The maintainer will not merge a change that breaks one of these rules. For example, Pahest will not download chats from claude.ai or chatgpt.com, because the terms of these services do not permit it.

## Set up

You need a Mac, because Pahest runs only on macOS.

1. Install the Command Line Tools of Apple. They include `git` and Python 3.9. If you have them, the command says so.

   ```sh
   xcode-select --install
   ```

2. Fork the repository on GitHub. A fork is your own copy of the repository.
3. Download your fork. Write your GitHub name in the place of `YOUR-NAME`.

   ```sh
   git clone https://github.com/YOUR-NAME/pahest.git
   cd pahest
   ```

You do not have to install more. Pahest has no dependencies.

## Run the tests

Run this command in the folder of the repository:

```sh
python3 -m unittest discover -s tests -t tests
```

The tests take less than a minute. They use a temporary home folder and no network. They never read your real sessions, and they never write to `~/pahest-backups`.

The tests must pass on Python 3.9 and on a current Python. On a Mac with the Command Line Tools, `/usr/bin/python3` is Python 3.9:

```sh
/usr/bin/python3 -m unittest discover -s tests -t tests
```

You can run one file of tests, or only the tests that have a word in their name:

```sh
python3 -m unittest discover -s tests -t tests -p test_store.py
python3 -m unittest discover -s tests -t tests -k templates
```

GitHub runs the same tests for each pull request, with the Python of macOS and with Python 3.13.

## Run your version

The script `pahest` in the repository runs the code of your folder. You do not have to install it.

```sh
./pahest --version
./pahest
```

`./pahest` makes a real backup of your sessions in `~/pahest-backups`, the same as the installed tool. It only reads the data of the apps.

If you changed the pages or the templates, you do not have to make a new backup. Rebuild the pages of the newest backup:

```sh
./pahest --regenerate
```

To use another Python, set `PYTHON`:

```sh
PYTHON=/usr/bin/python3 ./pahest --version
```

## Where things are

| Folder or file | Content |
| --- | --- |
| `src/pahest/` | The code. [AGENTS.md](AGENTS.md) has a table of the files and tells how a run works. |
| `src/pahest/templates/` | All the HTML and CSS, and the script of the pages. |
| `tests/` | The tests. `tests/helpers.py` has the helpers for temporary folders and files. |
| `README.md`, `docs/details.md` | The documents for users. |
| `docs/screenshots/` | The screenshots. |

## Write the change

- Make one change in one pull request. A small pull request gets an answer faster.
- Add a test for new behavior, and for each bug that you corrected.
- Keep HTML and CSS in the templates, not in the Python code.
- Open the pages in a browser after you change the script of the pages (`templates/app.js`). The script has no tests.
- Show each new kind of record or field from an app in full on the page. Add a test in `tests/test_readable.py` that the text is on the page.
- Write messages and documents in plain, short English. Not all users are technical.
- Update `README.md` or `docs/details.md` if a user sees different behavior.
- Do not change the version number. The maintainer sets it for a release.

To add a new app, open an idea first. Then read the part "Working on it" of [AGENTS.md](AGENTS.md), which lists what a new app needs.

## If you use an AI coding tool

You can use Claude Code, Codex or another AI tool to write a change. `AGENTS.md` gives these tools the rules of the project. You are responsible for the change, so read it, run the tests and try it before you send it.

## Send a pull request

1. Make a branch for your change:

   ```sh
   git checkout -b short-name-of-the-change
   ```

2. Make the change, then run the tests.
3. Commit with a short message that says what changed, for example `Report: show the size of each part`.
4. Push the branch to your fork.
5. Open a pull request to the `main` branch of `pahest/pahest`.
6. Fill in the text that GitHub puts into the pull request: what changed, why, and how you tested it.

The maintainer reads each pull request and can ask for changes. Pahest is a small project, so an answer can take some time.

Pahest has the MIT license. When you send a pull request, you agree that your change has the same license.

## Security problems

A security problem is a way to make Pahest do what its rules forbid. For example, Pahest writes into the data of an app, or it connects to the internet. Another example is text from a session that runs as code in the browser.

Do not put the details in a public issue. Open an issue that says only that you found a security problem. The maintainer will then open a private place on GitHub where you can give the details.
