import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { BrowserNotice, browserNoticeSeen } from './browser-notice';
import { BROWSER_NOTICE_KEY } from './preferences';

async function show() {
  const fixture = TestBed.createComponent(BrowserNotice);
  await fixture.whenStable();
  const element = fixture.nativeElement as HTMLElement;
  const gotIt = () =>
    Array.from(element.querySelectorAll('button')).find((b) => b.textContent?.includes('Got it'))!;
  return { fixture, element, gotIt };
}

describe('BrowserNotice', () => {
  beforeEach(() => localStorage.clear());

  it('is shown once: Got it turns it off, with no box to tick', async () => {
    const { element, gotIt } = await show();
    expect(element.querySelector('input[name="dontShowAgain"]')).toBeNull();

    gotIt().click();

    expect(browserNoticeSeen()).toBe(true);
  });

  it('keeps coming back when set to ask always, until its own box is ticked', async () => {
    localStorage.setItem(BROWSER_NOTICE_KEY, 'always');
    let { fixture, element, gotIt } = await show();

    gotIt().click();
    expect(browserNoticeSeen()).toBe(false);
    expect(localStorage.getItem(BROWSER_NOTICE_KEY)).toBe('always');

    ({ fixture, element, gotIt } = await show());
    const box = element.querySelector<HTMLInputElement>('input[name="dontShowAgain"]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    gotIt().click();

    expect(browserNoticeSeen()).toBe(true);
  });
});
