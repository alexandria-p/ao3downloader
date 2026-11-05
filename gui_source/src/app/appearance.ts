/**
 * How the page looks: a colour palette and a font, chosen in User settings and kept by this
 * browser alone, like every other per-browser convenience (`storage.ts`). Losing them only
 * means the page looks as it came.
 *
 * A palette is dark or light (`mode`). It sets the neutral and accent tokens `styles.css`
 * defines on `:root`, and its mode brings the status colours with it - failures red, copies to
 * check amber, rescued and done green, notes violet - as `STATUS_DARK` or `STATUS_LIGHT`, tuned
 * to be read on that kind of page. The components read those tokens and nothing else for those
 * colours, so a new component that hard-codes a grey, a status tint or the accent will not
 * follow the palette. AO3's own rating and warning tiles keep AO3's colours on purpose.
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

export type PaletteMode = 'dark' | 'light';

export interface Palette {
  id: string;
  name: string;
  mode: PaletteMode;
  tokens: PaletteTokens;
}

/** the status tokens, by mode - the dark set is also what `styles.css` starts with */
export type StatusTokens = Record<
  | 'danger' | 'danger-text' | 'danger-border' | 'danger-bg' | 'danger-bg-hover'
  | 'warn-text' | 'warn-text-dim' | 'warn-border' | 'warn-bg' | 'warn-bg-strong'
  | 'ok-text' | 'ok-border' | 'ok-bg' | 'ok-fill'
  | 'note-text' | 'note-border' | 'backdrop',
  string
>;

export const STATUS_DARK: StatusTokens = {
  danger: '#d97b7b', 'danger-text': '#d08b8b', 'danger-border': '#6b3a3a', 'danger-bg': '#2e2020',
  'danger-bg-hover': '#4c2f2f',
  'warn-text': '#e0c97a', 'warn-text-dim': '#a8995c', 'warn-border': '#8a6d2f', 'warn-bg': '#2d2616',
  'warn-bg-strong': '#4a3f12',
  'ok-text': '#8fc58a', 'ok-border': '#4f7a58', 'ok-bg': '#1f2a21', 'ok-fill': '#5a8f6a',
  'note-text': '#c9b8ea', 'note-border': '#6b5a8a',
  backdrop: 'rgba(0, 0, 0, 0.6)',
};

export const STATUS_LIGHT: StatusTokens = {
  danger: '#b3261e', 'danger-text': '#a8322b', 'danger-border': '#e3a0a0', 'danger-bg': '#fdecec',
  'danger-bg-hover': '#f9d6d6',
  'warn-text': '#865800', 'warn-text-dim': '#a07e3a', 'warn-border': '#e2c27a', 'warn-bg': '#fdf5e1',
  'warn-bg-strong': '#f8e6a8',
  'ok-text': '#2e7d32', 'ok-border': '#9fd0a3', 'ok-bg': '#eaf6eb', 'ok-fill': '#5aa36a',
  'note-text': '#6a4fb3', 'note-border': '#b9a6e3',
  backdrop: 'rgba(40, 30, 40, 0.35)',
};

export const DEFAULT_PALETTE = 'charcoal';

function dark(id: string, name: string, tokens: PaletteTokens): Palette {
  return { id, name, mode: 'dark', tokens };
}

function light(id: string, name: string, tokens: PaletteTokens): Palette {
  return { id, name, mode: 'light', tokens };
}

