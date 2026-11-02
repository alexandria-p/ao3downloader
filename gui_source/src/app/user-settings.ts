import { Component, computed, inject, signal } from '@angular/core';
import { HelperConnection } from './helper-connection';
import { Jobs, ServerConfig } from './jobs';
import {
  PROMPTS,
  PROMPT_AREAS,
  Prompt,
  promptAsks,
  saveDefaultFiletypes,
  savedDefaultFiletypes,
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

/**
 * The User settings tab: what this browser remembers, and - on a helper on this computer -
 * the helper's settings.ini.
 *
 * Nothing is written until Save. Every prompt with a "don't ask again" box is listed, from
 * `PROMPTS`, whether or not this browser has met it yet, so a prompt can be turned off before
 * it is ever shown and turned back on after. settings.ini is offered only where the page's
 * helper is on this computer and says it may be edited (`editable`): a hosted copy's file is
 * written by its deployment, and an edit there would be lost on the next restart.
 */
@Component({
  selector: 'app-user-settings',
  templateUrl: './user-settings.html',
  styleUrl: './user-settings.css',
})
export class UserSettings {
  private readonly jobs = inject(Jobs);
  private readonly helper = inject(HelperConnection);
  private readonly updates = inject(UpdateCheck);

  protected readonly areas = PROMPT_AREAS.map((area) => ({
    area,
    prompts: PROMPTS.filter((p) => p.area === area),
  }));
  protected readonly asking = signal<Record<string, Asking>>(this.storedAsking());

  protected readonly config = signal<ServerConfig | null>(this.jobs.config());
  protected readonly helperAnswered = signal(true);
  protected readonly formats = signal<string[]>([]);
  /** the helper's own defaults are back in force - nothing of this browser's is kept */
  protected readonly formatsReset = signal(false);

  protected readonly local = this.helper.isLocal();
  protected readonly ini = signal<IniFile | null>(null);
  /** settings.ini values as edited, by key - written only once Save is pressed */
  protected readonly iniValues = signal<Record<string, string>>({});
  protected readonly iniProblem = signal('');

  protected readonly saving = signal(false);
  protected readonly saved = signal(false);
  protected readonly problem = signal('');

  protected readonly iniChanges = computed(() => {
    const file = this.ini();
    if (!file) return {};
    const edited = this.iniValues();
    const changes: Record<string, string> = {};
    for (const setting of file.settings) {
      const value = edited[setting.key];
      if (value !== undefined && value !== setting.value) changes[setting.key] = value;
    }
    return changes;
  });

  constructor() {
    void this.load();
  }

  private storedAsking(): Record<string, Asking> {
    return Object.fromEntries(PROMPTS.map((p) => [p.key, promptAsks(p) ? 'ask' : 'skip']));
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
      this.showIni((await response.json()) as IniFile);
    } catch {
      // an older helper has no such endpoint, and a stopped one does not answer: either
      // way there is nothing here to edit
      this.ini.set(null);
    }
  }

  private showIni(file: IniFile): void {
    this.ini.set(file);
    this.iniValues.set(Object.fromEntries(file.settings.map((s) => [s.key, s.value])));
  }

  protected choose(prompt: Prompt, value: string): void {
    this.asking.update((all) => ({ ...all, [prompt.key]: value === 'skip' ? 'skip' : 'ask' }));
    this.saved.set(false);
  }

  protected isForced(filetype: string): boolean {
    return this.config()?.forced.includes(filetype) ?? false;
  }

  protected toggleFormat(filetype: string, on: boolean): void {
    if (this.isForced(filetype)) return;
    this.formats.update((all) => (on ? [...all.filter((x) => x !== filetype), filetype] : all.filter((x) => x !== filetype)));
    this.formatsReset.set(false);
    this.saved.set(false);
  }

  protected resetFormats(): void {
    const config = this.config();
    if (!config) return;
    this.formats.set([...new Set([...config.forced, ...(config.defaults ?? [])])]);
    this.formatsReset.set(true);
    this.saved.set(false);
  }

  protected editIni(key: string, value: string): void {
    this.iniValues.update((all) => ({ ...all, [key]: value }));
    this.saved.set(false);
  }

  async save(): Promise<void> {
    this.saving.set(true);
    this.saved.set(false);
    this.problem.set('');
    this.iniProblem.set('');
    try {
      for (const prompt of PROMPTS) setPromptAsks(prompt, this.asking()[prompt.key] !== 'skip');
      // the banner reads its flag once, when the page opens - tell it now
      this.updates.dismissed.set(this.asking()[PROMPTS.find((p) => p.area === 'Updates')!.key] === 'skip');

      const config = this.config();
      if (config) {
        if (this.formatsReset()) saveDefaultFiletypes(null);
        else if (savedDefaultFiletypes() !== null || !sameSet(this.formats(), startingFiletypes(config))) {
          // the order the helper offers them in, so the file reads the same way every time
          saveDefaultFiletypes(config.filetypes.filter((x) => this.formats().includes(x)));
        }
      }

      const changes = this.iniChanges();
      if (Object.keys(changes).length) {
        const response = await this.helper.call('/api/settings-file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ values: changes }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          this.iniProblem.set(body.error || `the helper answered ${response.status}`);
          return;
        }
        this.showIni(body as IniFile);
        // the run window reads these through the config, so it sees the new values at once
        await this.jobs.loadConfig();
      }
      this.saved.set(true);
    } catch (e) {
      this.problem.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.saving.set(false);
    }
  }
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}
