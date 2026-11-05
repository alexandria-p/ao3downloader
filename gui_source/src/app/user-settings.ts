import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { HelperConnection } from './helper-connection';
import { Jobs, QuestionName, ServerConfig } from './jobs';
import {
  BUILT_IN_ANSWERS,
  BUILT_IN_QUESTION_TIMEOUT,
  QUESTION_DEFAULTS,
  QuestionDefault,
  PROMPTS,
  promptLabels,
  PROMPT_AREAS,
  Prompt,
  UPDATE_BANNER_KEY,
  promptAsks,
  ao3TimeZone,
  browserTimeZone,
  knownTimeZones,
  saveAo3TimeZone,
  saveAnswerDefaults,
  saveDefaultFiletypes,
  saveQuestionTimeout,
  savedAnswerDefaults,
  savedQuestionTimeout,
  setPromptAsks,
  startingFiletypes,
} from './preferences';
import { UpdateCheck } from './updates';
import { LibraryImports } from './imports';
import { Library } from './library';
import { StorageChoice } from './storage-choice';
import { DebugMode } from './debug';
import { Appearance, CUSTOM_FONT, DEFAULT_FONT, DEFAULT_PALETTE, FONTS, FONT_GROUPS, PALETTES, fontById, fontStack, paletteById } from './appearance';

export type Asking = 'ask' | 'skip';

/** one setting in the helper's settings.ini, as `GET /api/settings-file` describes it */
export interface IniSetting {
  key: string;
  value: string;
  default: string;
  kind: 'boolean' | 'integer' | 'text' | 'choice';
  /** a 'choice' setting's answers */
  choices?: string[];
  about: string;
}

interface IniFile {
  editable: boolean;
  file?: string;
  settings: IniSetting[];
}

/** one value Reset to defaults would change, as its window lists it */
export interface ResetChange {
  group: 'Appearance' | 'Prompts' | 'Download formats' | 'AO3 time zone' | 'Questions' | 'settings.ini';
  name: string;
  current: string;
  default: string;
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
  host: { '(document:keydown.escape)': 'escape()' },
})
export class UserSettings implements OnDestroy {
  private readonly jobs = inject(Jobs);
  private readonly helper = inject(HelperConnection);
  private readonly updates = inject(UpdateCheck);
  private readonly imports = inject(LibraryImports);
  private readonly library = inject(Library);
  protected readonly debugMode = inject(DebugMode);
  /**
   * Where the exclusion lists are kept: in the library itself, so they follow it - in Dropbox,
   * or in the folder on this computer - whichever this page has open
   */
  private readonly storage = inject(StorageChoice);
  protected readonly libraryPlace = computed(() =>
    this.storage.mode() === 'dropbox' ? 'your Dropbox library' : 'your library folder',
  );

  protected readonly appearance = inject(Appearance);
  protected readonly palettes = PALETTES;
  protected readonly fonts = FONTS;
  protected readonly fontGroups = FONT_GROUPS;
  /** the palettes, dark ones first, each kind under its own heading */
  protected readonly paletteGroups = [
    { mode: 'dark', name: 'Dark', palettes: PALETTES.filter((p) => p.mode === 'dark') },
    { mode: 'light', name: 'Light', palettes: PALETTES.filter((p) => p.mode === 'light') },
  ];
  protected readonly customFontId = CUSTOM_FONT;
  /** what a font choice looks like, for its preview line */
  protected readonly fontPreview = computed(() => fontStack(this.appearance.font(), this.appearance.customFont()));

  protected setPalette(id: string): void {
    this.appearance.setPalette(id);
    this.say(`Saved: the ${paletteById(id).name} palette`);
  }

  protected setFont(id: string): void {
    this.appearance.setFont(id);
    if (id === CUSTOM_FONT && !this.appearance.customFont()) {
      this.say('Type the name of a font on this computer to use it');
      return;
    }
    this.say(`Saved: the font is ${this.fontName()}`);
  }

  /** sent on change, like a settings.ini box, so the page does not jump about mid-word */
  protected setCustomFont(name: string): void {
    this.appearance.setFont(CUSTOM_FONT, name);
    this.say(this.appearance.customFont()
      ? `Saved: the font is ${this.appearance.customFont()} - if this computer does not have it, the default is used`
      : 'Saved: no font named - the default is used');
  }

  private fontName(): string {
    const font = this.appearance.font();
    return font === CUSTOM_FONT ? this.appearance.customFont() || 'the default' : fontById(font).name;
  }

  protected setDebugMode(on: boolean): void {
    this.debugMode.set(on);
    this.say(on ? 'Saved: debug mode is on - the DEBUG tab is beside User settings' : 'Saved: debug mode is off');
  }

