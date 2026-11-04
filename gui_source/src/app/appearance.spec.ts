import { describe, expect, it } from 'vitest';
import { CUSTOM_FONT, FONTS, PALETTES, applyAppearance, cleanFontName, fontStack } from './appearance';

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
});
