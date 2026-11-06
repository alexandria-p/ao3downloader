import { DebugMode } from './debug-mode';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { Jobs, ServerConfig } from './jobs';
import {
  ANSWER_DEFAULTS_KEY,
  AO3_TIME_ZONE_KEY,
  BROWSER_NOTICE_KEY,
  QUESTION_TIMEOUT_KEY,
  DEFAULT_FILETYPES_KEY,
  FOLDER_WARNING_KEY,
  HIDE_WARNING_KEY,
  PROMPTS,
  SYNC_ACK_KEY,
  UPDATE_BANNER_KEY,
  startingFiletypes, promptLabels } from './preferences';
import { UpdateCheck } from './updates';
import { IMPORT_EXCLUDED_FILE, LibraryImports } from './imports';
import { Library } from './library';
import { LibraryStore } from './library-store';
import { CUSTOM_FONT, CUSTOM_FONT_KEY, FONT_KEY, PALETTES, PALETTE_KEY, paletteById } from './appearance';
import { IniSetting, TOAST_MS, UserSettings } from './user-settings';

const CONFIG: ServerConfig = {
  username: '',
  filetypes: ['JSON', 'HTML', 'EPUB', 'PDF'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
};

const INI: IniSetting[] = [
  { key: 'ExtraWaitTime', value: '15', default: '40', kind: 'integer', about: 'seconds to wait' },
  { key: 'EnableDebugTools', value: 'false', default: 'false', kind: 'boolean', about: 'a debug panel' },
];

let fixture: ComponentFixture<UserSettings>;
let element: HTMLElement;
let posted: unknown[];
let iniAnswer: { editable: boolean; file?: string; settings: IniSetting[] };

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  fixture.detectChanges();
}

async function open(): Promise<void> {
  fixture = TestBed.createComponent(UserSettings);
  element = fixture.nativeElement as HTMLElement;
  await settle();
}

function choose(selector: string, value: string): void {
  const select = element.querySelector<HTMLSelectElement>(selector)!;
  select.value = value;
  select.dispatchEvent(new Event('change'));
}

function tick(name: string, on: boolean): void {
  const box = element.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
  box.checked = on;
  box.dispatchEvent(new Event('change'));
}

function toast(): string {
  return element.querySelector('.toast')?.textContent?.trim() ?? '';
}

async function leave(selector: string, value: string): Promise<void> {
  const input = element.querySelector<HTMLInputElement>(selector)!;
  input.value = value;
  input.dispatchEvent(new Event('change'));
  await settle();
}

