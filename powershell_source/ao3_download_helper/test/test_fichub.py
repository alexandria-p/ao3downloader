"""FicHub: asked at the end of a run for the works ao3 would not give us.

The fixture is FicHub's real answer for 75354806, Wolfbird - a work ao3 no longer serves -
as it came back from https://fichub.net/api/v0/epub?q=https://archiveofourown.org/works/75354806.
"""

import io
import json
import os
import zipfile
from unittest.mock import MagicMock

import pytest

from source_code import exceptions, fichub, indexing, server, strings
from source_code.ao3 import Ao3


FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'fichub', 'wolfbird.json')
LINK = 'https://archiveofourown.org/works/75354806'


def wolfbird() -> dict:
    with open(FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def answering(status: int = 200, body=None, content: bytes = b'', content_type: str = ''):
    response = MagicMock()
    response.status_code = status
    response.content = content
    response.headers = {'Content-Type': content_type}
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    repo = MagicMock()
    repo.my_request.return_value = response
    return repo


# region what FicHub says, read into the index's shape

def test_a_work_fichub_has_becomes_an_entry_shaped_as_a_listing_shapes_one():
    entry = fichub.entry_from(wolfbird(), LINK)

    assert entry['id'] == '75354806'
    assert entry['link'] == LINK
    assert entry['title'] == 'Wolfbird'
    assert entry['authors'] == ['OpalApparition']
    # written the way a listing writes dates, or the next ao3 pass would rewrite them
    assert entry['date_updated'] == '27 Apr 2026'
    assert entry['date_created'] == '05 Dec 2025'
    assert (entry['chapters_published'], entry['chapters_total']) == (14, None)
    assert entry['words'] == 180137
    assert (entry['kudos'], entry['comments'], entry['bookmarks'], entry['hits']) == \
        (46052, 21360, 16962, 1976720)
    assert entry['fandoms'][0] == 'Heated Rivalry (TV)'
    assert entry['warnings'] == ['No Archive Warnings Apply']
    assert entry['tags']['rating'] == 'Explicit'
    assert entry['tags']['categories'] == ['M/M']
    assert 'Shane Hollander/Ilya Rozanov' in entry['tags']['relationships']
    assert 'Hayden Pike' in entry['tags']['characters']
    assert 'Aftercare' in entry['tags']['additional']
    assert entry['summary'].startswith('Shane Hollander is hockey’s closeted golden boy')
    assert '\n' in entry['summary']  # one line per paragraph, as a listing's summary is
    assert entry[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_WORK
    # FicHub cannot know whether you bookmarked it, so it says nothing either way
    assert strings.BOOKMARKED_FIELD not in entry
    assert 'bookmark_notes' not in entry


def test_an_entry_already_indexed_keeps_its_own_fields_and_takes_the_stats():
    existing = {'id': '75354806', 'link': LINK, 'title': 'Wolfbird', 'authors': ['OpalApparition'],
                'chapters_published': 12, 'chapters_total': None, 'words': 150000,
                'date_updated': '01 Mar 2026', 'bookmarked': True, 'bookmark_notes': 'mine',
                'summary': 'what the listing said',
                'tags': {'rating': '', 'categories': [], 'relationships': [], 'characters': [],
                         'additional': []}}

    entry = fichub.entry_from(wolfbird(), LINK, existing)

    assert entry['bookmarked'] is True
    assert entry['bookmark_notes'] == 'mine'
    assert entry['summary'] == 'what the listing said'
    assert entry['chapters_published'] == 14
    assert entry['date_updated'] == '27 Apr 2026'
    # an entry made from a work page has no tags; FicHub fills what it left blank
    assert entry['tags']['rating'] == 'Explicit'

# endregion

# region asking FicHub

def test_fichub_is_asked_by_the_works_link():
    repo = answering(body=wolfbird())
    assert fichub.lookup(repo, LINK)['meta']['title'] == 'Wolfbird'
    repo.my_request.assert_called_once_with(
        'GET', 'https://fichub.net/api/v0/epub?q=https%3A%2F%2Farchiveofourown.org%2Fworks%2F75354806')


@pytest.mark.parametrize('repo', [
    answering(status=404),
    answering(body=ValueError('not json')),
    answering(body={'err': 1, 'msg': 'not found'}),
    answering(body=['not', 'an', 'answer']),
    answering(body={**wolfbird(), 'meta': {**wolfbird()['meta'],
                                           'source': 'https://archiveofourown.org/works/1'}}),
])
def test_anything_but_an_answer_about_this_work_is_a_failure(repo):
    with pytest.raises(exceptions.FicHubException):
        fichub.lookup(repo, LINK)


def test_a_format_is_fetched_from_fichub_itself():
    repo = answering(content=b'epub bytes', content_type='application/epub+zip')
    assert fichub.download(repo, wolfbird(), 'EPUB') == b'epub bytes'
    url = repo.my_request.call_args[0][1]
    assert url.startswith('https://fichub.net/cache/epub/4g7sxdaj/')


def test_a_link_to_anywhere_but_fichub_is_not_followed():
    answer = {**wolfbird(), 'urls': {'epub': 'https://elsewhere.example/file.epub'}}
    repo = answering(content=b'x')
    with pytest.raises(exceptions.FicHubException):
        fichub.download(repo, answer, 'EPUB')
    repo.my_request.assert_not_called()


def test_a_format_fichub_does_not_make_is_a_clear_failure():
    with pytest.raises(exceptions.FicHubException, match='AZW3'):
        fichub.download(answering(), wolfbird(), 'AZW3')


def test_a_page_arriving_for_an_epub_is_not_saved_as_one():
    repo = answering(content=b'<html>', content_type='text/html; charset=utf-8')
    with pytest.raises(exceptions.FicHubException):
        fichub.download(repo, wolfbird(), 'EPUB')


def test_html_sent_as_a_zip_is_taken_out_of_it():
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, 'w') as archive:
        archive.writestr('Wolfbird.html', '<html>the work</html>')
    repo = answering(content=packed.getvalue(), content_type='application/zip')
    assert fichub.download(repo, wolfbird(), 'HTML') == b'<html>the work</html>'

# endregion

# region the step at the end of every run

def test_every_workflow_tries_fichub_just_before_the_cleanup():
    for action in server.ACTIONS:
        for dates in (False, True):
            job = server.Job(action, ['JSON', 'HTML'], 'Someone',
                             server.resolve_options({'dates': dates, 'reindex': True}))
            steps = [step for step, _ in server.step_plan(job)]
            assert steps[-3:] == ['fichub', 'cleanup', 'report'], action


def test_only_ao3_works_with_a_number_are_offered_to_fichub():
    ao3 = MagicMock()
    ao3.failures = [
        {'id': '1', 'link': 'https://archiveofourown.org/works/1', 'error': 'gone'},
        {'id': None, 'link': '', 'error': 'deleted, no number'},
        {'id': None, 'link': 'https://elsewhere.example/story', 'error': 'external'},
        {'id': None, 'link': 'https://archiveofourown.org/series/5', 'error': 'a series'},
    ]
    assert [x['id'] for x in server.fichub_candidates(ao3)] == ['1']


@pytest.fixture
def library(fake_fileops):
    for name in (strings.INDEXING_FOLDER_NAME, strings.WORKS_FOLDER_NAME):
        os.makedirs(os.path.join(fake_fileops.downloadfolder, name), exist_ok=True)
    return fake_fileops


def a_run(library, filetypes, failures, answer='yes', background=False):
    job = server.Job(server.ACTION_BOOKMARKS, filetypes, 'Someone', background=background)
    asked = []

    def ask(question, default):
        asked.append((question, default))
        return {'choice': answer} if answer else dict(default)

    if not background: job.ask = ask
    ao3 = Ao3(MagicMock(), library, [x for x in filetypes if x != 'JSON'], None, False, False)
    ao3.failures = failures
    return job, ao3, asked


def index_files(library) -> list[str]:
    return sorted(os.listdir(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)))


