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
- **Your AO3 time zone** - the zone AO3 shows your dates in (the one in your AO3 preferences).
  It starts as this browser's own. AO3's listings give only a date, so a scan turns its floor
  and ceiling - the moment the last scan started, kept in UTC - into a date in this zone before
  comparing: a fic AO3 dates on or after it is never passed over. Each run's log says which
  zone it used. Reset to defaults puts it back to this browser's.
- **settings.ini** - the settings below, on a copy whose helper runs on your computer. The
  hosting settings (`HelperUrl`, `RequirePasscode`, `PageOrigin`) are left to the file itself.

Prompts, formats and your AO3 time zone are kept by **this browser** - another browser, a private window or
another device has its own, and clearing the site's data resets them. settings.ini is a file
on your computer, the same in every browser.

**Reset to defaults**, at the top, first lists every value it would change - what it is
now, and the default it goes back to - then sets every prompt to **Ask always**, the
formats to the app's own, and every settings.ini value to the one your copy came with - for
the Windows, Mac and Linux apps, the values the release was built with. Each setting shows
its default beside it.

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
| `QuestionTimeoutMinutes` | `30` | Minutes a question a run stops to ask waits for you before it takes its default answer (below). `0` takes the default at once. |
| `UndatedFilesAnswer` | `skip` | Files with no date in their name: `skip` leaves them, `refresh` downloads them again. |
| `QuickScanFloorAnswer` | `full` | A quick scan with nothing to measure back to: `full` reads the whole listing, `since` goes back to when the index was last written. |
| `DuplicateCopiesAnswer` | `leave` | Older copies beside the newest: `leave` keeps them, `newest` deletes the older ones. |
| `FicHubAnswer` | `yes` | Ask FicHub for works AO3 would not give. |
| `FicHubOlderCopyAnswer` | `yes` | Take a format FicHub only has an older version of, when you have no copy at all. |
| `OverwriteNewerCopyAnswer` | `no` | Let an overwriting run replace a copy newer than the one it is writing. |
| `RequestTimeoutSeconds` | `60` | How long one request to AO3 may take before it's tried again. |
| `StillWaitingSeconds` | `15` | How often the log says "still waiting" while a request is slow. |
| `MaintenanceRetries` | `2` | Extra tries when AO3 shows its maintenance page. |
| `MaintenanceRetrySeconds` | `30` | Seconds between those tries. |
| `RetryMaxWaitSeconds` | `30` | The longest wait before retrying a failed request (the wait doubles each time). |
| `LibraryTimeoutMinutes` | `15` | How long a run waits for the page to read or write a library file. |
| `PageGoneSeconds` | `30` | How long a run waits for a closed or dropped page to come back before giving up. |
| `HelperUrl` | `http://127.0.0.1:4400` | Where the page finds the helper. Only changes for a [[hosted copy|Hosting your own copy]]. |
| `RequirePasscode` | `false` | Makes the helper refuse every request without the passcode. For a hosted copy. |
| `PageOrigin` | *(empty)* | The page allowed to use a hosted helper, e.g. `https://you.github.io`. |
| `SavePassword` | `false` | Left over from the console app. The web page never stores a password. |

The default answers are also what a background run takes when it was not told. A stop always takes the answer that changes nothing. **Reset to defaults** puts all of these back to the values above.

**On a hosted copy** the page can't edit settings.ini, so User settings has its own **Questions a run may ask** section instead: the minutes a question waits and each default answer, saved to this browser. They're sent with every run, and a background run's up-front answers start from them. Reset to defaults goes back to the hosted copy's own (the values above unless its deployment changed them).

## Your file is only ever added to

When a new version adds a setting, it's appended to your file with its explanation and default. When a version stops using one, it's commented out where it stands with a `# DEPRECATED:` line above it. Your own values and comments are never changed.

## Hosted copies and the apps

The deploy workflow writes every setting from a GitHub variable named after it in upper snake case: `ExtraWaitTime` from `EXTRA_WAIT_TIME`. The Windows, Mac and Linux apps use the same variables, but always point at their own helper, with no passcode. See [[Hosting your own copy]].
