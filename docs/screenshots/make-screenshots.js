// Makes the README's screenshots: the built page against a made-up, safe-for-work library.
//
//   cd gui_source && npx ng build
//   node docs/screenshots/make-screenshots.js            (from the repository root)
//
// The library is written into the browser's private storage (OPFS), in a folder named
// LIBRARY_NAME, and handed to the page as if picked with the folder picker. A stand-in helper
// answers what the page asks before a run starts, so nothing ever reaches AO3. The data below is
// the set chosen for the README - change it here, not in a one-off script, so the next set of
// screenshots shows the same library. No real AO3 username: Example_* and made-up names only.
const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const PAGE = path.join(ROOT, 'gui_source', 'dist', 'ao3-bookmarks', 'browser');
const OUT = process.argv[2] ? path.resolve(process.argv[2]) : __dirname;
const PORT = 4200;
const URL_ = `http://localhost:${PORT}/`;
const LIBRARY_NAME = 'library';
// how every screenshot looks, but for the customisation strip, which shows three looks of its own
const LOOK = { palette: 'strawberry-milk', font: 'lexend' };

// region the library

// id, title, author, fandom, rating, category, chapters, total, updated, bookmarked on, formats, extra
// The first two are the newest bookmarks, so they top the Works tab (sorted by date bookmarked).
const works = [
  {
    id: '90000001', title: 'Spooky Scary Skeletons', author: 'jack_in_the_box', fandom: 'Nightmare Before Christmas',
    rating: 'General Audiences', category: 'Gen', warnings: ['No Archive Warnings Apply'],
    additional: ['Alternate Universe', 'Coffee Shop AU', 'Slice of Life', 'Fluffy', 'Jack Skellington Is a Softy'],
    summary: 'Turns out this bag of old bones can learn new tricks, with a little pumpkin spice and a lot of holiday magic.',
    chapters: 5, total: 5, updated: '2026-11-03', bookmarked: '2026-11-04', formats: ['epub'],
  },
  {
    id: '90000002', title: "I'm Just Like You, You're Just Like Me", author: 'vamp_lover', fandom: 'Sinners (2025)',
    rating: 'Teen And Up Audiences', category: 'Gen', warnings: ['Creator Chose Not To Use Archive Warnings'],
    additional: ['Modern AU', 'Multiverse Theory', 'Angst', 'Bring Your Tissueboxes This Is A Sad One'],
    summary: "In every life, it's always been Smoke and Stack against the world. Back-to-back, back-to-wall.",
    chapters: 9, total: 12, updated: '2026-11-01', bookmarked: '2026-11-02', formats: ['pdf', 'epub', 'azw3'],
  },
  {
    id: '80000001', title: "The Lighthouse Keeper's Garden", author: 'Example_Writer', rating: 'General Audiences', category: 'Gen',
    summary: 'A retired lighthouse keeper plants a garden on a windy island, and the whole village comes to help.',
    chapters: 12, total: 12, updated: '2026-10-30', bookmarked: '2026-10-31', formats: ['html', 'epub'],
    own: { bookmark_rec: true, bookmark_notes: 'Perfect for a rainy afternoon.', bookmark_tags: ['comfort read'] },
  },
  {
    id: '80000002', title: 'Tea for Two Dragons', author: 'Quill_Mouse', rating: 'Teen And Up Audiences', category: 'F/F',
    summary: 'Two dragons open a tea shop. Only one of them knows how to make tea.',
    chapters: 7, total: 20, updated: '2026-10-28', bookmarked: '2026-10-29', formats: ['html', 'pdf'],
  },
  {
    id: '80000003', title: 'A Library of Small Hours', author: 'Paper_Moth', rating: 'General Audiences', category: 'Gen',
    summary: 'A night-shift librarian and the regulars who only ever visit after midnight.',
    chapters: 3, total: 3, updated: '2026-10-21', bookmarked: '', formats: ['html'], fromLink: true,
  },
  {
    id: '80000004', title: 'Strawberry Season', author: 'Example_Writer', rating: 'General Audiences', category: 'M/M',
    summary: 'A summer of strawberry picking, sunburn and slowly falling in love.',
    chapters: 15, total: null, updated: '2026-10-11', bookmarked: '2026-10-12', formats: ['html', 'epub', 'pdf'],
  },
  {
    id: '80000005', title: 'Notes from the Night Train', author: 'Lantern_Fox', rating: 'Teen And Up Audiences', category: 'Multi',
    summary: 'Postcards written on a sleeper train crossing the mountains.',
    chapters: 1, total: 1, updated: '2026-09-02', bookmarked: '', formats: ['html'], fromImport: true,
  },
  {
    id: '80000006', title: 'The Cartographer of Clouds', author: 'Quill_Mouse', rating: 'General Audiences', category: 'Gen',
    summary: 'A mapmaker sets out to chart the clouds over her valley, one sky at a time.',
    chapters: 22, total: 22, updated: '2026-08-17', bookmarked: '2026-08-18', formats: ['html', 'epub'],
  },
];

