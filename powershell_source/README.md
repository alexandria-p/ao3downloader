## Running things

To run the ao3 downloader project as a Powershell script in commandline,

1. Open powershell
2. Enter the following command:
powershell.exe -ExecutionPolicy Bypass -File .\run-locally.ps1

Creates `settings.ini` and `data.json` here on first run if they are missing.


## Directory

The console launcher, and everything the application writes as it runs.

| Path | What it is |
| --- | --- |
| `run-locally.ps1` | Runs the console menu. |
| `ao3_download_helper/` | The python project. See its own README. |
| `settings.ini` | Your settings, including `DownloadFolder`. |
| `data.json` | Saved username and file type choices. |
| `logs/` | `log.jsonl`, written as the app runs. |
| `downloads/` | Where fics land, unless `DownloadFolder` says otherwise. |


