/**
 * Dummy data: debug mode's stand-in for a real library.
 *
 * With debug mode on, User settings can switch the page to a made-up library - works,
 * collections and run history - instead of reading the real one. **There are two, one per
 * storage choice**, worded and sized differently so a glance says which is on screen: *This
 * computer* is a small tea-shop library, *Dropbox* a larger space-station one. Every title,
 * fandom and run says which it belongs to.
 *
 * **Nothing real is touched.** Each library is a `MemoryStore`, built once and kept while dummy
 * data stays on, so hiding a work or making a collection shows as it would and is forgotten when
 * dummy data is turned off. Runs are held while it is on: a run would reach AO3 for real and
 * write its results into a library that does not exist.
 */

import { Injectable, computed, inject, signal } from '@angular/core';
import { DebugMode } from './debug-mode';
import { MemoryStore } from './memory-store';
import { safeGet, safeRemove, safeSet } from './storage';

export const DUMMY_DATA_KEY = 'ao3.dummyData';

export type DummyKind = 'local' | 'dropbox';

@Injectable({ providedIn: 'root' })
export class DummyData {
  private readonly debug = inject(DebugMode);
  /** what User settings says - only in force while debug mode is on (`active`) */
  readonly chosen = signal(safeGet(DUMMY_DATA_KEY) === 'on');
  readonly active = computed(() => this.debug.on() && this.chosen());
  private readonly built = new Map<DummyKind, MemoryStore>();

  set(on: boolean): void {
    this.chosen.set(on);
    if (on) safeSet(DUMMY_DATA_KEY, 'on');
    else {
      safeRemove(DUMMY_DATA_KEY);
      // what was changed in them goes with them
      this.built.clear();
    }
  }

  /** the dummy library for one storage choice, the same one each time while dummy data is on */
  library(kind: DummyKind): MemoryStore {
    let store = this.built.get(kind);
    if (!store) {
      store = dummyLibrary(kind);
      this.built.set(kind, store);
    }
    return store;
  }
}

/** what each dummy library is called, and what makes it look like itself */
interface Theme {
  label: string;
  /** shown on every work and run, so nobody mistakes one library for the other */
  tag: string;
  firstId: number;
  fandoms: string[];
  authors: string[];
  titles: string[];
  collections: { name: string; title: string; description: string }[];
  runs: { action: string; actionName: string; status: string; error?: string }[];
}

const THEMES: Record<DummyKind, Theme> = {
  local: {
    label: 'dummy library - this computer',
    tag: 'Dummy data (This computer)',
    firstId: 9100001,
    fandoms: ['Teacup Chronicles (Dummy - This computer)'],
    authors: ['DummyLocalWriter', 'KettleOnDummy'],
    titles: [
      'Steeped in Starlight',
      'The Last Scone',
      'Oolong and Short',
      'Chamomile Confessions',
      'A Saucer of Secrets',
      'Earl Grey Mornings',
    ],
    collections: [
      { name: 'dummy_local_teashop', title: 'Teashop Fest (This computer dummy)', description: 'A made-up collection on this computer.' },
      { name: 'dummy_local_cosy', title: 'Cosy Corner (This computer dummy)', description: 'Another made-up collection.' },
    ],
    runs: [
      { action: 'quick', actionName: 'Quick scan', status: 'success' },
      { action: 'work', actionName: 'Download/update a specific fic', status: 'partial' },
      { action: 'bookmarks', actionName: 'Full scan', status: 'stopped' },
    ],
  },
  dropbox: {
    label: 'dummy library - Dropbox',
    tag: 'Dummy data (Dropbox)',
    firstId: 9200001,
    fandoms: ['Orbital Station Nine (Dummy - Dropbox)', 'Comet Couriers (Dummy - Dropbox)'],
    authors: ['DummyDropboxPilot', 'CloudSyncDummy', 'NebulaNotes'],
    titles: [
      'Docking Procedures',
      'Zero-G Waltz',
      'The Airlock Letters',
      'Signal from Sector Four',
      'Hydroponics at Midnight',
      'Gravity Well',
      'Courier of Comets',
      'Station Lights',
      'Long Haul Home',
      'Orbit Decay',
      'The Quiet Bulkhead',
      'Solar Wind Sonata',
    ],
    collections: [
      { name: 'dummy_dropbox_station', title: 'Station Week (Dropbox dummy)', description: 'A made-up collection in Dropbox.' },
      { name: 'dummy_dropbox_comets', title: 'Comet Exchange (Dropbox dummy)', description: 'Another made-up collection.' },
      { name: 'dummy_dropbox_drabbles', title: 'Hundred-Word Orbits (Dropbox dummy)', description: 'Short and made up.' },
    ],
    runs: [
      { action: 'quick', actionName: 'Quick scan', status: 'success' },
      { action: 'collections', actionName: 'Index my collections', status: 'success' },
      { action: 'custom', actionName: 'Custom run', status: 'partial' },
      { action: 'bookmarks', actionName: 'Full scan', status: 'failed', error: 'Dummy failure: AO3 is down for maintenance (made up)' },
      { action: 'works', actionName: 'Download several fics', status: 'interrupted' },
    ],
  },
};