const collection = {
  name: 'spookyoctoberfest2026', link: 'https://archiveofourown.org/collections/spookyoctoberfest2026',
  last_indexed: '2026-11-05T10:00:00+00:00',
  indexes: [{
    title: 'Spooky Octoberfest 2026', description: 'A month of spooky bingo prompts.',
    maintainers: ['Example_Moderator'], tags: ['scary', 'themed'], active_since: '2026-10-01', created: '2026-09-20',
    flags: ['Open', 'Moderated'], challenge_type: 'Prompt Meme', multifandom: true, closed: false, moderated: true,
    unrevealed: false, anonymous: false, fandom_count: 9, work_count: 4, bookmark_count: 0, subcollection_count: 0,
    parent_collection: null, subcollections_link: null, subcollections: [],
    work_ids: ['90000001', '90000002', '80000003', '80000005'], bookmark_ids: [], external_ids: [],
  }],
};

// made in FicFairy, so never synced back to AO3
const custom = {
  name: 'custom-0123456789', custom: true, link: null, title: 'My local collection',
  description: 'Some of my favorites', tags: ['comfort', 'found-family'], maintainers: [], closed: true, moderated: true,
  unrevealed: false, anonymous: false, multifandom: false, challenge_type: 'No Challenge',
  work_ids: ['80000001', '80000004', '80000006'], bookmark_ids: [], external_ids: [],
  indexes: [{ last_indexed: '2026-11-05' }],
};

const base = {
  filetypes: ['JSON', 'HTML', 'EPUB'], options: {}, reindexed: [], downloaded: [], updated: [], choices: [],
  skipped: [], failures: [], error: '', username: 'Example_Reader', log: ['[2026-11-05 09:00:00 UTC] logging in'],
};
const runs = [
  ['20261105T090000Z-aaaa1111.json', {
    ...base, id: 'aaaa1111-1', action: 'quick', actionName: 'Quick Scan', status: 'success',
    started: '2026-11-05T09:00:00+00:00', finished: '2026-11-05T09:12:00+00:00',
    reindexed: ['90000001', '90000002'], downloaded: ['90000001', '90000002'], updated: ['80000001'],
  }],
  ['20261102T090000Z-bbbb2222.json', {
    ...base, id: 'bbbb2222-2', action: 'works', actionName: 'Download/update several fics', status: 'partial',
    started: '2026-11-02T09:00:00+00:00', finished: '2026-11-02T09:05:00+00:00', reindexed: ['80000003'],
    downloaded: ['80000003'],
    failures: [{ id: '80000098', link: 'https://archiveofourown.org/works/80000098', error: 'EPUB: 404' }],
  }],
  ['20261028T090000Z-cccc3333.json', {
    ...base, id: 'cccc3333-3', action: 'bookmarks', actionName: '(Full scan) Reindex & Update All', status: 'success',
    started: '2026-10-28T09:00:00+00:00', finished: '2026-10-28T11:40:00+00:00',
    reindexed: works.map((w) => w.id), downloaded: works.map((w) => w.id),
  }],
];