export const PALETTES: Palette[] = [
  dark('charcoal', 'Charcoal', {
    bg: '#1e1e1e', surface: '#262626', 'surface-2': '#2d2d2d', 'surface-hover': '#3a3a3a',
    border: '#3d3d3d', 'border-strong': '#4d4d4d',
    text: '#d6d6d6', 'text-strong': '#f0f0f0', 'text-dim': '#9a9a9a', link: '#e8e8e8',
    accent: '#7fb3d5', 'accent-line': '#5a7f9a', 'accent-fill': '#33566b',
    'accent-fill-hover': '#3d6580', 'accent-bg': '#22303a', 'accent-text': '#9fc4dc',
  }),
  dark('fairy', 'Fairy dust', {
    bg: '#1d1724', surface: '#251d2e', 'surface-2': '#2c2336', 'surface-hover': '#382c44',
    border: '#3d3149', 'border-strong': '#4e3f5d',
    text: '#ddd4e6', 'text-strong': '#f6effb', 'text-dim': '#a193b0', link: '#efe4f7',
    accent: '#e3a3d6', 'accent-line': '#a8749e', 'accent-fill': '#66406a',
    'accent-fill-hover': '#784c7c', 'accent-bg': '#2f2238', 'accent-text': '#ecbde2',
  }),
  dark('midnight', 'Midnight', {
    bg: '#141a24', surface: '#1b2330', 'surface-2': '#212b3a', 'surface-hover': '#2b3749',
    border: '#2f3b4e', 'border-strong': '#3e4d64',
    text: '#d3dae6', 'text-strong': '#f0f4fa', 'text-dim': '#8f9bb0', link: '#e6ecf5',
    accent: '#8ab4f8', 'accent-line': '#5b7fb8', 'accent-fill': '#2f4d7a',
    'accent-fill-hover': '#3a5d91', 'accent-bg': '#1c2a40', 'accent-text': '#a9c7f5',
  }),
  dark('forest', 'Forest', {
    bg: '#18201b', surface: '#1f2922', 'surface-2': '#253128', 'surface-hover': '#2f3d33',
    border: '#34433a', 'border-strong': '#435549',
    text: '#d4ddd5', 'text-strong': '#eef5ef', 'text-dim': '#91a196', link: '#e4ede5',
    accent: '#8cc79f', 'accent-line': '#5f9470', 'accent-fill': '#2f5a3d',
    'accent-fill-hover': '#3a6b4a', 'accent-bg': '#1f3326', 'accent-text': '#a9d9b7',
  }),
  dark('ember', 'Ember', {
    bg: '#221a19', surface: '#2b2120', 'surface-2': '#322725', 'surface-hover': '#3e302d',
    border: '#463734', 'border-strong': '#584541',
    text: '#e3d6d2', 'text-strong': '#faf0ec', 'text-dim': '#a8958f', link: '#f3e5e0',
    accent: '#e8a98a', 'accent-line': '#a8735c', 'accent-fill': '#6b4130',
    'accent-fill-hover': '#7d4d39', 'accent-bg': '#352520', 'accent-text': '#f0c2a8',
  }),
  dark('deep-sea', 'Deep sea', {
    bg: '#0f1d22', surface: '#14262c', 'surface-2': '#192e35', 'surface-hover': '#213b43',
    border: '#24414a', 'border-strong': '#30535e',
    text: '#cfe3e6', 'text-strong': '#ecfafb', 'text-dim': '#86a5ab', link: '#def1f3',
    accent: '#4fd1c5', 'accent-line': '#2f8f88', 'accent-fill': '#1d5d5a',
    'accent-fill-hover': '#246f6b', 'accent-bg': '#123a3a', 'accent-text': '#7fe3da',
  }),
  dark('mocha', 'Mocha', {
    bg: '#1f1a17', surface: '#28211d', 'surface-2': '#2f2722', 'surface-hover': '#3b312a',
    border: '#43372f', 'border-strong': '#57483d',
    text: '#e4d8cc', 'text-strong': '#fbf1e6', 'text-dim': '#a8968a', link: '#f2e6d9',
    accent: '#d9a066', 'accent-line': '#9c7148', 'accent-fill': '#5e4128',
    'accent-fill-hover': '#704e31', 'accent-bg': '#33271d', 'accent-text': '#ebc08f',
  }),
  dark('synthwave', 'Synthwave', {
    bg: '#1a1033', surface: '#22163f', 'surface-2': '#2a1b4b', 'surface-hover': '#36245e',
    border: '#3d2a69', 'border-strong': '#523888',
    text: '#e0d7ff', 'text-strong': '#ffffff', 'text-dim': '#9d8cc9', link: '#7ee8fa',
    accent: '#ff5fb7', 'accent-line': '#c2408c', 'accent-fill': '#7a2766',
    'accent-fill-hover': '#93307b', 'accent-bg': '#331a4a', 'accent-text': '#ff9ad2',
  }),
  dark('nightshade', 'Nightshade', {
    bg: '#16131c', surface: '#1d1925', 'surface-2': '#241f2e', 'surface-hover': '#2f2840',
    border: '#352d45', 'border-strong': '#463b5c',
    text: '#d9d2e3', 'text-strong': '#f4effa', 'text-dim': '#968ca6', link: '#ebe3f5',
    accent: '#b48ef7', 'accent-line': '#7d62b0', 'accent-fill': '#4a3878',
    'accent-fill-hover': '#57438c', 'accent-bg': '#271f3a', 'accent-text': '#cbb2fa',
  }),
  dark('ink-gold', 'Ink and gold', {
    bg: '#0d0d0d', surface: '#151515', 'surface-2': '#1b1b1b', 'surface-hover': '#262626',
    border: '#2c2c2c', 'border-strong': '#3c3c3c',
    text: '#e6e1d3', 'text-strong': '#fffaf0', 'text-dim': '#9e988a', link: '#f5ecd6',
    accent: '#e6c15a', 'accent-line': '#a88a3a', 'accent-fill': '#5c4a1c',
    'accent-fill-hover': '#6e5922', 'accent-bg': '#262011', 'accent-text': '#f0d68a',
  }),
  dark('high-contrast', 'High contrast', {
    bg: '#000000', surface: '#0a0a0a', 'surface-2': '#141414', 'surface-hover': '#262626',
    border: '#8a8a8a', 'border-strong': '#cfcfcf',
    text: '#ffffff', 'text-strong': '#ffffff', 'text-dim': '#d0d0d0', link: '#ffff66',
    accent: '#ffff66', 'accent-line': '#ffff66', 'accent-fill': '#1f3f99',
    'accent-fill-hover': '#2a52bf', 'accent-bg': '#10204d', 'accent-text': '#ffff66',
  }),
  light('strawberry-milk', 'Strawberry milk', {
    bg: '#fff0f4', surface: '#ffe5ed', 'surface-2': '#ffd9e4', 'surface-hover': '#ffcadb',
    border: '#f6bccd', 'border-strong': '#ec9bb4',
    text: '#6b3f4c', 'text-strong': '#4a2531', 'text-dim': '#9c6b7a', link: '#b0406a',
    accent: '#d9487a', 'accent-line': '#e889a8', 'accent-fill': '#f9b4c9',
    'accent-fill-hover': '#f59ab6', 'accent-bg': '#ffdbe6', 'accent-text': '#a8325c',
  }),
  light('paper', 'Paper', {
    bg: '#faf8f4', surface: '#f2efe9', 'surface-2': '#ebe7df', 'surface-hover': '#e2ddd3',
    border: '#d8d2c6', 'border-strong': '#bdb5a6',
    text: '#3a3631', 'text-strong': '#1d1a17', 'text-dim': '#757066', link: '#2f5d8a',
    accent: '#2f6fa8', 'accent-line': '#8fb3d6', 'accent-fill': '#cfe0f0',
    'accent-fill-hover': '#bcd3ea', 'accent-bg': '#e3edf7', 'accent-text': '#245887',
  }),
  light('old-book', 'Old book', {
    bg: '#f4ecd8', surface: '#ece2ca', 'surface-2': '#e4d8bc', 'surface-hover': '#dacdae',
    border: '#cdbf9c', 'border-strong': '#b3a37e',
    text: '#4a3b28', 'text-strong': '#2e2416', 'text-dim': '#7d6c52', link: '#7a3e1d',
    accent: '#9a4f22', 'accent-line': '#c79a73', 'accent-fill': '#e5c8a8',
    'accent-fill-hover': '#dcb791', 'accent-bg': '#eedcc4', 'accent-text': '#7f3f19',
  }),
  light('mint', 'Mint', {
    bg: '#effaf5', surface: '#e2f4ec', 'surface-2': '#d5eee3', 'surface-hover': '#c5e6d7',
    border: '#b2dcc9', 'border-strong': '#8ec8ae',
    text: '#2f4a40', 'text-strong': '#1a3028', 'text-dim': '#5f7d71', link: '#1f7a5c',
    accent: '#16936b', 'accent-line': '#7cc8aa', 'accent-fill': '#b6e6d2',
    'accent-fill-hover': '#9edcc2', 'accent-bg': '#d3f0e3', 'accent-text': '#127556',
  }),
  light('lavender', 'Lavender', {
    bg: '#f6f2fd', surface: '#ede6fa', 'surface-2': '#e4dbf6', 'surface-hover': '#d8cdf0',
    border: '#cbbde9', 'border-strong': '#ad9ad9',
    text: '#43395a', 'text-strong': '#2a2240', 'text-dim': '#75698f', link: '#6a3fb5',
    accent: '#7b4fd0', 'accent-line': '#b39ae6', 'accent-fill': '#d9cbf6',
    'accent-fill-hover': '#cab7f2', 'accent-bg': '#e8dffa', 'accent-text': '#5d36a8',
  }),
  light('sky', 'Sky', {
    bg: '#f0f7fd', surface: '#e3f0fb', 'surface-2': '#d6e8f8', 'surface-hover': '#c6dff4',
    border: '#b3d3ee', 'border-strong': '#8bbbe2',
    text: '#2d4256', 'text-strong': '#172a3b', 'text-dim': '#5d7489', link: '#1d6bb0',
    accent: '#1f7fd1', 'accent-line': '#86bce8', 'accent-fill': '#c2def5',
    'accent-fill-hover': '#a9d0f0', 'accent-bg': '#dbebf9', 'accent-text': '#1662a6',
  }),
  light('peach', 'Peach', {
    bg: '#fff5ee', surface: '#ffeadd', 'surface-2': '#fde0cd', 'surface-hover': '#fbd2b8',
    border: '#f4c3a3', 'border-strong': '#e9a37a',
    text: '#5c3c2b', 'text-strong': '#3d2418', 'text-dim': '#8f6a56', link: '#b4502a',
    accent: '#e0703f', 'accent-line': '#f0a67f', 'accent-fill': '#fcc9a9',
    'accent-fill-hover': '#fab890', 'accent-bg': '#ffe2cf', 'accent-text': '#a8461f',
  }),
];

