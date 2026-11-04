/**
 * How the page looks: a colour palette and a font, chosen in User settings and kept by this
 * browser alone, like every other per-browser convenience (`storage.ts`). Losing them only
 * means the page looks as it came.
 *
 * Every palette is dark on purpose. The status colours - failures red, copies to check
 * amber, rescued green - are fixed tints tuned for a dark page and are not part of a palette,
 * so a light one would leave them unreadable. A palette sets only the neutral and accent
 * tokens `styles.css` defines on `:root`; the components read those tokens and nothing else
 * for those colours, so a new component that hard-codes a grey or the accent blue will not
 * follow the palette.
 */

import { Injectable, signal } from '@angular/core';
import { safeGet, safeRemove, safeSet } from './storage';

export const PALETTE_KEY = 'ao3.palette';
export const FONT_KEY = 'ao3.font';
export const CUSTOM_FONT_KEY = 'ao3.customFont';

/** the tokens a palette sets, by css custom property name without its `--` */
export type PaletteTokens = Record<
  | 'bg' | 'surface' | 'surface-2' | 'surface-hover' | 'border' | 'border-strong'
  | 'text' | 'text-strong' | 'text-dim' | 'link'
  | 'accent' | 'accent-line' | 'accent-fill' | 'accent-fill-hover' | 'accent-bg' | 'accent-text',
  string
>;

export interface Palette {
  id: string;
  name: string;
  tokens: PaletteTokens;
}

export const DEFAULT_PALETTE = 'charcoal';

export const PALETTES: Palette[] = [
  {
    id: 'charcoal',
    name: 'Charcoal',
    tokens: {
      bg: '#1e1e1e', surface: '#262626', 'surface-2': '#2d2d2d', 'surface-hover': '#3a3a3a',
      border: '#3d3d3d', 'border-strong': '#4d4d4d',
      text: '#d6d6d6', 'text-strong': '#f0f0f0', 'text-dim': '#9a9a9a', link: '#e8e8e8',
      accent: '#7fb3d5', 'accent-line': '#5a7f9a', 'accent-fill': '#33566b',
      'accent-fill-hover': '#3d6580', 'accent-bg': '#22303a', 'accent-text': '#9fc4dc',
    },
  },
  {
    id: 'fairy',
    name: 'Fairy dust',
    tokens: {
      bg: '#1d1724', surface: '#251d2e', 'surface-2': '#2c2336', 'surface-hover': '#382c44',
      border: '#3d3149', 'border-strong': '#4e3f5d',
      text: '#ddd4e6', 'text-strong': '#f6effb', 'text-dim': '#a193b0', link: '#efe4f7',
      accent: '#e3a3d6', 'accent-line': '#a8749e', 'accent-fill': '#66406a',
      'accent-fill-hover': '#784c7c', 'accent-bg': '#2f2238', 'accent-text': '#ecbde2',
    },
  },
  {
    id: 'midnight',
    name: 'Midnight',
    tokens: {
      bg: '#141a24', surface: '#1b2330', 'surface-2': '#212b3a', 'surface-hover': '#2b3749',
      border: '#2f3b4e', 'border-strong': '#3e4d64',
      text: '#d3dae6', 'text-strong': '#f0f4fa', 'text-dim': '#8f9bb0', link: '#e6ecf5',
      accent: '#8ab4f8', 'accent-line': '#5b7fb8', 'accent-fill': '#2f4d7a',
      'accent-fill-hover': '#3a5d91', 'accent-bg': '#1c2a40', 'accent-text': '#a9c7f5',
    },
  },
  {
    id: 'forest',
    name: 'Forest',
    tokens: {
      bg: '#18201b', surface: '#1f2922', 'surface-2': '#253128', 'surface-hover': '#2f3d33',
      border: '#34433a', 'border-strong': '#435549',
      text: '#d4ddd5', 'text-strong': '#eef5ef', 'text-dim': '#91a196', link: '#e4ede5',
      accent: '#8cc79f', 'accent-line': '#5f9470', 'accent-fill': '#2f5a3d',
      'accent-fill-hover': '#3a6b4a', 'accent-bg': '#1f3326', 'accent-text': '#a9d9b7',
    },
  },
  {
    id: 'ember',
    name: 'Ember',
    tokens: {
      bg: '#221a19', surface: '#2b2120', 'surface-2': '#322725', 'surface-hover': '#3e302d',
      border: '#463734', 'border-strong': '#584541',
      text: '#e3d6d2', 'text-strong': '#faf0ec', 'text-dim': '#a8958f', link: '#f3e5e0',
      accent: '#e8a98a', 'accent-line': '#a8735c', 'accent-fill': '#6b4130',
      'accent-fill-hover': '#7d4d39', 'accent-bg': '#352520', 'accent-text': '#f0c2a8',
    },
  },
];

