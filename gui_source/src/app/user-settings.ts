import { Component, OnDestroy, inject, signal } from '@angular/core';
import { HelperConnection } from './helper-connection';
import { Jobs, ServerConfig } from './jobs';
import {
  PROMPTS,
  PROMPT_AREAS,
  Prompt,
  UPDATE_BANNER_KEY,
  promptAsks,
  saveDefaultFiletypes,
  setPromptAsks,
  startingFiletypes,
} from './preferences';
import { UpdateCheck } from './updates';

export type Asking = 'ask' | 'skip';

/** one setting in the helper's settings.ini, as `GET /api/settings-file` describes it */
export interface IniSetting {
  key: string;
  value: string;
  default: string;
  kind: 'boolean' | 'integer' | 'text';
  about: string;
}

interface IniFile {
  editable: boolean;
  file?: string;
  settings: IniSetting[];
}

export interface Toast {
  text: string;
  kind: 'saved' | 'problem';
}

/** how long a toast stays up - long enough to read, short enough not to pile up */
export const TOAST_MS = 2500;
/** a problem stays longer: it says what did not happen, which is worth the time to read */
export const PROBLEM_TOAST_MS = 6000;

/**
 * The User settings tab: what this browser remembers, and - on a helper on this computer -
 * the helper's settings.ini.
 *
 * **Every change is saved the moment it is made**, and a toast says so (or says what went
 * wrong) - there is no Save button to forget. A settings.ini value is sent when its box is
 * left or Enter is pressed (`change`, not `input`), so a number half-typed is never written,
 * and one the helper refuses goes back to what the file still says.
 *
 * Every prompt with a "don't ask again" box is listed, from `PROMPTS`, whether or not this
 * browser has met it yet. settings.ini is offered only where the page's helper is on this
 * computer and says it may be edited (`editable`): a hosted copy's file is written by its
 * deployment, and an edit there would be lost on the next restart.
 */
@Component({
  selector: 'app-user-settings',
  templateUrl: './user-settings.html',
  styleUrl: './user-settings.css',
})
export class UserSettings implements OnDestroy {
  private readonly jobs = inject(Jobs);
  private readonly helper = inject(HelperConnection);
  private readonly updates = inject(UpdateCheck);

  protected readonly areas = PROMPT_AREAS.map((area) => ({
    area,
    prompts: PROMPTS.filter((p) => p.area === area),
  }));
  protected readonly asking = signal<Record<string, Asking>>(
    Object.fromEntries(PROMPTS.map((p) => [p.key, promptAsks(p) ? 'ask' : 'skip'])),
  );

  protected readonly config = signal<ServerConfig | null>(this.jobs.config());
  protected readonly helperAnswered = signal(true);
  protected readonly formats = signal<string[]>([]);

  protected readonly local = this.helper.isLocal();
  protected readonly ini = signal<IniFile | null>(null);

  readonly toast = signal<Toast | null>(null);
  private toastTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    void this.load();
  }

  ngOnDestroy(): void {
    clearTimeout(this.toastTimer);
  }

  private async load(): Promise<void> {
    const config = this.config() ?? (await this.jobs.loadConfig());
    this.config.set(config);
    this.helperAnswered.set(!!config);
    if (config) this.formats.set(startingFiletypes(config));
    if (this.local) await this.loadIni();
  }

  private async loadIni(): Promise<void> {
    try {
      const response = await this.helper.call('/api/settings-file');
      if (!response.ok) throw new Error(String(response.status));
      this.ini.set((await response.json()) as IniFile);
    } catch {
      // an older helper has no such endpoint, and a stopped one does not answer: either
      // way there is nothing here to edit
      this.ini.set(null);
    }
  }

  private say(text: string, kind: Toast['kind'] = 'saved'): void {
    clearTimeout(this.toastTimer);
    this.toast.set({ text, kind });
    this.toastTimer = setTimeout(() => this.toast.set(null), kind === 'saved' ? TOAST_MS : PROBLEM_TOAST_MS);
  }

  protected choose(prompt: Prompt, value: string): void {
    const asks = value !== 'skip';
    this.asking.update((all) => ({ ...all, [prompt.key]: asks ? 'ask' : 'skip' }));
    setPromptAsks(prompt, asks);
    // the banner reads its flag once, when the page opens - tell it now
    if (prompt.key === UPDATE_BANNER_KEY) this.updates.dismissed.set(!asks);
    this.say(`Saved: "${prompt.name}" - ${asks ? 'ask always' : 'do not ask again'}`);
  }

  protected isForced(filetype: string): boolean {
    return this.config()?.forced.includes(filetype) ?? false;
  }

  protected toggleFormat(filetype: string, on: boolean): void {
    const config = this.config();
    if (!config || this.isForced(filetype)) return;
    this.formats.update((all) => (on ? [...all.filter((x) => x !== filetype), filetype] : all.filter((x) => x !== filetype)));
    // in the order the helper offers them, so the stored list reads the same way every time
    saveDefaultFiletypes(config.filetypes.filter((x) => this.formats().includes(x)));
    this.say(`Saved: runs start with ${this.formatList()}`);
  }

  protected resetFormats(): void {
    const config = this.config();
    if (!config) return;
    saveDefaultFiletypes(null);
    this.formats.set(startingFiletypes(config));
    this.say(`Saved: back to the app's defaults - ${this.formatList()}`);
  }

  private formatList(): string {
    const config = this.config();
    return (config?.filetypes ?? []).filter((x) => this.formats().includes(x)).join(', ');
  }

  /** one setting changed and left: write it now. A refused value is put back as the file has it */
  protected async editIni(setting: IniSetting, value: string, input?: HTMLInputElement | HTMLSelectElement): Promise<void> {
    if (value === setting.value) return;
    try {
      const response = await this.helper.call('/api/settings-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: { [setting.key]: value } }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || `the helper answered ${response.status}`);
      this.ini.set(body as IniFile);
      this.say(`Saved to settings.ini: ${setting.key}=${value.trim()} - from the next run`);
      // the run window reads these through the config, so it sees the new value at once
      void this.jobs.loadConfig();
    } catch (e) {
      if (input) input.value = setting.value;
      this.say(`Not saved: ${e instanceof Error ? e.message : String(e)}`, 'problem');
    }
  }
}
