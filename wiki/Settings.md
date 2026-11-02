Settings live in `settings.ini`:

- **Windows/Mac/Linux app** - `config/settings.ini`, beside the program
- **Bundle** - `build/config/settings.ini`
- **Development** - `powershell_source/settings.ini`

Edit it while the app is closed - or, in the Windows, Mac or Linux app, a bundle or a
development build, from the **User settings** tab, which changes the values in place and
keeps your comments. A change there takes effect from the next run. The hosted copy's
settings come from its deployment, so the tab does not offer them there.

## The User settings tab

- **Prompts** - every message that offers "don't ask again", grouped by where it appears,
  each set to **Ask always** or **Do not ask again**, including ones you have not seen yet.
  That includes the first-visit notice about saving to Dropbox or this device (with its
  warning for browsers that are not Chromium): set to **Ask always**, it shows every time
  you open the page, with its own "Don't show this again" box.
- **Default download formats** - the formats ticked when a run's window opens. You can still
  change them in each run. JSON is always on, because it is the index.
- **settings.ini** - the settings below, on a copy whose helper runs on your computer. The
  hosting settings (`HelperUrl`, `RequirePasscode`, `PageOrigin`) are left to the file itself.

Each change is saved as soon as you make it - a settings.ini box when you leave it - and a
message at the bottom says so. Prompts and formats are kept in this browser only.

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
