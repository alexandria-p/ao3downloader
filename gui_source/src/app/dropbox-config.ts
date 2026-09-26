/**
 * The Dropbox app this page signs in through.
 *
 * The app key is **public** - it is sent in the sign-in url for anyone to read, and PKCE is
 * what makes that safe, because there is no client secret to hide. Never put the app
 * secret here; a browser app does not need one and anything in this file ships to every
 * visitor.
 *
 * Empty means this copy has no Dropbox app registered, and the page says so instead of
 * offering a sign-in that cannot work. To set one up, in the Dropbox App Console:
 *
 * 1. Create app -> Scoped access -> **App folder**
 * 2. Permissions: tick `files.metadata.read`, `files.content.read`, `files.content.write`
 *    (`account_info.read` is ticked already), and submit
 * 3. Settings -> OAuth 2 -> Redirect URIs: add every origin the page is served from, with a
 *    trailing slash - `http://localhost:4200/` covers both `ng serve` and the build's
 *    launcher. Dropbox only accepts plain http for `localhost`.
 * 4. Settings -> OAuth 2 -> Allow public clients (Implicit Grant & PKCE): Allow
 * 5. Copy the App key here
 */
export const DROPBOX_APP_KEY = '31mktq7zn2ydrxy';

/**
 * The app folder's name, as set in the App Console - the library lives in
 * `/Apps/<this>/` in Dropbox. Only used to tell people where to look; the api never needs
 * it, because every path an App folder app uses is already inside that folder.
 */
export const DROPBOX_APP_FOLDER = 'ao3-downloader';
