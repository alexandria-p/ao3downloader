For **one person**: the page on GitHub Pages, the helper on Render's free plan. Everyone else should use the [[Windows, Mac or Linux app|Getting started]].

It's locked two ways:

- **A passcode.** The page asks for it; the helper checks it and refuses everything without it.
- **An encrypted login.** Your AO3 password is encrypted with the helper's public key, and each encrypted login works once, for five minutes.

Neither secret is ever published: both live in GitHub secrets and Render's environment.

## One-time setup

1. **Make a key pair**, then delete the file once it's in GitHub:
   ```bash
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out helper-private.pem
   ```
2. **Pick a Render service name**, e.g. `ao3-helper` → `https://ao3-helper.onrender.com`.
3. **Add GitHub secrets** (Settings > Secrets and variables > Actions):
   - `AO3DOWNLOADER_PASSCODE` - make it long
   - `AO3DOWNLOADER_PRIVATE_KEY` - the whole `.pem`, including the BEGIN/END lines
   - `RENDER_API_KEY`, `RENDER_SERVICE_ID`, `RENDER_DEPLOY_HOOK` - from step 6
4. **Add GitHub variables.** `HELPER_URL` is required: the Render address. Every other [[setting|Settings]] has a variable in upper snake case (`EXTRA_WAIT_TIME`...), and unset ones keep their defaults.
5. **Turn on Pages** (Settings > Pages > Source: GitHub Actions), then run **Actions > deploy hosted app**. The first run publishes the helper image and stops on purpose. Make the image public: your profile > Packages > `ao3downloader-helper` > Change visibility.
6. **Create the Render service:** New > Web Service > Existing image > `ghcr.io/<you>/ao3downloader-helper:latest`, Free. Its first start fails for lack of a passcode - expected. Copy the service id (`srv-...`), the deploy hook and an API key into the secrets.
7. **Run deploy hosted app again.** Open `https://<you>.github.io/<repo>/app/` and type the passcode.
8. **Dropbox:** add the page's exact address to your Dropbox app's Redirect URIs.

## Deploying changes

Run **deploy hosted app**. It deploys the helper before the page, and builds the Windows, Mac and Linux apps alongside. Each run is a new [[version|Updating and versions]].

## Things to know

- **Keep Render to one instance** - runs are held in the helper's memory.
- **Free Render services sleep** after about 15 minutes idle, and take up to a minute to wake. A background run keeps it awake; a paused one doesn't.
- **Deploying ends a background run.** Wait for it to finish, or resume it afterwards.
- **The page must be opened over https** - browsers only encrypt on secure pages.
- **AO3 sees Render's IP**, which may be rate-limited sooner than a home connection. `EXTRA_WAIT_TIME` is the knob.