describe('UserSettings', () => {
  beforeEach(() => {
    localStorage.clear();
    posted = [];
    iniAnswer = { editable: true, file: '/home/me/config/settings.ini', settings: INI };
    TestBed.configureTestingModule({ imports: [UserSettings] });
    TestBed.inject(Jobs).config.set(CONFIG);
    const helper = TestBed.inject(HelperConnection);
    vi.spyOn(helper, 'call').mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/api/settings-file' && init?.method === 'POST') {
        const sent = JSON.parse(String(init.body));
        if (sent.reset) {
          posted.push({ reset: true });
          const settings = iniAnswer.settings.map((s) => ({ ...s, value: s.default }));
          return new Response(JSON.stringify({ ...iniAnswer, settings }), { status: 200 });
        }
        const values = sent.values as Record<string, string>;
        posted.push(values);
        const settings = iniAnswer.settings.map((s) => ({ ...s, value: values[s.key] ?? s.value }));
        return new Response(JSON.stringify({ ...iniAnswer, settings }), { status: 200 });
      }
      if (path === '/api/settings-file') return new Response(JSON.stringify(iniAnswer), { status: 200 });
      if (path === '/api/config') return new Response(JSON.stringify(CONFIG), { status: 200 });
      return new Response('{}', { status: 404 });
    });
  });

  // region appearance

  it('changes the palette at once, keeps it in this browser, and offers it to Reset', async () => {
    await open();
    expect(element.querySelectorAll('.palette').length).toBe(PALETTES.length);
    expect(element.querySelector('.palette.chosen')?.getAttribute('data-palette')).toBe('charcoal');

    const fairy = element.querySelector<HTMLInputElement>('.palette[data-palette="fairy"] input')!;
    fairy.checked = true;
    fairy.dispatchEvent(new Event('change'));
    await settle();

    expect(localStorage.getItem(PALETTE_KEY)).toBe('fairy');
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe(paletteById('fairy').tokens.bg);
    expect(element.querySelector('.palette.chosen')?.getAttribute('data-palette')).toBe('fairy');
    expect(toast()).toContain('Fairy dust');

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    expect(element.querySelector('[data-change="Palette"] .current')?.textContent).toContain('Fairy dust');
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();
    expect(localStorage.getItem(PALETTE_KEY)).toBeNull();
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe(paletteById('charcoal').tokens.bg);
  });

  it('takes a font by name from this computer, once its box is left, and previews it', async () => {
    await open();
    expect(element.querySelector('input[name="customFont"]')).toBeNull();

    choose('select[name="font"]', CUSTOM_FONT);
    await settle();
    expect(toast()).toContain('Type the name of a font');
    await leave('input[name="customFont"]', 'Comic Sans MS";} body{color:red');
    expect(localStorage.getItem(FONT_KEY)).toBe(CUSTOM_FONT);
    // nothing that could close the quote or the declaration is kept
    expect(localStorage.getItem(CUSTOM_FONT_KEY)).toBe('Comic Sans MS bodycolor:red');
    expect(document.documentElement.style.getPropertyValue('--font-body')).toContain('"Comic Sans MS bodycolor:red"');
    expect(element.querySelector<HTMLElement>('.font-preview')!.style.fontFamily).toContain('Comic Sans MS');

    choose('select[name="font"]', 'serif');
    await settle();
    expect(document.documentElement.style.getPropertyValue('--font-body')).toContain('Georgia');
    expect(toast()).toContain('Book (serif)');
    // the name typed is kept, so the custom font can be picked again
    expect(localStorage.getItem(CUSTOM_FONT_KEY)).toBe('Comic Sans MS bodycolor:red');
  });

  // endregion
  // region exclusion lists for imports

  it('empties every exclusion list for imports on Reset exclusion lists for imports', async () => {
    const texts = new Map<string, string>([[IMPORT_EXCLUDED_FILE, JSON.stringify({ excluded: [
      { id: '1', kind: 'files', files: ['1 a.html'] },
      { id: '2', kind: 'index', files: ['2 b.html'] },
      { id: '3', kind: 'dates', files: ['3 c.html'] },
    ] })]]);
    const store = {
      label: 'memory', check: async () => {}, list: async () => ['works/1 a.html', 'works/2 b.html'],
      read: async (path: string) => texts.get(path) ?? null,
      write: async (path: string, body: Response) => (texts.set(path, await body.text()), 0),
      size: async () => null, delete: async () => {}, rename: async () => {}, mkdir: async () => {},
    } as unknown as LibraryStore;
    TestBed.inject(Library).store.set(store);
    const imports = TestBed.inject(LibraryImports);
    await imports.check();
    expect(imports.found()).toEqual([]);
    await open();

    const section = element.querySelector('.import-exclusions')!;
    expect(section.querySelector('h3')?.textContent).toContain('Exclusion lists for imports');
    expect(section.querySelector('.hint')?.textContent).toContain('import-excluded.json');
    const button = section.querySelector<HTMLButtonElement>('button.reset-exclusions')!;
    expect(button.textContent?.trim()).toBe('Reset exclusion lists for imports');
    button.click();
    for (let i = 0; i < 3; i++) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await fixture.whenStable();
    }

    expect(JSON.parse(texts.get(IMPORT_EXCLUDED_FILE)!)).toEqual({ excluded: [] });
    // everything found is offered again
    expect(imports.found().map((w) => w.id)).toEqual(['1', '2']);
    expect(element.textContent).toContain('every exclusion list for imports is empty');
  });

  it('holds the reset until a library is open', async () => {
    await open();
    expect(element.querySelector<HTMLButtonElement>('button.reset-exclusions')!.disabled).toBe(true);
  });

  // endregion

  // region prompts

  it('lists every prompt that offers "do not ask again", grouped by area, even ones never shown', async () => {
    await open();

    const areas = Array.from(element.querySelectorAll('.prompts h4')).map((h) => h.textContent?.trim());
    expect(areas).toEqual(['File imports', 'Your library', 'Runs', 'Updates']);
    const rows = Array.from(element.querySelectorAll('.prompts [data-prompt]'));
    // every one but those kept off the tab (the browser notice), which are still reset
    expect(rows.map((r) => r.getAttribute('data-prompt'))).toEqual(
      PROMPTS.filter((p) => p.listed !== false).map((p) => p.key),
    );
    // nothing stored yet: every one still asks
    for (const row of rows) expect(row.querySelector('select')!.value).toBe('ask');
    const options = Array.from(rows[0].querySelectorAll('option')).map((o) => o.textContent?.trim());
    expect(options).toEqual(['Ask always', 'Do not ask again']);
  });

  it('puts the folder note and the Resolve issues window under File imports, worded for them', async () => {
    await open();
    const imports = [...element.querySelectorAll('.prompts h4')].find((h) => h.textContent?.trim() === 'File imports')!;
    const rows = imports.nextElementSibling!;
    expect([...rows.querySelectorAll('.name')].map((n) => n.textContent?.trim())).toEqual([
      'When loading local files on your machine',
      "Show 'resolve issues' window if a problem was found with your file import",
    ]);
    expect(rows.textContent).toContain('Tell the user how the application finds and identifies files.');
    expect(rows.textContent).toContain('If works are missing an index, files with no date in their name or there are duplicates.');
  });

  it('calls the update banner New app version alert banner, with Show always / Don\'t show', async () => {
    await open();
    const row = element.querySelector(`[data-prompt="${UPDATE_BANNER_KEY}"]`)!;
    expect(row.querySelector('.name')?.textContent?.trim()).toBe('New app version alert banner');
    expect([...row.querySelectorAll('option')].map((o) => o.textContent?.trim())).toEqual(['Show always', "Don't show"]);
  });

  it('shows a prompt already turned off as "Do not ask again"', async () => {
    localStorage.setItem(HIDE_WARNING_KEY, 'off');
    await open();

    expect(element.querySelector<HTMLSelectElement>(`[data-prompt="${HIDE_WARNING_KEY}"] select`)!.value).toBe('skip');
  });

  it('has no Save button: each choice is written the moment it is made, and a toast says so', async () => {
    localStorage.setItem(HIDE_WARNING_KEY, 'off');
    await open();
    expect(element.querySelector('button.save')).toBeNull();
    expect(toast()).toBe('');

    choose(`[data-prompt="${FOLDER_WARNING_KEY}"] select`, 'skip');
    await settle();
    expect(localStorage.getItem(FOLDER_WARNING_KEY)).toBe('true');
    expect(toast()).toBe('Saved: "When loading local files on your machine" - do not ask again');

    choose(`[data-prompt="${SYNC_ACK_KEY}"] select`, 'skip');
    choose(`[data-prompt="${HIDE_WARNING_KEY}"] select`, 'ask');
    await settle();
    expect(localStorage.getItem(SYNC_ACK_KEY)).toBe('true');
    expect(localStorage.getItem(HIDE_WARNING_KEY)).toBeNull();
    expect(toast()).toContain('ask always');
  });

  it('lets the toast go after a moment', async () => {
    vi.useFakeTimers();
    try {
      fixture = TestBed.createComponent(UserSettings);
      element = fixture.nativeElement as HTMLElement;
      fixture.detectChanges();
      choose(`[data-prompt="${FOLDER_WARNING_KEY}"] select`, 'skip');
      fixture.detectChanges();
      expect(toast()).not.toBe('');

      vi.advanceTimersByTime(TOAST_MS + 1);
      fixture.detectChanges();
      expect(toast()).toBe('');
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps the notice about saving to Dropbox or this device off the tab, and still resets it', async () => {
    localStorage.setItem(BROWSER_NOTICE_KEY, 'true');
    await open();
    expect(element.querySelector(`[data-prompt="${BROWSER_NOTICE_KEY}"]`)).toBeNull();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();
    // shown on every visit from now on - not merely once more
    expect(localStorage.getItem(BROWSER_NOTICE_KEY)).toBe('always');
  });

  it('turns the update banner off and on at once, not only on the next visit', async () => {
    const updates = TestBed.inject(UpdateCheck);
    await open();

    choose(`[data-prompt="${UPDATE_BANNER_KEY}"] select`, 'skip');
    expect(updates.dismissed()).toBe(true);

    choose(`[data-prompt="${UPDATE_BANNER_KEY}"] select`, 'ask');
    expect(updates.dismissed()).toBe(false);
    expect(localStorage.getItem(UPDATE_BANNER_KEY)).toBeNull();
  });

  // endregion

  // region download formats

  it("starts from the app's own defaults, with JSON always ticked", async () => {
    await open();

    const json = element.querySelector<HTMLInputElement>('input[name="format-JSON"]')!;
    expect(json.checked && json.disabled).toBe(true);
    expect(element.querySelector<HTMLInputElement>('input[name="format-HTML"]')!.checked).toBe(true);
    expect(element.querySelector<HTMLInputElement>('input[name="format-EPUB"]')!.checked).toBe(false);
  });

  it('saves the formats a run should start with as each is ticked, and leaves the helper defaults alone until then', async () => {
    await open();
    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();

    tick('format-HTML', false);
    tick('format-PDF', true);
    tick('format-EPUB', true);
    await settle();
    expect(toast()).toBe('Saved: runs start with JSON, EPUB, PDF');

    // in the order the helper offers them, whatever order they were ticked in
    expect(JSON.parse(localStorage.getItem(DEFAULT_FILETYPES_KEY)!)).toEqual(['JSON', 'EPUB', 'PDF']);
  });

  it("goes back to the app's defaults", async () => {
    localStorage.setItem(DEFAULT_FILETYPES_KEY, JSON.stringify(['JSON', 'PDF']));
    await open();
    expect(element.querySelector<HTMLInputElement>('input[name="format-PDF"]')!.checked).toBe(true);

    element.querySelector<HTMLButtonElement>('button.reset-formats')!.click();
    await settle();

    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();
  });

  it('starts a run with the saved formats, never dropping the index or adding one not offered', () => {
    localStorage.setItem(DEFAULT_FILETYPES_KEY, JSON.stringify(['PDF', 'AZW3']));

    expect(startingFiletypes(CONFIG)).toEqual(['JSON', 'PDF']);

    localStorage.removeItem(DEFAULT_FILETYPES_KEY);
    expect(startingFiletypes(CONFIG)).toEqual(['JSON', 'HTML']);
  });

  // endregion

  // region settings.ini

  it("offers settings.ini on a helper on this computer, saying where the file is", async () => {
    await open();

    const rows = Array.from(element.querySelectorAll('.ini [data-setting]'));
    expect(rows.map((r) => r.getAttribute('data-setting'))).toEqual(['ExtraWaitTime', 'EnableDebugTools']);
    expect(element.querySelector('.ini')?.textContent).toContain('/home/me/config/settings.ini');
    expect(rows[0].textContent).toContain('seconds to wait');
  });

  it('writes a setting once its box is left - not while it is being typed', async () => {
    await open();

    const wait = element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!;
    wait.value = '3';
    wait.dispatchEvent(new Event('input'));
    await settle();
    expect(posted).toEqual([]);

    await leave('[data-setting="ExtraWaitTime"] input', '30');
    expect(posted).toEqual([{ ExtraWaitTime: '30' }]);
    expect(toast()).toBe('Saved to settings.ini: ExtraWaitTime=30 - from the next run');

    // leaving it as it is sends nothing
    await leave('[data-setting="ExtraWaitTime"] input', '30');
    expect(posted).toHaveLength(1);
  });

  it('writes a true/false setting as soon as it is picked', async () => {
    await open();

    choose('[data-setting="EnableDebugTools"] select', 'true');
    await settle();

    expect(posted).toEqual([{ EnableDebugTools: 'true' }]);
  });

  it('offers a question\'s default answer as a list of the answers it has', async () => {
    iniAnswer = { editable: true, file: 'settings.ini', settings: [
      { key: 'FicHubAnswer', value: 'yes', default: 'yes', kind: 'choice', choices: ['yes', 'no'],
        about: 'whether to ask FicHub' },
    ] };
    await open();

    const options = [...element.querySelectorAll('[data-setting="FicHubAnswer"] option')]
      .map((x) => x.textContent?.trim());
    expect(options).toEqual(['yes', 'no']);

    choose('[data-setting="FicHubAnswer"] select', 'no');
    await settle();
    expect(posted).toEqual([{ FicHubAnswer: 'no' }]);
  });

  it('says when the helper would not take a value, and puts back what the file still says', async () => {
    await open();
    const helper = TestBed.inject(HelperConnection);
    vi.mocked(helper.call).mockImplementation(async () =>
      new Response(JSON.stringify({ error: 'ExtraWaitTime takes a whole number of 0 or more' }), { status: 400 }),
    );

    await leave('[data-setting="ExtraWaitTime"] input', '-3');

    expect(element.querySelector('.toast.problem')?.textContent).toContain(
      'Not saved: ExtraWaitTime takes a whole number',
    );
    expect(element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!.value).toBe('15');
  });

  it('offers no settings.ini when the helper says it cannot be edited', async () => {
    iniAnswer = { editable: false, settings: [] };
    await open();

    expect(element.querySelector('.ini')).toBeNull();
  });

  it('never asks a hosted helper for its settings.ini', async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    await open();

    expect(element.querySelector('.ini')).toBeNull();
    expect(vi.mocked(TestBed.inject(HelperConnection).call).mock.calls.map((c) => c[0])).not.toContain('/api/settings-file');
  });

  it('on a hosted copy, lets this browser choose what unanswered questions take, starting from the helper\'s', async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    TestBed.inject(Jobs).config.set({ ...CONFIG, settings: { ...CONFIG.settings!,
      answerDefaults: { fichub: 'no' }, questionTimeoutMinutes: 20 } });
    await open();
    // folded away like Prompts, saying where it is kept
    const questions = element.querySelector<HTMLDetailsElement>('details.questions')!;
    expect(questions.open).toBe(false);
    // under Appearance, above Prompts
    const order = [...element.querySelectorAll('.group')].map((g) => g.classList[1]);
    expect(order.slice(0, 5)).toEqual(['formats', 'ao3-zone', 'appearance', 'questions', 'prompts']);
    expect(questions.querySelector('summary .saved-to')?.textContent?.trim()).toBe('Saved to this browser');

    const fichub = element.querySelector<HTMLSelectElement>('[data-question-setting="fichub"] select')!;
    expect(fichub.value).toBe('no');
    expect(element.querySelector<HTMLInputElement>('[data-question-setting="timeout"] input')!.value).toBe('20');

    choose('[data-question-setting="overwrite-older"] select', 'yes');
    await leave('[data-question-setting="timeout"] input', '5');
    expect(JSON.parse(localStorage.getItem(ANSWER_DEFAULTS_KEY)!)).toEqual({ 'overwrite-older': 'yes' });
    expect(localStorage.getItem(QUESTION_TIMEOUT_KEY)).toBe('5');

    // and Reset puts them back to the helper's
    element.querySelector<HTMLButtonElement>('.reset-all')?.click();
    await settle();
    const listed = element.querySelector('.reset-window, [role="dialog"]')?.textContent ?? '';
    expect(listed).toContain('Minutes a question waits for you');
  });

  it('starts the AO3 time zone at this browser\'s own, keeps another when chosen, and Reset puts it back', async () => {
    const own = Intl.DateTimeFormat().resolvedOptions().timeZone;
    await open();
    const select = () => element.querySelector<HTMLSelectElement>('.ao3-zone select')!;
    expect(select().value).toBe(own);

    const other = own === 'Australia/Sydney' ? 'Europe/London' : 'Australia/Sydney';
    choose('.ao3-zone select', other);
    await settle();
    expect(localStorage.getItem(AO3_TIME_ZONE_KEY)).toBe(other);
    expect(toast()).toContain(`AO3 dates are read in ${other}`);

    // the browser's own is not kept, so the setting follows the browser
    choose('.ao3-zone select', own);
    await settle();
    expect(localStorage.getItem(AO3_TIME_ZONE_KEY)).toBeNull();
  });

  it('keeps no question defaults of its own where settings.ini holds them', async () => {
    await open();
    expect(element.querySelector('.questions')).toBeNull();
  });

  // endregion
  // region where it is kept, and putting it all back

  it('offers debug mode on a downloaded app only when settings.ini turns on EnableDebugTools', async () => {
    localStorage.setItem('ao3.debugMode', 'on');
    await open();
    expect(element.querySelector('.group.debug-mode')).toBeNull();
    // what this browser saved is not in force where it is not allowed
    expect(TestBed.inject(DebugMode).on()).toBe(false);

    TestBed.inject(Jobs).config.set({ ...CONFIG, settings: { debugTools: true } } as ServerConfig);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(element.querySelector('.group.debug-mode')).not.toBeNull();
    expect(TestBed.inject(DebugMode).on()).toBe(true);
    localStorage.removeItem('ao3.debugMode');
  });

  it('says at the top right of every section where it is saved, Debug mode always last', async () => {
    TestBed.inject(Jobs).config.set({ ...CONFIG, settings: { ...CONFIG.settings!, debugTools: true } });
    await open();

    const sections = [...element.querySelectorAll('.group')];
    const named = sections.map((g) => [
      g.querySelector('h3')?.textContent?.trim(),
      g.querySelector('.group-head .saved-to')?.textContent?.replace(/\s+/g, ' ').trim(),
    ]);
    expect(named[0]).toEqual(['Default download formats', 'Saved to this browser']);
    expect(named[1]).toEqual(['Your AO3 time zone', 'Saved to this browser']);
    expect(named[2]).toEqual(['Appearance', 'Saved to this browser']);
    expect(named.at(-1)).toEqual(['Debug mode', 'Saved to this browser']);
    expect(named).toContainEqual(['Exclusion lists for imports', 'Saved in your library folder']);
    // a helper on this computer offers its settings.ini
    expect(named).toContainEqual(['settings.ini', 'Saved to settings.ini']);
    expect(element.querySelector('.browser-note')).toBeNull();
  });

  it('folds Appearance away, with the font above the palettes and no note under its title', async () => {
    await open();
    const appearance = element.querySelector<HTMLDetailsElement>('details.appearance')!;
    expect(appearance.open).toBe(false);
    expect(appearance.querySelector('summary h3')?.textContent).toBe('Appearance');
    expect(appearance.textContent).not.toContain('How this page looks');
    const font = appearance.querySelector('.font-choice')!;
    const palettes = appearance.querySelector('.palettes')!;
    expect(font.compareDocumentPosition(palettes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('folds Prompts away too, with its pill still in its title row', async () => {
    await open();
    const prompts = element.querySelector<HTMLDetailsElement>('details.prompts')!;
    expect(prompts.open).toBe(false);
    expect(prompts.querySelector('summary h3')?.textContent).toBe("'Ask again' Prompts");
    expect(prompts.querySelector('summary .saved-to')?.textContent?.trim()).toBe('Saved to this browser');
  });

  it('shows each setting\'s default beside it', async () => {
    await open();

    expect(element.querySelector('[data-setting="ExtraWaitTime"] .default')?.textContent).toContain('default: 40');
  });

  it('asks before resetting, and Cancel changes nothing', async () => {
    localStorage.setItem(HIDE_WARNING_KEY, 'off');
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    expect(element.querySelector('.modal [role=dialog]')).not.toBeNull();
    Array.from(element.querySelectorAll<HTMLButtonElement>('.confirm-reset button'))
      .find((b) => b.textContent?.trim() === 'Cancel')!.click();
    await settle();

    expect(element.querySelector('.confirm-reset')).toBeNull();
    expect(localStorage.getItem(HIDE_WARNING_KEY)).toBe('off');
    expect(posted).toEqual([]);
  });

  it('resets every prompt to ask always, the formats to the app\'s, and settings.ini to its built defaults', async () => {
    for (const prompt of PROMPTS) localStorage.setItem(prompt.key, prompt.dismissed);
    localStorage.setItem(DEFAULT_FILETYPES_KEY, JSON.stringify(['JSON', 'PDF']));
    const updates = TestBed.inject(UpdateCheck);
    updates.dismissed.set(true);
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    // every value that will change, current then default
    const rows = Array.from(element.querySelectorAll('.changes tbody tr')).map((r) =>
      Array.from(r.children).map((c) => c.textContent?.replace(/\s+/g, ' ').trim()),
    );
    expect(rows).toEqual([
      ...PROMPTS.map((p) => [`Prompts ${p.name}`, promptLabels(p).skip, `→ ${promptLabels(p).ask}`]),
      ['Download formats Formats a run starts with', 'JSON, PDF', '→ JSON, HTML'],
      ['settings.ini ExtraWaitTime', '15', '→ 40'],
    ]);
    expect(element.querySelector('.changes tbody tr:last-child .default-value strong')?.textContent).toBe('40');
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();

    for (const row of Array.from(element.querySelectorAll('.prompts [data-prompt] select'))) {
      expect((row as HTMLSelectElement).value).toBe('ask');
    }
    expect(PROMPTS.every((p) => localStorage.getItem(p.key) !== p.dismissed)).toBe(true);
    expect(updates.dismissed()).toBe(false);
    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();
    expect(element.querySelector<HTMLInputElement>('input[name="format-PDF"]')!.checked).toBe(false);
    expect(posted).toEqual([{ reset: true }]);
    expect(element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!.value).toBe('40');
    expect(toast()).toContain('settings.ini holds its defaults');
  });

  it('resets only what this browser keeps when there is no settings.ini to offer', async () => {
    iniAnswer = { editable: false, settings: [] };
    localStorage.setItem(SYNC_ACK_KEY, 'true');
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    expect(element.querySelector('.confirm-reset')?.textContent).not.toContain('settings.ini');
    expect(element.querySelectorAll('.changes tbody tr')).toHaveLength(1);
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();

    expect(localStorage.getItem(SYNC_ACK_KEY)).toBeNull();
    expect(posted).toEqual([]);
  });

  it('says when everything is already at its default, and offers nothing to press', async () => {
    iniAnswer = { editable: true, file: 'settings.ini', settings: INI.map((x) => ({ ...x, value: x.default })) };
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();

    expect(element.querySelector('.confirm-reset .nothing')?.textContent).toContain('already at its default');
    expect(element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.disabled).toBe(true);
  });

  it('shuts the Reset window on Escape, changing nothing', async () => {
    localStorage.setItem(SYNC_ACK_KEY, 'true');
    await open();
    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();

    expect(element.querySelector('.confirm-reset')).toBeNull();
    expect(localStorage.getItem(SYNC_ACK_KEY)).toBe('true');
  });

  // endregion
});
