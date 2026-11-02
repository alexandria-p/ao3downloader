import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { Jobs, ServerConfig } from './jobs';
import {
  BROWSER_NOTICE_KEY,
  DEFAULT_FILETYPES_KEY,
  FOLDER_WARNING_KEY,
  HIDE_WARNING_KEY,
  PROMPTS,
  SYNC_ACK_KEY,
  UPDATE_BANNER_KEY,
  startingFiletypes,
} from './preferences';
import { UpdateCheck } from './updates';
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

  // region prompts

  it('lists every prompt that offers "do not ask again", grouped by area, even ones never shown', async () => {
    await open();

    const areas = Array.from(element.querySelectorAll('.prompts h4')).map((h) => h.textContent?.trim());
    expect(areas).toEqual(['Your library', 'Runs', 'Updates']);
    const rows = Array.from(element.querySelectorAll('.prompts [data-prompt]'));
    expect(rows.map((r) => r.getAttribute('data-prompt'))).toEqual(PROMPTS.map((p) => p.key));
    // nothing stored yet: every one still asks
    for (const row of rows) expect(row.querySelector('select')!.value).toBe('ask');
    const options = Array.from(rows[0].querySelectorAll('option')).map((o) => o.textContent?.trim());
    expect(options).toEqual(['Ask always', 'Do not ask again']);
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
    expect(toast()).toBe('Saved: "Before you choose a folder" - do not ask again');

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

  it('lists the notice about saving to Dropbox or this device, which otherwise shows only once', async () => {
    await open();
    expect(element.querySelector(`[data-prompt="${BROWSER_NOTICE_KEY}"]`)?.textContent).toContain('Chromium');

    choose(`[data-prompt="${BROWSER_NOTICE_KEY}"] select`, 'ask');
    await settle();
    // shown on every visit from now on - not merely once more
    expect(localStorage.getItem(BROWSER_NOTICE_KEY)).toBe('always');

    choose(`[data-prompt="${BROWSER_NOTICE_KEY}"] select`, 'skip');
    await settle();
    expect(localStorage.getItem(BROWSER_NOTICE_KEY)).toBe('true');
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

  // endregion
  // region where it is kept, and putting it all back

  it('says up front that most of this is kept by this browser, and that settings.ini is not', async () => {
    await open();

    const note = element.querySelector('.browser-note')?.textContent ?? '';
    expect(note).toContain('saved in this browser');
    expect(note).toContain('different browser');
    expect(note).toContain('settings.ini is different');
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
    expect(element.querySelector('.confirm-reset')?.textContent).toContain('Ask always');
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
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();

    expect(localStorage.getItem(SYNC_ACK_KEY)).toBeNull();
    expect(posted).toEqual([]);
  });

  // endregion
});
