<!-- Thank you for your help with Pahest. Read AGENTS.md first: it has the rules and a map of the code. -->

## What this changes

<!-- One or two sentences. Link the issue if there is one, for example: Fixes #12 -->

## Why

<!-- The problem that you saw, or what a user can do after this change. -->

## How you tested it

<!-- The commands that you ran and what you saw. Add a screenshot if a page or the terminal output looks different. -->
<!-- Remove personal data from output and screenshots: user names, project names, session text. -->

## Checklist

- [ ] The tests pass: `python3 -m unittest discover -s tests -t tests`
- [ ] New behavior has a test.
- [ ] Pahest still only reads the data of the apps. It writes nothing to them and does not run them.
- [ ] No network access, and the pages load nothing from the internet.
- [ ] Nothing from a session is shortened. Where a page shows less, it says so and links to the raw transcript.
- [ ] Only the Python standard library is used, and the code runs on Python 3.9.
- [ ] If the pages or the page script changed, I opened the pages in a browser.
- [ ] Messages and documents are in plain, short English.
- [ ] `README.md` or `docs/details.md` is updated if the behavior that a user sees changed.
