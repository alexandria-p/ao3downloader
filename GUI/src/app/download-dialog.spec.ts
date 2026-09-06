import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { DownloadDialog } from './download-dialog';
import { JobAction, JobEvent, Jobs, ServerConfig, StartRequest } from './jobs';

const CONFIG: ServerConfig = {
  downloadFolder: 'my_downloads',
  username: 'Someone',
  filetypes: ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML', 'JSON'],
  forced: ['JSON', 'HTML'],
};

class FakeJobs extends Jobs {
  started: StartRequest[] = [];
  cancelled: string[] = [];
  push: ((event: JobEvent) => void) | null = null;
  closed = false;

  override async loadConfig(): Promise<ServerConfig | null> {
    this.config.set(CONFIG);
    this.available.set(true);
    return CONFIG;
  }

  override async start(request: StartRequest): Promise<string> {
    this.started.push(request);
    return 'job-1';
  }

  override async cancel(jobId: string): Promise<void> {
    this.cancelled.push(jobId);
  }

  override stream(_id: string, onEvent: (e: JobEvent) => void): () => void {
    this.push = onEvent;
    return () => {
      this.closed = true;
    };
  }
}

let jobs: FakeJobs;
let fixture: ComponentFixture<DownloadDialog>;
let element: HTMLElement;

async function open(action: JobAction = 'bookmarks') {
  fixture = TestBed.createComponent(DownloadDialog);
  fixture.componentRef.setInput('action', action);
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
}

function button(text: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === text,
  );
}

function checkbox(labelText: string): HTMLInputElement | undefined {
  return Array.from(element.querySelectorAll<HTMLLabelElement>('label.check'))
    .find((l) => l.textContent?.includes(labelText))
    ?.querySelector('input') as HTMLInputElement | undefined;
}

async function advanceTo(step: 'options' | 'credentials' | 'running') {
  button('Continue')?.click();
  await fixture.whenStable();
  if (step === 'options') return;

  button('Continue')?.click();
  await fixture.whenStable();
  if (step === 'credentials') return;

  const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
  password.value = 'a-password';
  password.dispatchEvent(new Event('input'));
  await fixture.whenStable();

  button('Start download')?.click();
  await fixture.whenStable();
}

describe('DownloadDialog', () => {
  beforeEach(async () => {
    jobs = new FakeJobs();
    TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
  });

  // region file types

  it('locks the file types that are always produced', async () => {
    await open();

    for (const forced of CONFIG.forced) {
      const input = checkbox(forced)!;
      expect(input.checked, forced).toBe(true);
      expect(input.disabled, forced).toBe(true);
    }
    expect(checkbox('EPUB')!.disabled).toBe(false);
    expect(checkbox('EPUB')!.checked).toBe(false);
  });

  // endregion

  // region options step

  it('asks the listing questions the console asks, for a bookmarks run', async () => {
    await open('bookmarks');
    await advanceTo('options');

    expect(element.querySelector('input[type="number"]')).toBeTruthy();
    expect(checkbox('series links')).toBeTruthy();
    expect(checkbox('embedded images')).toBeTruthy();
  });

  it('does not offer the publication date lookup', async () => {
    // hidden from the ui: it costs one request per work and is rarely worth it
    await open('bookmarks');
    await advanceTo('options');

    expect(checkbox('publication date')).toBeUndefined();
  });

  it('never asks the helper for publication dates', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(jobs.started[0].options.workdates).toBe(false);
  });

  it('leaves out the questions that mean nothing for an update run', async () => {
    await open('update');
    await advanceTo('options');

    // no listing to page through, no series to expand, no metadata to date
    expect(element.querySelector('input[type="number"]')).toBeNull();
    expect(checkbox('series links')).toBeUndefined();
    expect(checkbox('publication date')).toBeUndefined();
    // images still apply to a re-download
    expect(checkbox('embedded images')).toBeTruthy();
  });

  it('sends the chosen options with the job', async () => {
    await open('bookmarks');
    await advanceTo('options');

    const pages = element.querySelector<HTMLInputElement>('input[type="number"]')!;
    pages.value = '3';
    pages.dispatchEvent(new Event('input'));
    checkbox('series links')!.click();
    checkbox('embedded images')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started).toHaveLength(1);
    expect(jobs.started[0].options).toEqual({
      pages: 3,
      series: true,
      images: true,
      workdates: false,
    });
  });

  it('treats a blank or zero page limit as every page', async () => {
    await open('bookmarks');
    await advanceTo('options');

    const pages = element.querySelector<HTMLInputElement>('input[type="number"]')!;
    pages.value = '';
    pages.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.pages).toBe(0);
  });

  // endregion

  // region running

  it('shows what the run was asked to do', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const chosen = element.querySelector('.chosen')?.textContent ?? '';
    expect(chosen).toContain('JSON');
    expect(chosen).toContain('HTML');
    expect(chosen).toContain('all pages');
    expect(chosen).toContain('my_downloads');
  });

  it('names the fic and the format currently being fetched', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'work', title: '123 A Fic - Author', filetype: 'EPUB' });
    await fixture.whenStable();

    const current = element.querySelector('.current')?.textContent ?? '';
    expect(current).toContain('123 A Fic - Author');
    expect(current).toContain('EPUB');
  });

  it('keeps the fic name when a work event carries no format', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'work', title: '123 A Fic - Author' });
    await fixture.whenStable();

    const current = element.querySelector('.current')?.textContent ?? '';
    expect(current).toContain('123 A Fic - Author');
  });

  it('tracks progress from page events', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 20, total: 80, works: 400 });
    await fixture.whenStable();

    expect(element.querySelector('.percent')?.textContent).toContain('25');
  });

  it('warns when ao3 asks the run to slow down', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'paused', seconds: 300, until: '12:05:00' });
    await fixture.whenStable();

    const pause = element.querySelector('.pause')?.textContent ?? '';
    expect(pause).toContain('300');
    expect(pause).toContain('12:05:00');

    jobs.push!({ type: 'resumed' });
    await fixture.whenStable();
    expect(element.querySelector('.pause')).toBeNull();
  });

  // endregion

  // region stopping

  it('offers a stop button while the run is working', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(button('Stop')).toBeTruthy();
  });

  it('asks the helper to stop when it is pressed', async () => {
    await open('bookmarks');
    await advanceTo('running');

    button('Stop')!.click();
    await fixture.whenStable();

    expect(jobs.cancelled).toEqual(['job-1']);
    // and does not let it be pressed twice
    expect(button('Stopping...')?.disabled).toBe(true);
  });

  it('reports a stop as kept work rather than a failure', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'finished', cancelled: true });
    await fixture.whenStable();

    expect(element.querySelector('.error')).toBeNull();
    const warning = element.querySelector('.warning')?.textContent ?? '';
    expect(warning).toContain('Stopped');
    expect(warning).toContain('kept');
  });

  it('reports a clean finish as success', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'finished', cancelled: false });
    await fixture.whenStable();

    expect(element.querySelector('.success')?.textContent).toContain('Finished');
  });

  // endregion
});