  /** a library open that can be written to: the exclusion lists live in it */
  protected readonly canResetExclusions = computed(() => !!this.library.store());
  protected readonly resettingExclusions = signal(false);

  /** empties every exclusion list for imports in the library open now */
  protected async resetExclusions(): Promise<void> {
    if (this.resettingExclusions()) return;
    this.resettingExclusions.set(true);
    try {
      await this.imports.resetExclusions();
      this.say('Reset: every exclusion list for imports is empty - everything found is offered again');
    } catch (e) {
      this.say(`Not reset: ${e instanceof Error ? e.message : String(e)}`, 'problem');
    } finally {
      this.resettingExclusions.set(false);
    }
  }

  protected readonly labelsOf = promptLabels;
  protected readonly areas = PROMPT_AREAS.map((area) => ({
    area,
    prompts: PROMPTS.filter((p) => p.area === area && p.listed !== false),
  }));
  protected readonly asking = signal<Record<string, Asking>>(
    Object.fromEntries(PROMPTS.map((p) => [p.key, promptAsks(p) ? 'ask' : 'skip'])),
  );

  protected readonly config = signal<ServerConfig | null>(this.jobs.config());
  protected readonly helperAnswered = signal(true);
  protected readonly formats = signal<string[]>([]);

  protected readonly local = this.helper.isLocal();
  protected readonly ini = signal<IniFile | null>(null);

  /**
   * A hosted copy's question defaults, kept by this browser (its settings.ini cannot be
   * edited from here): what is saved, and what the helper's own deployment says when not.
   */
  protected readonly questions = QUESTION_DEFAULTS;
  private readonly savedAnswers = signal(savedAnswerDefaults());
  private readonly savedTimeout = signal(savedQuestionTimeout());
  protected helperAnswer(name: QuestionName): string {
    return this.config()?.settings?.answerDefaults?.[name] ?? BUILT_IN_ANSWERS[name];
  }
  protected answer(name: QuestionName): string {
    return this.savedAnswers()[name] ?? this.helperAnswer(name);
  }
  protected helperTimeout(): number {
    return this.config()?.settings?.questionTimeoutMinutes ?? BUILT_IN_QUESTION_TIMEOUT;
  }
  protected readonly questionTimeout = computed(() => this.savedTimeout() ?? this.helperTimeout());
  protected choiceLabel(question: QuestionDefault, value: string): string {
    return question.choices.find((c) => c.value === value)?.label ?? value;
  }

  /** the zone AO3 shows this person's dates in - this browser's own until changed */
  protected readonly browserZone = browserTimeZone();
  protected readonly zones = knownTimeZones();
  protected readonly ao3Zone = signal(ao3TimeZone());

  protected setAo3Zone(zone: string): void {
    if (!this.zones.includes(zone)) return;
    // this browser's own zone is not kept, so the setting follows the browser if it moves
    saveAo3TimeZone(zone === this.browserZone ? null : zone);
    this.ao3Zone.set(zone);
    this.say(`Saved: AO3 dates are read in ${zone} - from the next run`);
  }

  /** the Reset to defaults window is open */
  protected readonly confirmingReset = signal(false);

  /**
   * Every value Reset would change - only those that differ from their default, so the
   * window shows exactly what pressing it does. Worked out from what is on screen, which
   * is what has been saved: every change here is saved as it is made.
   */
  protected readonly resetChanges = computed<ResetChange[]>(() => {
    const changes: ResetChange[] = [];
    if (this.appearance.palette() !== DEFAULT_PALETTE) {
      changes.push({ group: 'Appearance', name: 'Palette', current: paletteById(this.appearance.palette()).name,
                     default: paletteById(DEFAULT_PALETTE).name });
    }
    if (this.appearance.font() !== DEFAULT_FONT) {
      changes.push({ group: 'Appearance', name: 'Font', current: this.fontName(), default: fontById(DEFAULT_FONT).name });
    }
    const askingNow = this.asking();
    for (const prompt of PROMPTS) {
      if (askingNow[prompt.key] === 'skip') {
        changes.push({ group: 'Prompts', name: prompt.name, current: promptLabels(prompt).skip, default: promptLabels(prompt).ask });
      }
    }
    const config = this.config();
    if (config) {
      const order = (list: string[]) => config.filetypes.filter((x) => list.includes(x)).join(', ');
      const now = order(this.formats());
      const fresh = order([...config.forced, ...(config.defaults ?? [])]);
      if (now !== fresh) changes.push({ group: 'Download formats', name: 'Formats a run starts with', current: now, default: fresh });
    }
    if (this.ao3Zone() !== this.browserZone) {
      changes.push({ group: 'AO3 time zone', name: 'Your AO3 time zone', current: this.ao3Zone(),
                     default: `${this.browserZone} (this browser)` });
    }
    if (!this.local) {
      if (this.questionTimeout() !== this.helperTimeout()) {
        changes.push({ group: 'Questions', name: 'Minutes a question waits for you',
                       current: String(this.questionTimeout()), default: String(this.helperTimeout()) });
      }
      for (const question of QUESTION_DEFAULTS) {
        const now = this.answer(question.name);
        const fresh = this.helperAnswer(question.name);
        if (now !== fresh) {
          changes.push({ group: 'Questions', name: question.label,
                         current: this.choiceLabel(question, now), default: this.choiceLabel(question, fresh) });
        }
      }
    }
    const file = this.ini();
    if (file?.editable) {
      for (const setting of file.settings) {
        if (setting.value !== setting.default) {
          changes.push({ group: 'settings.ini', name: setting.key, current: setting.value || '(empty)', default: setting.default || '(empty)' });
        }
      }
    }
    return changes;
  });