function entry(w) {
  const reading = {
    indexed_on: '2026-11-05T10:00:00+00:00', id: w.id, link: `https://archiveofourown.org/works/${w.id}`, title: w.title,
    authors: [w.author], date_created: null, date_updated: w.updated, fandoms: [w.fandom || 'Original Work'],
    warnings: w.warnings || ['No Archive Warnings Apply'],
    tags: {
      rating: w.rating, categories: [w.category], relationships: [], characters: w.additional ? [] : ['Original Character'],
      additional: w.additional || ['Fluff', 'Cozy', 'Found Family'],
    },
    summary: w.summary, words: 3800 * w.chapters, chapters_published: w.chapters, chapters_total: w.total,
    comments: 12 * w.chapters, kudos: 240 + 31 * w.chapters, bookmarks: 40 + 3 * w.chapters, hits: 3000 + 410 * w.chapters,
    date_bookmarked: w.bookmarked, bookmark_notes: '', bookmark_tags: [], bookmark_collections: [],
    bookmark_private: false, bookmark_rec: false, ...(w.own || {}),
  };
  const doc = {
    id: w.id, link: reading.link, source: 'https://archiveofourown.org/users/Example_Reader/bookmarks',
    bookmarked: !!w.bookmarked, last_indexed: reading.indexed_on, indexes: [reading],
  };
  if (w.fromLink) doc.from_link = true;
  if (w.fromImport) doc.from_import = true;
  return doc;
}

// endregion

// region the page

/** serves the built page, as the app does, on localhost:4200 */
function serve() {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.woff': 'font/woff', '.otf': 'font/otf',
    '.ico': 'image/x-icon' };
  const server = http.createServer((req, res) => {
    let file = path.join(PAGE, decodeURIComponent(new URL(req.url, URL_).pathname));
    if (!file.startsWith(PAGE) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(PAGE, 'index.html');
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(PORT, () => resolve(server)));
}

async function setUp(page, { issues }) {
  await page.evaluate(async ({ name, entries, files, collection, custom, runs, issues }) => {
    const top = await navigator.storage.getDirectory();
    for await (const old of top.keys()) await top.removeEntry(old, { recursive: true });
    const root = await top.getDirectoryHandle(name, { create: true });
    const write = async (dir, file, text) => {
      const w = await (await dir.getFileHandle(file, { create: true })).createWritable();
      await w.write(text); await w.close();
    };
    const indexing = await root.getDirectoryHandle('indexing', { create: true });
    const worksDir = await root.getDirectoryHandle('works', { create: true });
    for (const e of entries) {
      const r = e.indexes[0];
      await write(indexing, `${e.id} ${r.title} - ${r.authors[0]}.json`, JSON.stringify(e));
    }
    for (const file of files) await write(worksDir, file, '<p>A made-up work.</p>');
    if (issues) {
      // files you already had: two works with no index entry, and one with no date in the name
      await write(worksDir, '80000101 Moonlit Market - Paper_Moth.html', '<p>x</p>');
      await write(worksDir, '80000102 Snowbound Bakery - Lantern_Fox.epub', 'x');
      await write(worksDir, '80000002 Tea for Two Dragons - Quill_Mouse.epub', 'x');
    }
    const collections = await root.getDirectoryHandle('collections', { create: true });
    await write(collections, `${collection.name}.json`, JSON.stringify(collection));
    await write(await collections.getDirectoryHandle('custom', { create: true }), `${custom.name}.json`, JSON.stringify(custom));
    const runsDir = await root.getDirectoryHandle('runs', { create: true });
    for (const [file, run] of runs) await write(runsDir, file, JSON.stringify(run));
    await root.getDirectoryHandle('images', { create: true });
  }, {
    name: LIBRARY_NAME,
    entries: works.map(entry),
    files: works.flatMap((w) => w.formats.map((f) => `${w.id} ${w.title.replace(/[\\/:*?"<>|]/g, '')} - ${w.author} ${w.updated}.${f}`)),
    collection, custom, runs, issues,
  });
}

async function open(browser, o = {}) {
  const page = await browser.newPage({
    viewport: o.viewport || { width: 1100, height: 760 }, deviceScaleFactor: 2,
    ...(o.windows ? { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36' } : {}),
  });
  await page.addInitScript(([palette, font, windows, name]) => {
    if (palette) localStorage.setItem('ao3.palette', palette);
    if (font) localStorage.setItem('ao3.font', font);
    if (windows) {
      Object.defineProperty(Navigator.prototype, 'platform', { get: () => 'Win32' });
      Object.defineProperty(Navigator.prototype, 'userAgentData', { get: () => ({ platform: 'Windows' }) });
    }
    localStorage.setItem('ao3.browserNoticeSeen', 'true');
    localStorage.setItem('ao3.folderWarningDismissed', 'true');
    localStorage.setItem('ao3.ao3TimeZone', 'UTC');
    const grant = async () => 'granted';
    FileSystemHandle.prototype.queryPermission = grant;
    FileSystemHandle.prototype.requestPermission = grant;
    // the folder picker hands over the made-up library, so the top bar names it
    window.showDirectoryPicker = async () => (await navigator.storage.getDirectory()).getDirectoryHandle(name, { create: true });
  }, ['palette' in o ? o.palette : LOOK.palette, 'font' in o ? o.font : LOOK.font, !!o.windows, LIBRARY_NAME]);
  // a stand-in helper: only what the page asks before a run starts, so nothing reaches AO3
  await page.route('http://127.0.0.1:4400/**', async (route) => {
    if (o.noHelper) return route.abort('connectionrefused');
    const u = new URL(route.request().url());
    const json = (body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body),
      headers: { 'Access-Control-Allow-Origin': '*' } });
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: {
      'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' } });
    if (u.pathname === '/api/config') return json({ username: 'Example_Reader', filetypes: ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML', 'JSON'],
      forced: ['JSON'], defaults: ['JSON', 'HTML'], zoneLookup: true });
    if (u.pathname === '/api/jobs') return json({ jobs: [] });
    if (u.pathname === '/api/runs/floors') {
      const all = (JSON.parse(route.request().postData() || '{}').runs || []).filter((r) => r.action === 'bookmarks' && r.status === 'success');
      return json({ runs: all });
    }
    return json({});
  });
  await page.goto(URL_);
  await setUp(page, { issues: !!o.issues });
  await page.reload();
  const pick = page.getByRole('button', { name: /choose.*folder/i }).first();
  if (await pick.count()) await pick.click();
  await page.waitForTimeout(2500);
  return page;
}

