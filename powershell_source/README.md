## What is here

The python project, the config it reads, and everything the application writes as it runs.

The console menu that used to live here has been removed, along with the parts of the python
package only it reached. What remains is the local helper the web UI talks to - see
[the repository README](../README.md) for how to run it, and
[CLAUDE.md](../CLAUDE.md) for how it is put together.

## Directory

| Path | What it is |
| --- | --- |
| `ao3_download_helper/` | The python project. See its own README. |
| `settings.ini` | Your settings, including `DownloadFolder`. |
| `data.json` | Saved username, if one was ever saved. Not created by the web UI. |
| `logs/` | `log.jsonl`, written as the app runs. |
| `downloads/` | Where fics land, unless `DownloadFolder` says otherwise. Holds `indexing/`, `collections/`, `images/` and `runs/` alongside the works themselves. |

`settings.ini` and `data.json` here are what the **development** build reads. A generated
bundle keeps its own in `build/config/`.
