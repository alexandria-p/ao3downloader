import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { LibrarySetup, SetupTarget } from './library-setup';
import { SetupOverlay } from './setup-overlay';

async function render() {
  const fixture = TestBed.createComponent(SetupOverlay);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement };
}

/** a library that answers with whatever the test hands it, and records what was asked */
function target(folders: string[], files: string[] = []): SetupTarget & { made: string[] } {
  const made: string[] = [];
  let release: () => void = () => {};
  const held = new Promise<void>((r) => (release = r));
  return {
    made,
    topLevel: async () => ({ folders, files }),
    makeFolder: async (name) => {
      made.push(name);
      if (made.length === 1) await held;
    },
    moveToWorks: async (names, progress) => {
      progress(names.length);
      return { moved: names.length, notMoved: [] };
    },
    // lets a test look at the overlay while the first folder is being made
    release,
  } as SetupTarget & { made: string[]; release: () => void };
}

describe('SetupOverlay', () => {
  it('shows nothing, and blocks nothing, while there is nothing to set up', async () => {
    const { element } = await render();
    expect(element.querySelector('.cover')).toBeNull();
  });

  it('covers the page with a spinner and says what it is making', async () => {
    const setup = TestBed.inject(LibrarySetup);
    const library = target(['indexing']) as SetupTarget & { made: string[]; release: () => void };
    const preparing = setup.prepare(library, '/Apps/ao3-downloader');
    const { fixture, element } = await render();
    fixture.detectChanges();

    expect(element.querySelector('.cover')).toBeTruthy();
    expect(element.querySelector('.spinner')).toBeTruthy();
    expect(element.textContent).toContain('Setting up /Apps/ao3-downloader');
    expect(element.textContent).toContain('collections, images, runs, works');
    expect(element.querySelector('.cover')?.getAttribute('aria-busy')).toBe('true');

    library.release();
    await preparing;
    fixture.detectChanges();
    expect(element.querySelector('.cover')).toBeNull();
  });

  it('asks about top-level works, and moves them on the answer', async () => {
    const setup = TestBed.inject(LibrarySetup);
    const all = ['indexing', 'collections', 'images', 'runs', 'works'];
    const preparing = setup.prepare(target(all, ['111 A.html', '222 B.epub']), 'downloads');
    await new Promise((r) => setTimeout(r, 0));
    const { fixture, element } = await render();

    expect(element.querySelector('.cover')?.getAttribute('role')).toBe('alertdialog');
    expect(element.textContent).toContain('2');
    const move = Array.from(element.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Move them'),
    )!;
    move.click();
    await preparing;
    fixture.detectChanges();

    expect(setup.state()).toBe('idle');
    expect(element.querySelector('.cover')).toBeNull();
  });
});