  readonly toast = signal<Toast | null>(null);
  private toastTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    void this.load();
  }

  ngOnDestroy(): void {
    clearTimeout(this.toastTimer);
  }

  /** a toast left from the last change would sit over the window's list, so it goes */
  protected openReset(): void {
    clearTimeout(this.toastTimer);
    this.toast.set(null);
    this.confirmingReset.set(true);
  }

  /** Escape shuts the Reset window without changing anything */
  protected escape(): void {
    this.confirmingReset.set(false);
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
    const labels = promptLabels(prompt);
    this.say(`Saved: "${prompt.name}" - ${(asks ? labels.ask : labels.skip).toLowerCase()}`);
  }

  protected setAnswer(question: QuestionDefault, value: string): void {
    if (!question.choices.some((c) => c.value === value)) return;
    const answers = { ...this.savedAnswers() };
    // the same as the helper's is not kept, so a later change to the deployment still shows
    if (value === this.helperAnswer(question.name)) delete answers[question.name];
    else answers[question.name] = value;
    saveAnswerDefaults(answers);
    this.savedAnswers.set(answers);
    this.say(`Saved: "${question.label}" - ${this.choiceLabel(question, value)} - from the next run`);
  }

  protected setQuestionTimeout(value: string, input?: HTMLInputElement): void {
    const minutes = Number(value);
    if (value.trim() === '' || !Number.isInteger(minutes) || minutes < 0) {
      if (input) input.value = String(this.questionTimeout());
      this.say('Not saved: the wait is a whole number of minutes, 0 or more', 'problem');
      return;
    }
    const kept = minutes === this.helperTimeout() ? null : minutes;
    saveQuestionTimeout(kept);
    this.savedTimeout.set(kept);
    this.say(`Saved: questions wait ${minutes} minute${minutes === 1 ? '' : 's'} - from the next run`);
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

  /**
   * Everything back as it came: every prompt asks always, runs start with the app's own
   * formats, and settings.ini - where it is offered - holds the values this copy was built
   * with (the downloaded app's own; the template's for anything else).
   */
  protected async resetAll(): Promise<void> {
    this.confirmingReset.set(false);
    this.appearance.reset();
    for (const prompt of PROMPTS) setPromptAsks(prompt, true);
    this.asking.set(Object.fromEntries(PROMPTS.map((p) => [p.key, 'ask' as Asking])));
    this.updates.dismissed.set(false);
    saveDefaultFiletypes(null);
    saveAnswerDefaults(null);
    saveQuestionTimeout(null);
    saveAo3TimeZone(null);
    this.ao3Zone.set(this.browserZone);
    this.savedAnswers.set({});
    this.savedTimeout.set(null);
    const config = this.config();
    if (config) this.formats.set(startingFiletypes(config));

    if (!this.ini()?.editable) {
      this.say(this.local
        ? 'Reset: the page looks as it came, every prompt asks always, and runs start with the app\'s default formats'
        : 'Reset: the page looks as it came, every prompt asks always, runs start with the app\'s default formats, and questions take the app\'s default answers');
      return;
    }
    try {
      const response = await this.helper.call('/api/settings-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reset: true }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || `the helper answered ${response.status}`);
      this.ini.set(body as IniFile);
      void this.jobs.loadConfig();
      this.say('Reset: the page looks as it came, every prompt asks always, runs start with the app\'s default formats, and settings.ini holds its defaults');
    } catch (e) {
      this.say(
        `Prompts and formats were reset, but settings.ini was not: ${e instanceof Error ? e.message : String(e)}`,
        'problem',
      );
    }
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
