"""FicHub, a mirror ao3 works can be fetched from when ao3 itself will not give them to us.

FicHub (fichub.net) keeps its own copies of ao3 works, including ones ao3 has since taken
down. Its api answers a work's link with the work's details - title, author, tags, stats -
and where each format it has made can be fetched. A run turns to it only at the end, for
the works ao3 failed on, and only when the person running it says yes (`server.rescue_with_fichub`).

Every request goes through the run's own `Repository`, so a stop, a pause and the run's
pacing all apply to FicHub exactly as they do to ao3.
"""

import io
import urllib.parse
import zipfile

from bs4 import BeautifulSoup
from requests import codes

from source_code import exceptions, parse_soup, parse_text, strings


def lookup(repo, link: str) -> dict:
    """What FicHub has for one ao3 work: its answer, as it gave it.

    Raises `FicHubException` for anything but a work FicHub knows - an error it reports, a
    status that is not 200, a body that is not its json, or an answer about some other work.
    The last is checked rather than trusted, because the answer is about to be written into
    that work's index entry and named after it.
    """

    url = strings.FICHUB_API_URL + '?q=' + urllib.parse.quote(link, safe='')
    response = repo.my_request('GET', url)
    if response.status_code != codes['ok']:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_STATUS.format(response.status_code))
    try:
        answer = response.json()
    except ValueError as e:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_NOT_JSON) from e
    if not isinstance(answer, dict) or not isinstance(answer.get('meta'), dict):
        raise exceptions.FicHubException(strings.ERROR_FICHUB_NOT_JSON)
    if answer.get('err'):
        raise exceptions.FicHubException(strings.ERROR_FICHUB_LOOKUP.format(
            answer.get('msg') or answer.get('err')))

    asked = parse_text.get_work_number(link)
    source = parse_text.get_work_number(str(answer['meta'].get('source') or ''))
    if asked and source and source != asked:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_WRONG_WORK.format(source))
    return answer


def count(value) -> int | None:
    """A stat as FicHub writes it - '16,962' in the extended meta, 180137 at the top - read
    the way a listing blurb's is."""

    if value is None: return None
    return parse_text.get_count(str(value))


def entry_from(answer: dict, link: str, existing: dict | None = None) -> dict:
    """The index entry FicHub's answer describes, shaped as a listing blurb shapes one.

    For a work the index already has, it keeps everything it has - the bookmark's own fields
    and `bookmarked` above all, which FicHub cannot know - and takes from FicHub the stats
    that move when a fic is updated, as `Ao3.refresh_one` does from a work page, plus
    anything the entry left blank (an entry made from a work page has no tags). For a new
    one it is the whole of what FicHub says, without the bookmark fields.

    FicHub's extended meta carries what ao3's work page says, under ao3's own names; the
    top-level meta is FicHub's summary of it, used where the extended one is missing.
    """

    meta = answer.get('meta') or {}
    raw = meta.get('rawExtendedMeta') or {}
    stats = raw.get('stats') or {}

    published, total = parse_text.get_chapter_counts(str(stats.get('chapters') or ''))
    if published is None: published = count(meta.get('chapters'))
    # ao3 writes 'Updated:' or 'Completed:' beside 'Published:'; FicHub keeps that one as
    # 'status' and its own reading of it as 'updated'. a one-shot has neither
    updated = (stats.get('status') or stats.get('updated') or str(meta.get('updated') or '')[:10]
               or stats.get('published') or str(meta.get('created') or '')[:10])
    created = stats.get('published') or str(meta.get('created') or '')[:10]

    fresh = {
        'chapters_published': published,
        'chapters_total': total,
        'words': count(stats.get('words')) if stats.get('words') is not None else count(meta.get('words')),
        'comments': count(stats.get('comments')),
        'kudos': count(stats.get('kudos')),
        'bookmarks': count(stats.get('bookmarks')),
        'hits': count(stats.get('hits')),
        # written the way a listing writes it, or a later ao3 pass would rewrite it
        'date_updated': parse_text.get_listing_date(updated),
    }

    def tags(name: str) -> list[str]:
        found = raw.get(name)
        return [str(x).strip() for x in found if str(x).strip()] if isinstance(found, list) else []

    summary = ''
    if meta.get('description'):
        summary = parse_soup.get_userstuff_text(
            BeautifulSoup(str(meta['description']), 'html.parser')).strip()
    authors = [x.strip() for x in str(meta.get('author') or '').split(',') if x.strip()]

    whole = {
        'id': parse_text.get_work_number(link),
        'link': link,
        'title': str(meta.get('title') or ''),
        'authors': authors or ['Anonymous'],
        'date_created': parse_text.get_listing_date(created) or None,
        'fandoms': tags('fandom'),
        'warnings': tags('warning'),
        'tags': {
            'rating': ', '.join(tags('rating')),
            'categories': tags('category'),
            'relationships': tags('relationship'),
            'characters': tags('character'),
            'additional': tags('freeform'),
        },
        'summary': summary,
        **fresh,
        strings.BOOKMARK_TYPE_FIELD: strings.BOOKMARK_TYPE_WORK,
    }

    if not existing: return whole

    record = {**existing, **fresh}
    for key, value in whole.items():
        if key not in record or blank(record[key]): record[key] = value
    return record


def blank(value) -> bool:
    """Whether a field says nothing, so FicHub's value may fill it."""

    if isinstance(value, dict): return all(blank(x) for x in value.values())
    return value is None or value == '' or value == []


def download(repo, answer: dict, filetype: str) -> bytes:
    """One format of a work, from where FicHub's answer says it is.

    Only from fichub.net itself: the answer names the file by a path on its own site, and a
    link to anywhere else is refused rather than followed. Checked as ao3's files are - a
    status that is not 200, or a page arriving for a format that is not html, is a failure,
    never a file saved under the format's name.

    FicHub sends its html as a zip holding the page; the page is taken out of it, so the
    file saved is the html every other copy of a work is.
    """

    shown = filetype.upper()
    if shown not in strings.FICHUB_FORMATS:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_NO_FORMAT.format(shown))
    key = filetype.lower()
    path = (answer.get('urls') or {}).get(key) or answer.get(key + '_url')
    if not path:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_NO_FORMAT.format(shown))

    url = urllib.parse.urljoin(strings.FICHUB_BASE_URL + '/', str(path))
    where = urllib.parse.urlparse(url)
    if where.scheme != 'https' or where.netloc != urllib.parse.urlparse(strings.FICHUB_BASE_URL).netloc:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_ELSEWHERE.format(shown))

    response = repo.my_request('GET', url)
    if response.status_code != codes['ok']:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_NOT_A_FILE.format(
            shown, strings.ERROR_FICHUB_STATUS.format(response.status_code)))
    content = response.content
    if shown == 'HTML':
        return unzipped_html(content)
    content_type = (response.headers.get('Content-Type') or '').lower()
    if 'text/html' in content_type:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_NOT_A_FILE.format(
            shown, content_type))
    return content


def unzipped_html(content: bytes) -> bytes:
    """The html page inside a zip FicHub sent, or the content as it came if it is no zip."""

    if not content.startswith(b'PK'): return content
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            pages = [x for x in archive.namelist() if x.lower().endswith(('.html', '.htm'))]
            if not pages:
                raise exceptions.FicHubException(strings.ERROR_FICHUB_NOT_A_FILE.format('HTML', 'zip'))
            return archive.read(pages[0])
    except zipfile.BadZipFile as e:
        raise exceptions.FicHubException(strings.ERROR_FICHUB_NOT_A_FILE.format('HTML', 'zip')) from e
