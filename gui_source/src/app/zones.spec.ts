import { beforeEach, describe, expect, it } from 'vitest';
import { AO3_TIME_ZONE_KEY, inAo3Zone, utcToZonedDay, zonedDayToUtc } from './preferences';
import { lineTime } from './download-dialog';

describe('times in the AO3 time zone', () => {
  beforeEach(() => localStorage.clear());

  it('turns a day typed in the AO3 zone into the UTC moments it begins and ends', () => {
    localStorage.setItem(AO3_TIME_ZONE_KEY, 'America/New_York');
    // winter: New York is 5 hours behind
    expect(zonedDayToUtc('2026-01-15')).toBe('2026-01-15T05:00:00+00:00');
    expect(zonedDayToUtc('2026-01-15', true)).toBe('2026-01-16T04:59:59+00:00');
    // summer: 4 hours, the zone's own daylight saving
    expect(zonedDayToUtc('2026-07-15')).toBe('2026-07-15T04:00:00+00:00');
    expect(zonedDayToUtc('not a day')).toBe('');
  });

  it('says a kept UTC moment as the day it is in the AO3 zone, and a bare day as itself', () => {
    localStorage.setItem(AO3_TIME_ZONE_KEY, 'Australia/Sydney');
    expect(utcToZonedDay('2026-11-02T20:00:00+00:00')).toBe('2026-11-03');
    expect(utcToZonedDay('2026-11-02')).toBe('2026-11-02');
    // and back: the day a typed range began on is the day it shows
    expect(utcToZonedDay(zonedDayToUtc('2026-11-03'))).toBe('2026-11-03');
    expect(utcToZonedDay(zonedDayToUtc('2026-11-03', true))).toBe('2026-11-03');
  });

  it('shows every time in the AO3 zone', () => {
    localStorage.setItem(AO3_TIME_ZONE_KEY, 'Asia/Tokyo');
    const at = new Date('2026-11-03T00:00:00Z');
    expect(lineTime(at)).toBe(at.toLocaleTimeString([], { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    expect(inAo3Zone({ hour: '2-digit' }).timeZone).toBe('Asia/Tokyo');
  });

  it('falls back to the browser\'s own for a zone it cannot name', () => {
    localStorage.setItem(AO3_TIME_ZONE_KEY, 'Nowhere/Atlantis');
    expect(inAo3Zone().timeZone).toBeUndefined();
  });
});
