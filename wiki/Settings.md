Settings live in `settings.ini`:

- **Windows/Mac/Linux app** - `config/settings.ini`, beside the program
- **Bundle** - `build/config/settings.ini`
- **Development** - `powershell_source/settings.ini`

Edit it while the app is closed.

| Setting | Default | What it does |
| --- | --- | --- |
| `ExtraWaitTime` | `15` | Seconds to wait after every request to AO3. Raise it if AO3 keeps asking you to slow down. `0` trips the limit almost at once. |
| `MaxRetries` | `30` | Retries for a failed request. `0` retries for ever. |
| `MaxTimeouts` | `3` | Timeouts in a row before giving up on a request. `0` turns this off. |
| `FileNameLength` | `50` | Longest file name before the title is shortened. Keeps you under Windows' path limit. `0` never shortens. |
| `EnableDebugLogging` | `false` | More detail in the helper's log file. |
| `EnableDebugTools` | `false` | Shows the debug runs and the debug panel in the run window. |
| `EnableConsoleLogging` | `false` | Prints every request and every line a run says to the helper's window. Always on in the Windows/Mac/Linux app. Never prints your password or passcode. |
| `PausedRunTimeoutMinutes` | `10` | Minutes a paused background run waits before it's abandoned. `0` never. |
| `HelperUrl` | `http://127.0.0.1:4400` | Where the page finds the helper. Only changes for a [[hosted copy|Hosting your own copy]]. |
| `RequirePasscode` | `false` | Makes the helper refuse every request without the passcode. For a hosted copy. |
| `PageOrigin` | *(empty)* | The page allowed to use a hosted helper, e.g. `https://you.github.io`. |
| `SavePassword` | `false` | Left over from the console app. The web page never stores a password. |

## Your file is only ever added to

When a new version adds a setting, it's appended to your file with its explanation and default. When a version stops using one, it's commented out where it stands with a `# DEPRECATED:` line above it. Your own values and comments are never changed.

## Hosted copies and the apps

The deploy workflow writes every setting from a GitHub variable named after it in upper snake case: `ExtraWaitTime` from `EXTRA_WAIT_TIME`. The Windows, Mac and Linux apps use the same variables, but always point at their own helper, with no passcode. See [[Hosting your own copy]].
