import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { Jobs, ServerConfig } from './jobs';
import {
  DEFAULT_FILETYPES_KEY,
  FOLDER_WARNING_KEY,
  HIDE_WARNING_KEY,
  PROMPTS,
  SYNC_ACK_KEY,
  UPDATE_BANNER_KEY,
  startingFiletypes,
} from './preferences';
import { UpdateCheck } from './updates';
import { IniSetting, UserSettings } from './user-settings';

const CONFIG: ServerConfig = {
  username: '',
  filetypes: ['JSON', 'HTML', 'EPUB', 'PDF'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
};

const INI: IniSetting[] = [
  { key: 'ExtraWaitTime', value: '15', default: '15', kind: 'integer', about: 'seconds to wait' },
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

async function save(): Promise<void> {
  element.querySelector<HTMLButtonElement>('button.save')!.click();
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
        const values = JSON.parse(String(init.body)).values as Record<string, string>;
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

  it('writes nothing until Save, then writes what each prompt reads', async () => {
    localStorage.setItem(HIDE_WARNING_KEY, 'off');
    await open();

    choose(`[data-prompt="${FOLDER_WARNING_KEY}"] select`, 'skip');
    choose(`[data-prompt="${SYNC_ACK_KEY}"] select`, 'skip');
    choose(`[data-prompt="${HIDE_WARNING_KEY}"] select`, 'ask');
    await settle();
    expect(localStorage.getItem(FOLDER_WARNING_KEY)).toBeNull();
    expect(localStorage.getItem(HIDE_WARNING_KEY)).toBe('off');

    await save();

    expect(localStorage.getItem(FOLDER_WARNING_KEY)).toBe('true');
    expect(localStorage.getItem(SYNC_ACK_KEY)).toBe('true');
    expect(localStorage.getItem(HIDE_WARNING_KEY)).toBeNull();
    expect(element.querySelector('.status.saved')?.textContent).toContain('Saved');
  });

  it('turns the update banner off and on at once, not only on the next visit', async () => {
    const updates = TestBed.inject(UpdateCheck);
    await open();

    choose(`[data-prompt="${UPDATE_BANNER_KEY}"] select`, 'skip');
    await save();
    expect(updates.dismissed()).toBe(true);

    choose(`[data-prompt="${UPDATE_BANNER_KEY}"] select`, 'ask');
    await save();
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

  it('saves the formats a run should start with, and leaves the helper defaults in force when untouched', async () => {
    await open();
    await save();
    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();

    tick('format-HTML', false);
    tick('format-PDF', true);
    tick('format-EPUB', true);
    await save();

    // in the order the helper offers them, whatever order they were ticked in
    expect(JSON.parse(localStorage.getItem(DEFAULT_FILETYPES_KEY)!)).toEqual(['JSON', 'EPUB', 'PDF']);
  });

  it("goes back to the app's defaults", async () => {
    localStorage.setItem(DEFAULT_FILETYPES_KEY, JSON.stringify(['JSON', 'PDF']));
    await open();
    expect(element.querySelector<HTMLInputElement>('input[name="format-PDF"]')!.checked).toBe(true);

    element.querySelector<HTMLButtonElement>('button.reset-formats')!.click();
    await save();

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

  it('sends only the settings that changed, and only on Save', async () => {
    await open();

    const wait = element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!;
    wait.value = '30';
    wait.dispatchEvent(new Event('input'));
    await settle();
    expect(posted).toEqual([]);

    await save();

    expect(posted).toEqual([{ ExtraWaitTime: '30' }]);
  });

  it('says when the helper would not take a value, and keeps the prompts it saved', async () => {
    await open();
    const helper = TestBed.inject(HelperConnection);
    vi.mocked(helper.call).mockImplementation(async () =>
      new Response(JSON.stringify({ error: 'ExtraWaitTime takes a whole number of 0 or more' }), { status: 400 }),
    );
    choose(`[data-prompt="${FOLDER_WARNING_KEY}"] select`, 'skip');
    const wait = element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!;
    wait.value = '-3';
    wait.dispatchEvent(new Event('input'));

    await save();

    expect(element.querySelector('.status.problem')?.textContent).toContain('ExtraWaitTime takes a whole number');
    expect(localStorage.getItem(FOLDER_WARNING_KEY)).toBe('true');
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
});
