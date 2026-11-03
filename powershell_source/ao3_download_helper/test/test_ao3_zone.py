"""AO3 dates its listings in the zone it shows each person, while every time this app records
is UTC. So a floor or ceiling - a UTC moment - is turned into a date in that person's AO3 zone
(set in the page's User settings, the browser's own zone until changed) before the two are
compared, and a fic AO3 dates on or after the floor is one updated on or after it.
"""

import datetime
from unittest.mock import MagicMock

import pytest

from source_code import runs, server


def zone(name: str):
    return server.ao3_zone(name)


# region a UTC moment as the day AO3 would date it

@pytest.mark.parametrize('name, day', [
    # 02:00 UTC on the 3rd is still the 2nd in New York, already the 3rd in Sydney
    ('America/New_York', '2026-11-02'),
    ('Australia/Sydney', '2026-11-03'),
    ('UTC', '2026-11-03'),
])
def test_a_moment_is_dated_as_ao3_dates_it_in_the_person_s_zone(name, day):
    assert server.ao3_day('2026-11-03T02:00:00+00:00', zone(name)) == day


def test_with_no_zone_a_moment_is_dated_in_utc():
    assert server.ao3_day('2026-11-03T23:30:00+00:00', None) == '2026-11-03'


def test_an_older_record_s_naive_time_is_taken_as_written():
    assert server.ao3_day('2026-11-03T23:30:00', zone('Australia/Sydney')) == '2026-11-03'


def test_daylight_saving_is_the_zone_s_own():
    # London is UTC+1 in summer: 23:30 UTC on 1 July is already the 2nd there
    assert server.ao3_day('2026-07-01T23:30:00+00:00', zone('Europe/London')) == '2026-07-02'
    assert server.ao3_day('2026-01-01T23:30:00+00:00', zone('Europe/London')) == '2026-01-01'

# endregion


# region the zone a page sends

def test_no_zone_is_utc():
    assert server.ao3_zone('') is None and server.ao3_zone(None) is None


@pytest.mark.parametrize('bad', ['../../etc/passwd', 'Europe London', 5, 'x' * 80])
def test_anything_that_is_not_a_zone_name_is_refused(bad):
    with pytest.raises(ValueError):
        server.ao3_zone(bad)


def test_a_zone_this_computer_cannot_look_up_is_utc_rather_than_a_refused_run():
    assert server.ao3_zone('Nowhere/Atlantis') is None

# endregion


# region where a quick scan stops

def a_job(zone_name: str, baseline: str, resume=True) -> server.Job:
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'Someone')
    job.ao3_zone = server.ao3_zone(zone_name)
    job.ao3_zone_name = zone_name
    job.baseline = baseline
    job.resume = {'id': 'earlier'} if resume else None
    return job


def test_a_floor_is_the_day_the_last_scan_started_in_the_person_s_ao3_zone(monkeypatch):
    last = {'id': 'r', 'status': runs.STATUS_SUCCESS, 'baseline': '2026-11-03T02:00:00+00:00'}
    monkeypatch.setattr(runs, 'last_successful', lambda *a, **k: last)
    # a fic updated in New York at 21:30 on the 2nd - after the scan began at 02:00 UTC on the
    # 3rd - is dated the 2nd there, and a UTC floor of the 3rd would have stopped above it
    assert server.quick_scan_floor(MagicMock(), zone('America/New_York')) == '2026-11-02'
    assert server.quick_scan_floor(MagicMock(), None) == '2026-11-03'


def test_a_retry_s_ceiling_is_its_first_attempt_s_day_in_the_person_s_ao3_zone():
    job = a_job('Australia/Sydney', '2026-11-02T20:00:00+00:00')
    assert server.retry_ceiling(job) == '2026-11-03'
    assert server.retry_ceiling(a_job('', '2026-11-02T20:00:00+00:00')) == '2026-11-02'

# endregion


def test_the_helper_says_whether_it_can_look_up_a_zone():
    # the Windows app's build fails on false: a zone database has to be packed in there
    assert server.zone_lookup_works() is True


# region a typed range, kept in UTC and compared in the AO3 zone

def test_a_typed_range_end_is_kept_as_a_utc_moment():
    assert server.range_moment('2023-12-31T13:00:00+00:00') == '2023-12-31T13:00:00+00:00'
    assert server.range_moment('2024-01-01T00:00:00+11:00') == '2023-12-31T13:00:00+00:00'
    # an older page sent a bare day, kept as one
    assert server.range_moment('2024-01-01') == '2024-01-01'
    assert server.range_moment('rubbish') == ''


def test_a_typed_range_is_compared_as_the_days_it_is_in_the_ao3_zone():
    job = a_job('Australia/Sydney', '', resume=False)
    job.options = {'dateFrom': '2023-12-31T13:00:00+00:00', 'dateTo': '2024-06-30T13:59:59+00:00'}
    assert server.range_day(job, 'dateFrom') == '2024-01-01'
    assert server.range_day(job, 'dateTo') == '2024-06-30'


def test_a_quick_scan_keeps_its_floor_as_the_utc_moment_it_stands_for(monkeypatch):
    last = {'id': 'r', 'status': runs.STATUS_SUCCESS, 'baseline': '2026-11-03T02:00:00+00:00'}
    monkeypatch.setattr(runs, 'last_successful', lambda *a, **k: last)
    assert server.quick_scan_floor_at(MagicMock()) == '2026-11-03T02:00:00+00:00'
    assert server.quick_scan_floor(MagicMock(), zone('America/New_York')) == '2026-11-02'


def test_the_newest_index_time_is_the_latest_moment_not_the_latest_day():
    records = [{'last_indexed': '2026-11-03T01:00:00+00:00'},
               {'last_indexed': '2026-11-02T23:00:00+00:00'}, {'last_indexed': ''}]
    assert server.newest_indexed_at(records) == '2026-11-03T01:00:00+00:00'
    assert server.newest_indexed_on(records, zone('America/New_York')) == '2026-11-02'

# endregion


# region times a run's own lines say

def test_a_run_s_lines_say_a_kept_time_in_the_ao3_zone_and_name_it():
    assert runs.shown('2026-11-03T10:15:00+00:00', zone('Australia/Sydney')) == \
        '2026-11-03 21:15 Australia/Sydney'
    assert runs.shown('2026-11-03T10:15:00+00:00') == '2026-11-03 10:15 UTC'

# endregion