def work_files(library) -> list[str]:
    return sorted(os.listdir(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME)))


def ao3_failed() -> list[dict]:
    return [{'id': '75354806', 'link': LINK, 'error': 'not a work file (404)'}]


@pytest.mark.fichub
def test_a_work_ao3_would_not_give_us_is_indexed_and_downloaded_from_fichub(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: f'{filetype} from fichub'.encode())
    job, ao3, asked = a_run(library, ['JSON', 'EPUB', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    question, default = asked[0]
    assert question['name'] == server.FICHUB_QUESTION
    assert question['count'] == 1 and question['ids'] == ['75354806']
    assert default == {'choice': server.FICHUB_YES}

    # named as any download is: number, title, author, and the date ao3 last updated it
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub',
                                   '75354806 Wolfbird - OpalApparition 2026-04-27.html']
    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        entry = indexing.flatten(json.load(f))
    assert entry['title'] == 'Wolfbird'
    assert entry[strings.RETRIEVED_FROM_FIELD] == {'site': 'fichub', 'downloaded': ['EPUB', 'HTML']}

    assert ao3.failures == []
    assert ao3.rescued == [{'id': '75354806', 'link': LINK, 'title': 'Wolfbird',
                            'downloaded': ['EPUB', 'HTML']}]
    assert '75354806' in ao3.downloaded


@pytest.mark.fichub
def test_fichub_reads_only_the_failed_works_entries_never_the_whole_index(library, monkeypatch):
    # in Dropbox every entry is a download of its own; reading them all to find one took a
    # run thirteen minutes before FicHub was even asked
    def whole_index(fileops):
        raise AssertionError('the whole index was read')
    monkeypatch.setattr(server.shared, 'read_index', whole_index)
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    for number in ('75354806', '1', '2'):
        with open(os.path.join(folder, f'{number} Some Title - Someone.json'), 'w', encoding='utf-8') as f:
            json.dump({'id': number, 'link': f'https://archiveofourown.org/works/{number}',
                       'title': 'Some Title', 'bookmarked': True}, f)
    read = []
    load = library.load_json
    monkeypatch.setattr(library, 'load_json', lambda path: read.append(path) or load(path))
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: b'from fichub')
    job, ao3, _ = a_run(library, ['JSON', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert [os.path.basename(x) for x in read if x.endswith('.json')][0] == \
        '75354806 Some Title - Someone.json'
    assert not any(os.path.basename(x).startswith(('1 ', '2 ')) for x in read)
    assert ao3.failures == []


@pytest.mark.fichub
def test_a_work_neither_ao3_nor_fichub_has_stays_a_failure_naming_both(library, monkeypatch):
    def nowhere(repo, link):
        raise exceptions.FicHubException('FicHub could not find it (not found)')

    monkeypatch.setattr(server.fichub, 'lookup', nowhere)
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    [failure] = ao3.failures
    assert failure['error'] == 'AO3: not a work file (404) | FicHub: FicHub could not find it (not found)'
    assert failure['fichub'] == 'FicHub could not find it (not found)'
    assert ao3.rescued == []
    assert work_files(library) == [] and index_files(library) == []


@pytest.mark.fichub
def test_a_format_fichub_cannot_give_leaves_the_work_failed_but_keeps_what_came(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fichub.download(MagicMock(), answer, filetype)
                        if filetype == 'AZW3' else b'epub')
    job, ao3, _ = a_run(library, ['JSON', 'EPUB', 'AZW3'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    [failure] = ao3.failures
    assert 'AZW3' in failure['fichub']
    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        assert indexing.flatten(json.load(f))[strings.RETRIEVED_FROM_FIELD]['downloaded'] == ['EPUB']


@pytest.mark.fichub
def test_saying_no_leaves_the_failures_as_they_were(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', MagicMock())
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed(), answer='no')

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    server.fichub.lookup.assert_not_called()
    assert ao3.failures == ao3_failed()


@pytest.mark.fichub
def test_a_background_run_tries_fichub_without_asking(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'epub')
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed(), background=True)
    job.emit = MagicMock()

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert ao3.failures == [] and len(ao3.rescued) == 1
    assert not any(c.args and c.args[0].get('type') == 'question' for c in job.emit.call_args_list)


@pytest.mark.fichub
def test_a_run_with_nothing_failed_never_asks(library):
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], [])
    job.steps = MagicMock()

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert asked == []
    job.steps.skip.assert_called_once_with('fichub')


@pytest.mark.fichub
def test_a_metadata_only_run_indexes_from_fichub_and_downloads_nothing(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', MagicMock())
    job, ao3, _ = a_run(library, ['JSON'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    server.fichub.download.assert_not_called()
    assert len(index_files(library)) == 1 and work_files(library) == []
    assert ao3.failures == []


def test_a_later_reading_from_ao3_does_not_carry_the_fichub_mark(library):
    ao3 = Ao3(MagicMock(), library, [], None, False, False)
    record = {**fichub.entry_from(wolfbird(), LINK),
              strings.RETRIEVED_FROM_FIELD: {'site': 'fichub', 'downloaded': []}}
    ao3.save_metadata(record, from_mirror=True)
    ao3.indexed_on = 'later'
    # an ao3 pass carries the whole record forward, as `refresh_one` does
    ao3.save_metadata({**record, 'kudos': 50000})

    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        saved = json.load(f)
    first, latest = saved[indexing.INDEXES]
    assert first[strings.RETRIEVED_FROM_FIELD]['site'] == 'fichub'
    assert strings.RETRIEVED_FROM_FIELD not in latest


def test_a_single_fic_ao3_will_not_show_is_handed_to_fichub_rather_than_ending_the_run(
        library, monkeypatch):
    ao3 = MagicMock()
    ao3.failures = []
    ao3.index_one_work.side_effect = exceptions.DeletedException('deleted')
    ao3.record_failure.side_effect = lambda link, e: ao3.failures.append(
        {'id': '75354806', 'link': link, 'error': str(e)})
    monkeypatch.setattr(server, 'Ao3', MagicMock(return_value=ao3))
    monkeypatch.setattr(server.shared, 'read_index', lambda fileops: [])
    finished = MagicMock()
    monkeypatch.setattr(server, 'finish_run', finished)
    job = server.Job(server.ACTION_WORK, ['JSON', 'EPUB'], 'Someone',
                     server.resolve_options({}), url='75354806')

    server.run_work(job, library, MagicMock(), MagicMock())

    finished.assert_called_once()
    assert ao3.failures[0]['id'] == '75354806'

# endregion


def a_fic_page(monkeypatch, shown: set[str]):
    """Stand AO3 in for the fic runs: the works in `shown` have a page, every other is down.
    Each existing entry handed over is kept by work number."""

    given = {}

    def index_one_work(self, link, existing=None, find_existing=None):
        work = link.rsplit('/', 1)[-1]
        print(f'(ao3 asked about {work})')
        if work not in shown: raise exceptions.Ao3DownException('AO3 is down')
        given[work] = find_existing() if find_existing else existing
        raise exceptions.DeletedException('stop here')
    monkeypatch.setattr(server.Ao3, 'index_one_work', index_one_work)
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    return given


def an_index_file(library, number: str, title: str) -> None:
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, f'{number} {title} - Someone.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': number, 'link': f'https://archiveofourown.org/works/{number}',
                   'title': title}, f)


@pytest.mark.parametrize('action, url', [
    (server.ACTION_WORK, '75354806'),
    (server.ACTION_WORKS, 'https://archiveofourown.org/works/75354806\nhttps://archiveofourown.org/works/2'),
])
def test_a_fic_run_finds_its_fics_entries_by_number_never_reading_the_whole_index(
        library, monkeypatch, action, url):
    # in Dropbox every entry is a download of its own, and reading them all held 'looking
    # up work' for minutes before ao3 was asked anything
    def whole_index(fileops):
        raise AssertionError('the whole index was read')
    monkeypatch.setattr(server.shared, 'read_index', whole_index)
    an_index_file(library, '75354806', 'Title 75354806')
    an_index_file(library, '1', 'Title 1')
    given = a_fic_page(monkeypatch, {'75354806', '2'})
    job = server.Job(action, ['JSON', 'HTML'], 'Someone', server.resolve_options({}), url=url)

    (server.run_work if action == server.ACTION_WORK else server.run_works)(
        job, library, MagicMock(), MagicMock())

    assert given['75354806']['title'] == 'Title 75354806'
    if action == server.ACTION_WORKS: assert given['2'] is None


def test_a_fic_run_asks_ao3_first_then_looks_for_its_index_file(library, monkeypatch, capsys):
    an_index_file(library, '75354806', 'Wolfbird')
    a_fic_page(monkeypatch, {'75354806', '1'})

    for url in ('75354806', '1'):
        job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', server.resolve_options({}), url=url)
        server.run_work(job, library, MagicMock(), MagicMock())
    lines = capsys.readouterr().out.splitlines()

    said = [x for x in lines if 'index file' in x or 'on AO3' in x or x.startswith('(ao3')]
    assert said == [
        'looking up work 75354806 on AO3',
        '(ao3 asked about 75354806)',
        'looking for an existing index file for work 75354806...',
        'found the index file for work 75354806: 75354806 Wolfbird - Someone.json',
        'looking up work 1 on AO3',
        '(ao3 asked about 1)',
        'looking for an existing index file for work 1...',
        'no index file for work 1 yet - a new one will be made',
    ]


def test_a_fic_ao3_will_not_show_never_reads_the_library(library, monkeypatch, capsys):
    # straight on to FicHub at the end: nothing to save, so nothing to look for
    read = []
    load = library.load_json
    monkeypatch.setattr(library, 'load_json', lambda path: read.append(path) or load(path))
    an_index_file(library, '75354806', 'Wolfbird')
    a_fic_page(monkeypatch, set())
    job = server.Job(server.ACTION_WORKS, ['JSON'], 'Someone', server.resolve_options({}),
                     url=LINK + '\nhttps://archiveofourown.org/works/2')

    server.run_works(job, library, MagicMock(), MagicMock())

    assert not [x for x in read if 'indexing' in str(x)]
    assert 'index file' not in capsys.readouterr().out
    assert [x['id'] for x in job.ao3.failures] == ['75354806', '2']


def test_several_fics_each_ask_ao3_then_look_for_their_own_index_file(library, monkeypatch, capsys):
    an_index_file(library, '75354806', 'Wolfbird')
    a_fic_page(monkeypatch, {'75354806', '2'})
    job = server.Job(server.ACTION_WORKS, ['JSON'], 'Someone', server.resolve_options({}),
                     url=LINK + '\nhttps://archiveofourown.org/works/2')

    server.run_works(job, library, MagicMock(), MagicMock())
    said = [x for x in capsys.readouterr().out.splitlines()
            if 'index file' in x or 'on AO3' in x]

    assert said == [
        'fic 1 of 2: looking up work 75354806 on AO3',
        'looking for an existing index file for work 75354806...',
        'found the index file for work 75354806: 75354806 Wolfbird - Someone.json',
        'fic 2 of 2: looking up work 2 on AO3',
        'looking for an existing index file for work 2...',
        'no index file for work 2 yet - a new one will be made',
    ]


@pytest.mark.fichub
def test_fichub_says_what_it_is_about_to_do_before_each_thing(library, monkeypatch, capsys):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'bytes')
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    said = [x.strip() for x in capsys.readouterr().out.splitlines() if x.strip()]
    order = [
        'trying FicHub for 1 works: 75354806',
        f'FicHub 1 of 1: asking FicHub about work 75354806 ({LINK})...',
        'FicHub has work 75354806: Wolfbird',
        'fetching EPUB of work 75354806 from FicHub...',
        'writing the index entry for work 75354806 from what FicHub says...',
        'index updated for work 75354806 from FicHub',
    ]
    places = [said.index(line) for line in order]
    assert places == sorted(places)


def test_a_fic_run_names_the_work_whose_index_it_did_or_did_not_update(library, monkeypatch, capsys):
    ao3 = MagicMock()
    ao3.failures = []
    ao3.reindexed = {'1'}
    ao3.index_one_work.side_effect = lambda link, existing=None, find_existing=None: (
        {'id': link.rsplit('/', 1)[1], 'link': link} if not link.endswith('/2')
        else (_ for _ in ()).throw(exceptions.DeletedException('deleted')))
    monkeypatch.setattr(server, 'Ao3', MagicMock(return_value=ao3))
    monkeypatch.setattr(server.shared, 'read_index', lambda fileops: [])
    monkeypatch.setattr(server, 'index_marked_series', lambda *a: [])
    monkeypatch.setattr(server, 'download_planned', MagicMock())
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    links = [f'https://archiveofourown.org/works/{n}' for n in (1, 2, 3)]
    job = server.Job(server.ACTION_WORKS, ['JSON'], 'Someone', server.resolve_options({}),
                     url='\n'.join(links))

    server.run_works(job, library, MagicMock(), MagicMock())

    said = capsys.readouterr().out
    assert 'index updated for work 1' in said
    # ao3 would not show it
    assert 'index not updated for work 2' in said
    # read, but its entry was not written - a save that failed is not claimed
    assert 'index not updated for work 3' in said