const DAY = 24 * 60 * 60 * 1000;
/** a fixed moment, so the dummy library is the same every time it is built */
const NOW = Date.UTC(2026, 10, 1, 9, 30);

function day(offset: number): string {
  return new Date(NOW - offset * DAY).toISOString().slice(0, 10);
}

function moment(offset: number): string {
  return new Date(NOW - offset * DAY).toISOString().replace(/\.\d+Z$/, '+00:00');
}

/** a whole dummy library for one storage choice: index, works, collections and runs */
export function dummyLibrary(kind: DummyKind): MemoryStore {
  const theme = THEMES[kind];
  const store = new MemoryStore([], {}, theme.label);
  const put = (path: string, value: unknown, changed: number) => {
    store.files.set(path, typeof value === 'string' ? value : JSON.stringify(value, null, 2));
    store.changed.set(path, changed);
  };

  const ids: string[] = [];
  theme.titles.forEach((title, n) => {
    const id = String(theme.firstId + n);
    ids.push(id);
    const author = theme.authors[n % theme.authors.length];
    const fandom = theme.fandoms[n % theme.fandoms.length];
    const updated = day(3 + n * 9);
    const complete = n % 3 !== 1;
    const chapters = 1 + (n % 4) * 3;
    const reading = {
      title,
      authors: [author],
      date_created: null,
      date_updated: updated,
      fandoms: [fandom],
      warnings: ['No Archive Warnings Apply'],
      tags: {
        rating: n % 2 ? 'Teen And Up Audiences' : 'General Audiences',
        categories: ['Gen'],
        relationships: [],
        characters: [`Dummy Character ${n + 1}`],
        additional: [theme.tag, n % 2 ? 'Fluff' : 'Slow Burn'],
      },
      summary: `${theme.tag}: a made-up work, number ${n + 1} of ${theme.titles.length}. Nothing here is real.`,
      words: 1500 + n * 2750,
      chapters_published: chapters,
      chapters_total: complete ? chapters : null,
      comments: 4 + n * 3,
      kudos: 40 + n * 17,
      bookmarks: 6 + n,
      hits: 900 + n * 311,
      date_bookmarked: day(10 + n * 7),
      bookmark_notes: n % 4 === 0 ? `A note on a dummy bookmark (${theme.tag}).` : '',
      bookmark_tags: [],
      bookmark_collections: [],
      bookmark_private: false,
      bookmark_rec: n % 5 === 0,
    };
    put(
      `indexing/${id} ${title} - ${author}.json`,
      {
        id,
        link: `https://archiveofourown.org/works/${id}`,
        source: 'dummy data',
        bookmark_type: 'individual work',
        bookmarked: true,
        last_indexed: moment(1),
        indexes: [reading],
      },
      NOW - DAY,
    );
    // an html copy of every work, and a pdf or epub of some, each dated as the index says
    const formats = ['html', ...(n % 2 ? ['pdf'] : []), ...(n % 3 === 0 ? ['epub'] : [])];
    for (const format of formats) {
      put(
        `works/${id} ${title} - ${author} ${updated}.${format}`,
        format === 'html'
          ? workHtml({ title, author, fandom, updated, chapters, summary: reading.summary, tag: theme.tag, n })
          : `${theme.tag} - a made-up ${format} of ${title}`,
        NOW - (3 + n * 9) * DAY,
      );
    }
  });

  theme.collections.forEach((collection, n) => {
    // each holds a few of the works, and one number the index does not have
    const held = ids.filter((_, i) => i % theme.collections.length === n);
    put(
      `collections/${collection.name}.json`,
      {
        name: collection.name,
        link: `https://archiveofourown.org/collections/${collection.name}`,
        source: 'dummy data',
        last_indexed: moment(2),
        indexes: [
          {
            title: collection.title,
            description: `${collection.description} ${theme.tag}.`,
            maintainers: [theme.authors[n % theme.authors.length]],
            tags: [theme.tag],
            active_since: day(400 + n * 30),
            created: day(420 + n * 30),
            flags: n % 2 ? ['Moderated'] : ['Open'],
            challenge_type: n % 2 ? 'Gift Exchange' : 'No Challenge',
            multifandom: false,
            closed: false,
            moderated: n % 2 === 1,
            unrevealed: false,
            anonymous: false,
            fandom_count: 1,
            work_count: held.length + 1,
            bookmark_count: 0,
            subcollection_count: 0,
            parent_collection: null,
            subcollections_link: null,
            subcollections: [],
            work_ids: [...held, String(theme.firstId + 900 + n)],
            bookmark_ids: [],
            external_ids: [],
          },
        ],
      },
      NOW - 2 * DAY,
    );
  });

  theme.runs.forEach((run, n) => {
    const started = NOW - (n * 6 + 1) * DAY;
    const stamp = new Date(started).toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
    const id = `${kind === 'local' ? 'c0ffee' : 'db0b0x'}${String(n).padStart(2, '0')}-dummy-run`;
    const finished = run.status === 'interrupted' ? null : moment(n * 6 + 1 - 0.02);
    const some = ids.slice(n, n + 3);
    const failed = run.status === 'partial' || run.status === 'failed';
    put(
      `runs/${stamp}-${id.slice(0, 8)}.json`,
      {
        id,
        action: run.action,
        actionName: `${run.actionName} (${theme.tag})`,
        started: moment(n * 6 + 1),
        baseline: moment(n * 6 + 1),
        finished,
        status: run.status,
        filetypes: ['JSON', 'HTML'],
        options: {},
        username: 'Example_Reader',
        reindexed: some,
        downloaded: run.status === 'failed' ? [] : some.slice(0, 2),
        updated: run.status === 'success' ? some.slice(0, 1) : [],
        choices: [],
        failures: failed
          ? [{ id: some[2] ?? some[0], link: `https://archiveofourown.org/works/${some[2] ?? some[0]}`, error: 'Dummy failure: HTTP 404 (made up)' }]
          : [],
        skipped: [],
        error: run.error ?? '',
        log: [
          `[${moment(n * 6 + 1).slice(0, 19).replace('T', ' ')} UTC] ${theme.tag}: a made-up run.`,
          `[${moment(n * 6 + 1).slice(0, 19).replace('T', ' ')} UTC] Nothing here reached AO3.`,
        ],
      },
      started,
    );
  });

  return store;
}