export interface FontChoice {
  id: string;
  name: string;
  /** the css font-family; empty for `custom`, which is built from the name typed */
  stack: string;
}

export const DEFAULT_FONT = 'default';
export const CUSTOM_FONT = 'custom';
const DEFAULT_STACK = "'Segoe UI', Tahoma, Verdana, system-ui, sans-serif";

/**
 * Only fonts a computer already has, or falls back from: nothing is fetched from a font
 * service, so the page looks the same with no connection and asks no third party for anything.
 */
export const FONTS: FontChoice[] = [
  { id: DEFAULT_FONT, name: 'Default', stack: DEFAULT_STACK },
  { id: 'system', name: 'System', stack: "system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, sans-serif" },
  { id: 'serif', name: 'Book (serif)', stack: "Georgia, Cambria, 'Times New Roman', serif" },
  { id: 'rounded', name: 'Rounded', stack: "ui-rounded, 'SF Pro Rounded', 'Arial Rounded MT Bold', 'Nunito', 'Varela Round', " + DEFAULT_STACK },
  { id: 'legible', name: 'Easy to read', stack: "'Atkinson Hyperlegible', Verdana, Tahoma, sans-serif" },
  { id: 'mono', name: 'Typewriter (monospace)', stack: "ui-monospace, 'Cascadia Code', Consolas, Menlo, 'Courier New', monospace" },
  { id: CUSTOM_FONT, name: 'Another font...', stack: '' },
];

/**
 * A font name as typed, safe to put in quotes in a font-family: anything that could close the
 * quote or the declaration is dropped. A name the computer does not have falls back to the
 * default stack after it, which is what a browser does with any missing font.
 */
export function cleanFontName(name: string): string {
  return name.replace(/["'\\;{}<>]/g, '').replace(/\s+/g, ' ').trim().slice(0, 80);
}

export function paletteById(id: string | null): Palette {
  return PALETTES.find((p) => p.id === id) ?? PALETTES[0];
}

export function fontById(id: string | null): FontChoice {
  return FONTS.find((f) => f.id === id) ?? FONTS[0];
}

/** the font-family a choice comes to; a custom one with no name is the default */
export function fontStack(id: string, custom: string): string {
  if (id === CUSTOM_FONT) {
    const name = cleanFontName(custom);
    return name ? `"${name}", ${DEFAULT_STACK}` : DEFAULT_STACK;
  }
  return fontById(id).stack;
}

/** sets the tokens and the font on the page's root element */
export function applyAppearance(palette: string, font: string, custom: string, root: HTMLElement = document.documentElement): void {
  const chosen = paletteById(palette);
  for (const [token, value] of Object.entries(chosen.tokens)) root.style.setProperty(`--${token}`, value);
  root.style.setProperty('--font-body', fontStack(font, custom));
  root.dataset['palette'] = chosen.id;
}

@Injectable({ providedIn: 'root' })
export class Appearance {
  readonly palette = signal(paletteById(safeGet(PALETTE_KEY)).id);
  readonly font = signal(fontById(safeGet(FONT_KEY)).id);
  readonly customFont = signal(safeGet(CUSTOM_FONT_KEY) ?? '');

  constructor() {
    this.apply();
  }

  setPalette(id: string): void {
    const chosen = paletteById(id).id;
    this.palette.set(chosen);
    if (chosen === DEFAULT_PALETTE) safeRemove(PALETTE_KEY);
    else safeSet(PALETTE_KEY, chosen);
    this.apply();
  }

  /** a custom font keeps its name even when another font is chosen, so it can be picked again */
  setFont(id: string, custom?: string): void {
    const chosen = fontById(id).id;
    this.font.set(chosen);
    if (chosen === DEFAULT_FONT) safeRemove(FONT_KEY);
    else safeSet(FONT_KEY, chosen);
    if (custom !== undefined) {
      const name = cleanFontName(custom);
      this.customFont.set(name);
      if (name) safeSet(CUSTOM_FONT_KEY, name);
      else safeRemove(CUSTOM_FONT_KEY);
    }
    this.apply();
  }

  /** what Reset to defaults leaves: the default palette and font, the typed name forgotten */
  reset(): void {
    this.setPalette(DEFAULT_PALETTE);
    this.setFont(DEFAULT_FONT, '');
  }

  private apply(): void {
    if (typeof document === 'undefined') return;
    applyAppearance(this.palette(), this.font(), this.customFont());
  }
}