export interface FontChoice {
  id: string;
  name: string;
  /** what the font picker groups it under */
  group: string;
  /** the css font-family; empty for `custom`, which is built from the name typed */
  stack: string;
}

export const DEFAULT_FONT = 'default';
export const CUSTOM_FONT = 'custom';
const DEFAULT_STACK = "'Segoe UI', Tahoma, Verdana, system-ui, sans-serif";

/** a font bundled with the page (`fonts.css`), falling back to the default if it will not load */
function bundled(id: string, name: string, family: string, group: string, fallback = DEFAULT_STACK): FontChoice {
  return { id, name, group, stack: `'${family}', ${fallback}` };
}

const SERIF = "Georgia, Cambria, 'Times New Roman', serif";
const MONO = "ui-monospace, Consolas, Menlo, 'Courier New', monospace";

/**
 * Fonts a computer already has, and fonts bundled with the page itself (`fonts.css`, from
 * @fontsource, under the SIL Open Font License). Nothing is fetched from a font service: a
 * bundled font comes from the page's own address, only once it is chosen, and works offline.
 */
export const FONTS: FontChoice[] = [
  { id: DEFAULT_FONT, name: 'Default', group: 'On this computer', stack: DEFAULT_STACK },
  { id: 'system', name: 'System', group: 'On this computer', stack: "system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, sans-serif" },
  { id: 'serif', name: 'Book (serif)', group: 'On this computer', stack: SERIF },
  { id: 'mono', name: 'Typewriter (monospace)', group: 'On this computer', stack: MONO },
  bundled('fredoka', 'Fredoka', 'Fredoka', 'Cute and rounded'),
  bundled('rounded', 'Nunito', 'Nunito', 'Cute and rounded'),
  bundled('quicksand', 'Quicksand', 'Quicksand', 'Cute and rounded'),
  bundled('comfortaa', 'Comfortaa', 'Comfortaa', 'Cute and rounded'),
  bundled('baloo', 'Baloo', 'Baloo 2', 'Cute and rounded'),
  bundled('sniglet', 'Sniglet', 'Sniglet', 'Cute and rounded'),
  bundled('mali', 'Mali', 'Mali', 'Handwritten'),
  bundled('itim', 'Itim', 'Itim', 'Handwritten'),
  bundled('patrick-hand', 'Patrick Hand', 'Patrick Hand', 'Handwritten'),
  bundled('gaegu', 'Gaegu', 'Gaegu', 'Handwritten'),
  bundled('short-stack', 'Short Stack', 'Short Stack', 'Handwritten'),
  bundled('legible', 'Atkinson Hyperlegible', 'Atkinson Hyperlegible', 'Easy to read'),
  bundled('lexend', 'Lexend', 'Lexend', 'Easy to read'),
  bundled('opendyslexic', 'OpenDyslexic', 'OpenDyslexic', 'Easy to read'),
  bundled('inter', 'Inter', 'Inter', 'Clean'),
  bundled('poppins', 'Poppins', 'Poppins', 'Clean'),
  bundled('lora', 'Lora', 'Lora', 'Bookish', SERIF),
  bundled('merriweather', 'Merriweather', 'Merriweather', 'Bookish', SERIF),
  bundled('literata', 'Literata', 'Literata', 'Bookish', SERIF),
  bundled('garamond', 'EB Garamond', 'EB Garamond', 'Bookish', SERIF),
  bundled('jetbrains-mono', 'JetBrains Mono', 'JetBrains Mono', 'Typewriter', MONO),
  bundled('courier-prime', 'Courier Prime', 'Courier Prime', 'Typewriter', MONO),
  { id: CUSTOM_FONT, name: 'Another font...', group: 'Your own', stack: '' },
];

