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
