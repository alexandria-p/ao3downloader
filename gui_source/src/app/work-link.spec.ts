import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Library } from './library';
import { WorkLink } from './work-link';

@Component({
  imports: [WorkLink],
  template: `
    <a id="held" href="https://archiveofourown.org/works/111" [appWorkLink]="'111'" target="_blank">111</a>
    <a id="not-held" href="https://archiveofourown.org/works/222" [appWorkLink]="'222'" target="_blank">222</a>
  `,
})
class Links {}

describe('WorkLink', () => {
  let opened: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    opened = vi.fn(() => ({ location: { href: '' }, close: () => {} }));
    vi.stubGlobal('open', opened);
    TestBed.inject(Library).copies.update((c) => ({
      ...c,
      html: new Map([['111', new File(['<p>one</p>'], '111 One - A 2026-01-02.html')]]),
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  function click(id: string, init: MouseEventInit = {}): MouseEvent {
    const fixture = TestBed.createComponent(Links);
    fixture.detectChanges();
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...init });
    (fixture.nativeElement as HTMLElement).querySelector(`#${id}`)!.dispatchEvent(event);
    return event;
  }

  it('opens your downloaded copy instead of AO3 when the library holds one', () => {
    const event = click('held');
    expect(event.defaultPrevented).toBe(true);
    expect(opened).toHaveBeenCalledWith('', '_blank');
  });

  it('goes to AO3 as before when there is no copy', () => {
    const event = click('not-held');
    expect(event.defaultPrevented).toBe(false);
    expect(opened).not.toHaveBeenCalled();
  });

  it('leaves a ctrl-click to the browser, so the AO3 page is still a click away', () => {
    const event = click('held', { ctrlKey: true });
    expect(event.defaultPrevented).toBe(false);
    expect(opened).not.toHaveBeenCalled();
  });

  it('says on the link that it opens your copy', () => {
    const fixture = TestBed.createComponent(Links);
    fixture.detectChanges();
    const held = (fixture.nativeElement as HTMLElement).querySelector('#held')!;
    expect(held.classList).toContain('local');
    expect(held.getAttribute('title')).toBe('Open your downloaded copy');
  });
});