const tab = (page, name) => page.locator('nav.views button', { hasText: name }).first().click();

/** the three looks, cut into strips and stacked into one picture */
async function stack(browser, files, name) {
  const page = await browser.newPage({ viewport: { width: 2200, height: 1984 }, deviceScaleFactor: 1 });
  const strips = files.map((f) => `<div style="height:660px;overflow:hidden"><img src="data:image/png;base64,${fs.readFileSync(f).toString('base64')}" style="display:block;width:2200px"></div>`);
  await page.setContent(`<body style="margin:0;background:#fff;display:flex;flex-direction:column;gap:2px">${strips.join('')}</body>`);
  await page.screenshot({ path: path.join(OUT, name) });
  await page.close();
}

// endregion

(async () => {
  if (!fs.existsSync(path.join(PAGE, 'index.html'))) {
    console.error(`No built page at ${PAGE} - run "npx ng build" in gui_source first.`);
    process.exit(1);
  }
  const server = await serve();
  const browser = await chromium.launch();
  const shot = (page, file) => page.screenshot({ path: path.join(OUT, file) });
  try {
    let page = await open(browser);
    await shot(page, 'works.png');

    await page.getByRole('button', { name: 'Quick Scan' }).first().click();
    await page.waitForTimeout(1500);
    await shot(page, 'quick-scan.png');
    for (const label of ['Cancel', 'Close']) {
      const b = page.locator('app-download-dialog').getByRole('button', { name: label, exact: true });
      if (await b.count()) { await b.first().click(); break; }
    }
    await page.waitForTimeout(400);

    await tab(page, 'Collections'); await page.waitForTimeout(600);
    await shot(page, 'collections.png');
    await tab(page, 'History'); await page.waitForTimeout(1500);
    await shot(page, 'history.png');
    await page.close();

    page = await open(browser, { issues: true });
    await page.waitForTimeout(1000);
    await shot(page, 'import.png');
    await page.close();

    const looks = [];
    for (const [file, o] of [
      ['custom-strawberry-milk.png', { palette: 'strawberry-milk', font: '' }],
      ['custom-charcoal-typewriter.png', { palette: 'charcoal', font: 'mono' }],
      ['custom-lavender-gaegu.png', { palette: 'lavender', font: 'gaegu' }],
    ]) {
      page = await open(browser, o);
      await page.waitForTimeout(800);
      const where = path.join(require('os').tmpdir(), file);
      await page.screenshot({ path: where });
      looks.push(where);
      await page.close();
    }
    await stack(browser, looks, 'customisation.png');

    page = await open(browser, { viewport: { width: 420, height: 860 } });
    await page.waitForTimeout(800);
    await shot(page, 'custom-narrow.png');
    await page.close();
  } finally {
    await browser.close();
    server.close();
  }
})();
