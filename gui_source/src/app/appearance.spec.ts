import { describe, expect, it } from 'vitest';
import { CUSTOM_FONT, FONTS, FONT_GROUPS, PALETTES, STATUS_DARK, STATUS_LIGHT, applyAppearance, cleanFontName, fontById, fontStack, logoFilter } from './appearance';

describe('appearance', () => {
  it('gives every palette the same tokens, so none leaves a colour behind from another', () => {
    const tokens = Object.keys(PALETTES[0].tokens).sort();
    for (const palette of PALETTES) expect(Object.keys(palette.tokens).sort()).toEqual(tokens);
  });

  it('starts from the palette styles.css draws the page in', () => {
    expect(PALETTES[0].id).toBe('charcoal');
    expect(PALETTES[0].tokens.bg).toBe('#1e1e1e');
  });

  it('builds a custom font from the name, falling back to the default stack, and the default with no name', () => {
    expect(fontStack(CUSTOM_FONT, 'Comic Sans MS')).toBe(`"Comic Sans MS", ${FONTS[0].stack}`);
    expect(fontStack(CUSTOM_FONT, '  ')).toBe(FONTS[0].stack);
    expect(fontStack('serif', 'ignored')).toContain('Georgia');
    expect(fontStack('no such font', '')).toBe(FONTS[0].stack);
  });

  it('drops anything from a font name that could end the quote or the declaration', () => {
    expect(cleanFontName(`a"b'c;d{e}f\\g<h>`)).toBe('abcdefgh');
  });

  it('sets the tokens and the font on the element it is given, and says which palette', () => {
    const root = document.createElement('div');
    applyAppearance('forest', 'mono', '', root);
    expect(root.style.getPropertyValue('--accent')).toBe(PALETTES.find((p) => p.id === 'forest')!.tokens.accent);
    expect(root.style.getPropertyValue('--font-body')).toContain('monospace');
    expect(root.dataset['palette']).toBe('forest');

    applyAppearance('nonsense', '', '', root);
    expect(root.dataset['palette']).toBe('charcoal');
  });
  it('offers dark and light palettes that differ in more than shade, each with a unique id', () => {
    expect(PALETTES.filter((p) => p.mode === 'dark').length).toBeGreaterThan(5);
    expect(PALETTES.filter((p) => p.mode === 'light').length).toBeGreaterThan(5);
    expect(new Set(PALETTES.map((p) => p.id)).size).toBe(PALETTES.length);
    expect(new Set(PALETTES.map((p) => p.tokens.accent)).size).toBe(PALETTES.length);
  });

  it('brings the status colours for the palette mode, so failures stay readable on a light page', () => {
    expect(Object.keys(STATUS_LIGHT).sort()).toEqual(Object.keys(STATUS_DARK).sort());
    const root = document.createElement('div');
    applyAppearance('strawberry-milk', '', '', root);
    expect(root.style.getPropertyValue('--danger-bg')).toBe(STATUS_LIGHT['danger-bg']);
    expect(root.style.getPropertyValue('--bg')).toBe('#fff0f4');
    expect(root.dataset['mode']).toBe('light');
    expect(root.style.colorScheme).toBe('light');

    applyAppearance('charcoal', '', '', root);
    expect(root.style.getPropertyValue('--danger-bg')).toBe(STATUS_DARK['danger-bg']);
    expect(root.style.colorScheme).toBe('dark');
  });

  it('keeps the ids a browser may already have saved, now as bundled fonts', () => {
    expect(fontById('rounded').stack).toContain("'Nunito'");
    expect(fontById('legible').stack).toContain("'Atkinson Hyperlegible'");
  });

  it('puts every font in exactly one group, and has more than a handful', () => {
    expect(FONT_GROUPS.flatMap((g) => g.fonts)).toEqual(FONTS);
    expect(FONTS.length).toBeGreaterThan(20);
    expect(new Set(FONTS.map((f) => f.id)).size).toBe(FONTS.length);
  });
  it('tints the logo to each palette, leaving it as drawn where the accent is already its pink', () => {
    expect(logoFilter(PALETTES.find((p) => p.id === 'strawberry-milk')!.tokens.accent)).toBe('none');
    expect(logoFilter(PALETTES.find((p) => p.id === 'fairy')!.tokens.accent)).toBe('none');
    expect(logoFilter(PALETTES.find((p) => p.id === 'forest')!.tokens.accent)).toMatch(/^hue-rotate\(-?\d+deg\)$/);
    expect(logoFilter('#808080')).toBe('grayscale(1)');
    expect(logoFilter('not a colour')).toBe('none');

    const root = document.createElement('div');
    applyAppearance('midnight', '', '', root);
    expect(root.style.getPropertyValue('--logo-filter')).toBe(logoFilter(PALETTES.find((p) => p.id === 'midnight')!.tokens.accent));
  });

  it('starts the page with the logo tinted as the default palette tints it', () => {
    expect(logoFilter(PALETTES[0].tokens.accent)).toBe('hue-rotate(-112deg)');
  });
});