/** the font picker's groups, in the order they are first met in FONTS */
export const FONT_GROUPS: { name: string; fonts: FontChoice[] }[] = FONTS.reduce(
  (groups, font) => {
    const group = groups.find((g) => g.name === font.group);
    if (group) group.fonts.push(font);
    else groups.push({ name: font.group, fonts: [font] });
    return groups;
  },
  [] as { name: string; fonts: FontChoice[] }[],
);

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

/** the logo's own pink, as a hue in degrees - measured off `public/ficfairy-logo.png` */
export const LOGO_HUE = 316;
/** how near a palette's accent must be to the logo's pink for the artwork to be left as drawn */
const LOGO_KEEP_WITHIN = 30;

/** a `#rrggbb` colour's hue (0-360) and saturation (0-1), or null for anything else */
export function hueOf(hex: string): { hue: number; saturation: number } | null {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!match) return null;
  const [r, g, b] = match.slice(1).map((part) => parseInt(part, 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const chroma = max - min;
  if (!chroma) return { hue: 0, saturation: 0 };
  const light = (max + min) / 2;
  const saturation = chroma / (1 - Math.abs(2 * light - 1));
  const hue = max === r ? ((g - b) / chroma) % 6 : max === g ? (b - r) / chroma + 2 : (r - g) / chroma + 4;
  return { hue: (hue * 60 + 360) % 360, saturation };
}

/**
 * The css filter that tints the logo to a palette's accent: the logo is drawn in one pink, so
 * turning its hue to the accent's keeps every line and shade while changing the colour. A
 * palette whose accent is already near that pink keeps the artwork as drawn, and one with a
 * grey accent gets a grey logo.
 */
export function logoFilter(accent: string): string {
  const colour = hueOf(accent);
  if (!colour) return 'none';
  if (colour.saturation < 0.1) return 'grayscale(1)';
  const turn = Math.round(((colour.hue - LOGO_HUE + 540) % 360) - 180);
  return Math.abs(turn) <= LOGO_KEEP_WITHIN ? 'none' : `hue-rotate(${turn}deg)`;
}

/** sets the tokens, the status colours for the palette's mode, and the font on the page's root */
export function applyAppearance(palette: string, font: string, custom: string, root: HTMLElement = document.documentElement): void {
  const chosen = paletteById(palette);
  const status = chosen.mode === 'light' ? STATUS_LIGHT : STATUS_DARK;
  for (const [token, value] of Object.entries({ ...status, ...chosen.tokens })) root.style.setProperty(`--${token}`, value);
  root.style.setProperty('--font-body', fontStack(font, custom));
  root.style.setProperty('--logo-filter', logoFilter(chosen.tokens.accent));
  // form controls, scrollbars and date pickers follow the palette's mode
  root.style.colorScheme = chosen.mode;
  root.dataset['palette'] = chosen.id;
  root.dataset['mode'] = chosen.mode;
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
