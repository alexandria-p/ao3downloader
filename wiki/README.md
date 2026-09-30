# wiki/

The source of the repository's GitHub wiki. Edit pages here, not on the wiki: the
**publish wiki** workflow copies this folder to the wiki whenever it changes on `main`,
replacing whatever is there. This README is not published.

A file's name is its page's title, with hyphens for spaces (`Getting-started.md` is
*Getting started*). `_Sidebar.md` is the sidebar on every page. Link pages with
`[[Page name]]`, or `[[text|Page name]]`.

The longer documents in the repository root - `README.md`, `CLAUDE.md`, `TERMINOLOGY.md`,
`HOSTING.md`, `RESUMING.md`, `TECH_DEBT.md` - stay the full record; these pages are the short
version for people using the app.