/** made-up lines a dummy chapter is built from - gentle, and plainly not anybody's real work */
const LINES = [
  'The kettle sang before anyone had quite decided to make tea, which was how most good afternoons began.',
  'Outside, the weather made up its mind three times and changed it twice.',
  'Nobody said the obvious thing, and so it sat in the middle of the room like a friendly cat.',
  'There was a list on the counter: bread, string, something for the window that would not stay shut.',
  'By evening the lamps were lit, and the long shadows had gone back wherever shadows go.',
  'It was not a grand adventure. It was, everyone agreed later, exactly the right size.',
];

/**
 * A dummy work's html, shaped like AO3's own download - title, author, tags, summary, then its
 * chapters - so opening one from the dummy library looks like opening a real one.
 */
function workHtml(work: { title: string; author: string; fandom: string; updated: string; chapters: number;
  summary: string; tag: string; n: number }): string {
  const chapters = Math.min(work.chapters, 3);
  const body = Array.from({ length: chapters }, (_, c) => {
    const paragraphs = Array.from({ length: 4 }, (_, p) => `<p>${LINES[(work.n + c + p) % LINES.length]}</p>`).join('\n');
    return `<div class="meta group"><h2 class="heading">Chapter ${c + 1}</h2></div>\n<div class="userstuff">\n${paragraphs}\n</div>`;
  }).join('\n');
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${work.title} - ${work.author}</title>
<style>body{font:16px/1.6 Georgia,serif;max-width:40em;margin:2em auto;padding:0 1em;color:#222}
.meta{border-bottom:1px solid #ccc;margin-bottom:1em}.tag{color:#900}dt{font-weight:bold}</style></head>
<body>
<div class="meta">
<p class="tag">${work.tag} - a made-up work, not a real one.</p>
<dl><dt>Fandom:</dt><dd>${work.fandom}</dd><dt>Stats:</dt><dd>Updated: ${work.updated} Chapters: ${work.chapters}</dd></dl>
<h1>${work.title}</h1>
<div class="byline">by <a rel="author">${work.author}</a></div>
<p>Summary</p><blockquote class="userstuff"><p>${work.summary}</p></blockquote>
</div>
${body}
</body></html>`;
}
