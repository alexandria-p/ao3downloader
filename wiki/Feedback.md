## Sending feedback

The **Feedback** tab sits on the right edge of the hosted page and of the Windows, Mac and Linux
apps. Hover over it and it slides out; click it to open the form. It works in the middle of a run,
too.

1. Choose **Positive** or **Negative**.
2. Write what you want to say.
3. Optionally add a name, and tick **Attach the log of my latest run**. Your AO3 username is
   taken out of the log, and **See exactly what will be sent** shows it before it goes. A log
   never holds your password.
4. Click **Send feedback**. Cloudflare's bot check usually passes by itself.

It becomes a **public** GitHub issue labelled `feedback`, so leave out anything private. You don't
need a GitHub account. The form links your issue straight away. It appears in the
[list of feedback](https://github.com/alexandria-p/ao3downloader/issues?q=label%3Afeedback) within
a minute, and replies are posted there.

A bundle you built yourself has no Feedback tab. Use [GitHub issues](https://github.com/alexandria-p/ao3downloader/issues) instead.

## How it works

The page sends the form to a small **Cloudflare Worker** (`feedback_worker/`), not to the helper.
The Worker checks the bot check's token with Cloudflare, then opens the issue with a GitHub token
that can only write issues in this repository. Nothing secret is in the page.

## Setting it up

`FEEDBACK.md` in the repository is the full walk-through. In short:

1. In the Cloudflare dashboard:
   - pick a `workers.dev` subdomain;
   - copy your account ID;
   - make an API token from the **Edit Cloudflare Workers** template.
2. Add a **Turnstile** widget for the hostnames `alexandria-p.github.io` and `localhost`, and copy
   its site key and secret key.
3. Make a fine-grained GitHub token with **Issues: read and write** on this repository only.
4. Add the repository secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
   `TURNSTILE_SECRET_KEY` and `FEEDBACK_GITHUB_TOKEN`.
5. Add the repository variables:
   - `FEEDBACK_URL`: `https://ao3downloader-feedback.<subdomain>.workers.dev`;
   - `TURNSTILE_SITE_KEY`.
6. Run **build & deploy hosted app and github releases**. It makes the labels, deploys the Worker,
   and builds the page and apps with the tab.
