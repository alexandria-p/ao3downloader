import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HelperConnection, PasscodeResult } from './helper-connection';
import { PasscodeGate } from './passcode-gate';

class FakeHelper extends HelperConnection {
  result: PasscodeResult = 'accepted';
  offered: string[] = [];

  override async tryPasscode(passcode: string): Promise<PasscodeResult> {
    this.offered.push(passcode);
    return this.result;
  }
}

let helper: FakeHelper;
let fixture: ComponentFixture<PasscodeGate>;
let element: HTMLElement;

async function type(passcode: string) {
  const input = element.querySelector('input') as HTMLInputElement;
  input.value = passcode;
  input.dispatchEvent(new Event('input'));
  await fixture.whenStable();
}

async function submit() {
  element.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  await fixture.whenStable();
  await fixture.whenStable();
}

describe('PasscodeGate', () => {
  beforeEach(async () => {
    helper = new FakeHelper();
    TestBed.configureTestingModule({ providers: [{ provide: HelperConnection, useValue: helper }] });
    fixture = TestBed.createComponent(PasscodeGate);
    await fixture.whenStable();
    element = fixture.nativeElement as HTMLElement;
  });

  it('says the page is passcode protected and offers no way to close it', () => {
    expect(element.textContent).toContain('passcode protected');
    expect(element.querySelector('[aria-label="Close"]')).toBeNull();
  });

  it('cannot be submitted empty', () => {
    const unlock = element.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(unlock.disabled).toBe(true);
  });

  it('hands a passcode the helper accepts on, and says it is unlocked', async () => {
    const unlocked = vi.fn();
    fixture.componentInstance.unlocked.subscribe(unlocked);

    await type('right');
    await submit();

    expect(helper.offered).toEqual(['right']);
    expect(unlocked).toHaveBeenCalledOnce();
  });

  it('says so when the passcode is refused, and stays up', async () => {
    helper.result = 'refused';
    const unlocked = vi.fn();
    fixture.componentInstance.unlocked.subscribe(unlocked);

    await type('wrong');
    await submit();
    fixture.detectChanges();

    expect(element.querySelector('[role="alert"]')?.textContent).toContain('not accepted');
    expect(unlocked).not.toHaveBeenCalled();
  });

  it('tells a helper that is asleep apart from a wrong passcode', async () => {
    helper.result = 'unreachable';

    await type('anything');
    await submit();
    fixture.detectChanges();

    expect(element.querySelector('[role="alert"]')?.textContent).toContain('Could not reach');
  });
});
