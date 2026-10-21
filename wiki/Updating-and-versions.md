## Updating the app

When a newer version is out, a banner at the top of the page says so. The footer always says `up to date with latest` or `update to latest (X)`, even after you dismiss the banner.

- **Windows, Mac or Linux:** click **Update now**. The app downloads the new version, checks it against GitHub's SHA-256, restarts itself, and the page reloads - a few seconds. On a Mac or Linux it opens in a new window; close the old one. It won't update while a run is going. If anything fails, the old version is put back and the page says why (`update/update.log`).
- **By hand:** unzip the new version over the old folder.

Your `settings.ini` is never replaced: the zip has no `config/` folder. See [[Settings]] for how new settings are added to it.

## Versions

Every deploy is one version, shared by the hosted page and every app zip. The footer shows it.

The `VERSION` file in the repository decides it:

| `VERSION` | Latest release | This deploy |
| --- | --- | --- |
| `2.0.0` (higher) | `1.8.2` | `2.0.0` |
| `1.8.2` (same or lower) | `1.8.2` | `1.8.3` |
| anything | none yet | `VERSION` |

- **Routine deploy:** change nothing - it goes up by one.
- **Bigger step:** raise `VERSION` (three numbers, e.g. `2.0.0`), commit, then deploy.

Each deploy tags the commit `vX.Y.Z` and publishes the Windows, Mac and Linux zips as that release, marked latest. A bundle built on your own computer has no version and never checks for updates.
