import { TestBed } from '@angular/core/testing';
import { VISIT_LOG_LIMIT, VisitErrorHandler, VisitLog } from './visit-log';

describe('VisitLog', () => {
  let visit: VisitLog;
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [VisitErrorHandler] });
    visit = TestBed.inject(VisitLog);
  });

  it('starts with the page opening, and stamps every line in UTC', () => {
    visit.note('Tab opened: history');
    const lines = visit.text().split('\n');
    expect(lines[0]).toMatch(/^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC\] Page opened$/);
    expect(lines[1]).toMatch(/UTC\] Tab opened: history$/);
  });

  it('keeps only the last entries, and says the earlier ones went', () => {
    for (let i = 0; i < VISIT_LOG_LIMIT + 5; i++) visit.note(`entry ${i}`);
    expect(visit.size).toBe(VISIT_LOG_LIMIT);
    const text = visit.text();
    expect(text.split('\n')[0]).toContain('earlier entries dropped');
    expect(text).toContain(`entry ${VISIT_LOG_LIMIT + 4}`);
    expect(text).not.toContain('Page opened');
  });

  it('notes an error with its name, message and where it came from', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    TestBed.inject(VisitErrorHandler).handleError(new TypeError('cannot read the folder'));
    expect(visit.text()).toMatch(/Error: TypeError: cannot read the folder/);
  });
});
