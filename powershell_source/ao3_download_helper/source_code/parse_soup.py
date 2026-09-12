import copy
import re
import traceback
from typing import Any

from bs4 import BeautifulSoup, Comment, NavigableString, ResultSet, Tag

from source_code import parse_text, strings
from source_code.exceptions import DownloadException, ProceedException, SeriesLinkException


def get_work_link_html(soup: BeautifulSoup) -> str | None:
    msg = soup.select('#preface .message a')
    if msg and len(msg) == 2: # there should be exactly two links in here
        return str(msg[1].get('href')) # we want the second one
    return None


def get_stats_html(soup: BeautifulSoup) -> str | None:
    stats = soup.select('#preface .meta .tags dd')
    for dd in stats:
        if 'Chapters: ' in dd.text:
            return dd.text
    return None


def get_series_html(soup: BeautifulSoup) -> list[str]:
    series = []
    links = soup.select('#preface .meta .tags dd a')
    for link in links:
        href = link.get('href')
        if href and 'archiveofourown.org/series/' in href:
            series.append(href)
    return series


def get_work_link_mobi(soup: BeautifulSoup) -> str | None:
    # it's ok if there are other work links in the file, because the relevant one will always be the first to appear
    # can't use a more specific selector because the html that comes out of the mobi parser is poorly formatted rip me
    link = soup.find('a', href=lambda x: bool(x and 'archiveofourown.org/works/' in x))
    if link and isinstance(link, Tag): return str(link.get('href'))
    return None


def get_stats_mobi(soup: BeautifulSoup) -> str | None:
    stats = soup.find('blockquote', string=lambda x: bool(x and 'Chapters: ' in x))
    if stats: return stats.text
    return None


def get_series_mobi(soup: BeautifulSoup) -> list[str]:
    series = []
    tag = soup.find('p', string=lambda x: bool(x and x == 'Series:'))
    if tag:
        block = tag.find_next_sibling('blockquote')
        if block and isinstance(block, Tag):
            links = block.find_all('a', href=lambda x: bool(x and 'archiveofourown.org/series/' in x))
            for link in links:
                if isinstance(link, Tag):
                    href = link.get('href')
                    if href: series.append(str(href))
    return series


def get_login_token(soup: BeautifulSoup) -> str:
    """Get authentication token for logging in to ao3."""

    form = soup.find('form', id='new_user')
    if not form or not isinstance(form, Tag):
        title = soup.title.string if soup.title else 'undefined'
        raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_FORM.format(title)))
    
    field = form.find('input', attrs={'name': 'authenticity_token'})
    if not field or not isinstance(field, Tag):
        raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_TOKEN))
    
    token = field.get('value')

    if not token:
        raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_TOKEN_VALUE))

    return str(token)


def get_mark_read_token(soup: BeautifulSoup) -> str | None:
    """Get token for marking a work as read."""

    actions = soup.find('ul', class_='work navigation actions')
    if not actions or not isinstance(actions, Tag): return None

    mark_read = actions.find('li', class_='mark')
    if not mark_read or not isinstance(mark_read, Tag): return None

    form = mark_read.find('form')
    if not form or not isinstance(form, Tag): return None

    field = form.find('input', attrs={'name': 'authenticity_token'})
    if not field or not isinstance(field, Tag): return None

    token = field.get('value')
    return str(token)


def get_image_links(soup: BeautifulSoup) -> list[str]:
    links = []
    work = soup.find('div', id='workskin')
    if not work or not isinstance(work, Tag): return links
    images = work.find_all('img')
    for img in images:
        if isinstance(img, Tag):
            href = img.get('src')
            if href:
                links.append(href)
    return links


def get_work_urls(soup: BeautifulSoup) -> list[str]:
    """Get all links to ao3 works on a page"""

    work_urls: list[str] = []
    for anchor in soup.select('.index.group a'):
        href = anchor.get('href')
        if not href:
            continue
        href_text = str(href)
        if not parse_text.is_work(href_text):
            continue
        full_url = get_full_work_url(href_text)
        if full_url:
            work_urls.append(full_url)

    return list(dict.fromkeys(work_urls))


def get_full_work_url(url: str) -> str | None:
    """Get full ao3 work url from partial url"""

    work_number = parse_text.get_work_number(url)
    return strings.AO3_BASE_URL + '/works/' + work_number if work_number else None


def get_series_urls(soup: BeautifulSoup, get_all: bool) -> list[str]:
    """Get all links to ao3 series on a page"""

    bookmarks = None if get_all else soup.find_all('li', class_='bookmark')

    series_urls: list[str] = []
    for anchor in soup.select('.index.group a'):
        href = anchor.get('href')
        if not href:
            continue
        href_text = str(href)
        if not is_series(href_text, get_all, bookmarks):
            continue
        full_url = get_full_series_url(href_text)
        if full_url:
            series_urls.append(full_url)

    return list(dict.fromkeys(series_urls))


def is_series(element: str, get_all: bool, bookmarks: ResultSet[Any] | None) -> bool:

    series_number = parse_text.get_series_number(element)

    # it's not a series at all, so return false
    if not series_number: return False

    # it is a series and we want all of them, so return true
    if get_all: return True

    # check the bookmarks list to see if this is a series, and return true if it is
    if not bookmarks:
        return False

    return any(
        f'series-{series_number}' in (bookmark.get('class') or [])
        for bookmark in bookmarks
    )


def get_full_series_url(url: str) -> str | None:
    """Get full ao3 series url from partial url"""

    series_number = parse_text.get_series_number(url)
    return strings.AO3_BASE_URL + '/series/' + series_number if series_number else None


def get_work_and_series_urls(soup: BeautifulSoup, get_all: bool=False) -> list[str]:
    """Get all links to ao3 works or series on a page"""

    work_urls = get_work_urls(soup)
    series_urls = get_series_urls(soup, get_all)
    return work_urls + series_urls


def get_total_pages(soup: BeautifulSoup) -> int | None:
    """Get total page count from pagination element, or None if no pagination exists."""

    pagination = soup.select_one('ol.pagination')
    if not pagination:
        return None
    page_numbers = []
    for li in pagination.find_all('li'):
        digits = re.sub(r'\D', '', li.get_text())
        if not digits:
            continue # ignore non-numeric ('previous' and 'next')
        page_numbers.append(int(digits))
    return max(page_numbers) if page_numbers else None


def get_proceed_link(soup: BeautifulSoup) -> str:
    """Get link to proceed through explicit work agreement."""

    link = None
    for anchor in soup.select('div.works-show.region ul.actions li a'):
        if anchor.get_text(strip=True) == strings.AO3_PROCEED:
            link = anchor.get('href')
            break
    if not link: raise ProceedException(strings.ERROR_PROCEED_LINK)
    return strings.AO3_BASE_URL + str(link)


def get_download_link(soup: BeautifulSoup, download_type: str) -> str:
    """Get download link from ao3 work page."""

    link = None
    for anchor in soup.select('li.download a'):
        if anchor.get_text(strip=True) == download_type:
            link = anchor.get('href')
            break
    if not link: raise DownloadException(strings.ERROR_DOWNLOAD_LINK)
    return strings.AO3_BASE_URL + str(link)


def has_custom_skin(soup: BeautifulSoup) -> bool:
    """Check if a work has custom creator styles"""

    return bool(soup.select('ul.work.navigation.actions li.style'))


def get_title(soup: BeautifulSoup, link: str, pattern: str) -> list[str]:
    """Get (non-truncated) filename for the work"""

    return apply_name_pattern(get_work_metadata_from_work(soup, link), pattern)


def get_work_stats(soup: BeautifulSoup) -> dict:
    """What a work's own page can say about a fic that its index entry already records.

    Deliberately a subset. A work page and a listing blurb describe a fic differently, and
    writing the whole of one into a record shaped by the other would make every field look
    changed and fill the history with schema noise. These are the fields that actually move
    when a fic is updated, and they are read with the same helpers the blurb parser uses,
    so they come out in the same shape.

    Tags, summary, warnings and the bookmark's own fields are not here: the listing is
    where those come from, and a bookmarks pass is what refreshes them.
    """

    stats: dict[str, Any] = {}
    try:
        published, total = parse_text.get_chapter_counts(
            get_text_or_empty(soup, 'dd.chapters'))
        stats['chapters_published'] = published
        stats['chapters_total'] = total # None for a work in progress, shown by ao3 as '?'
        stats['words'] = parse_text.get_count(get_text_or_empty(soup, 'dd.words'))
        # ao3 leaves a stat out entirely when it is zero, so these stay None rather than 0
        stats['comments'] = parse_text.get_count(get_text_or_empty(soup, 'dd.comments'))
        stats['kudos'] = parse_text.get_count(get_text_or_empty(soup, 'dd.kudos'))
        stats['bookmarks'] = parse_text.get_count(get_text_or_empty(soup, 'dd.bookmarks'))
        stats['hits'] = parse_text.get_count(get_text_or_empty(soup, 'dd.hits'))
        # written the way a listing writes it, or the two passes would rewrite each other
        stats['date_updated'] = parse_text.get_listing_date(get_updated_date(soup))
    except Exception as e:
        stats['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return stats


def get_updated_date(soup: BeautifulSoup) -> str:
    """The date a work page says it was last updated on.

    A single-chapter work has no status line, in which case the publication date is the
    only date it has and is the one that identifies the version.
    """

    return get_text_or_empty(soup, 'dd.status') or get_text_or_empty(soup, 'dd.published')


def apply_name_pattern(metadata: dict, pattern: str) -> list[str]:
    """Fill the configured file name pattern in from work metadata.

    A '/' in the pattern separates directory names, so the result is one string per
    path segment.
    """

    result = []

    for part in pattern.split('/'):
        part_result = part
        for key, value in metadata.items():
            part_result = part_result.replace(f'{{{key}}}', value)
        result.append(part_result)

    return result


def get_name_metadata_from_blurb(record: dict) -> dict:
    """The file name pattern fields, taken from an exported blurb record.

    Same keys as get_work_metadata_from_work so the pattern behaves the same way for a
    metadata export as it does for a download. The fields a listing page doesn't carry
    are empty rather than missing, so a pattern using one of them still resolves.
    """

    tags = record.get('tags') or {}

    def joined(values) -> str:
        return ', '.join(values or [])

    def number(value) -> str:
        return '' if value is None else str(value)

    return {
        'worknum': record.get('id') or '',
        'title': record.get('title') or '',
        'author': joined(record.get('authors')),
        'fandom': joined(record.get('fandoms')),
        'pairing': joined(tags.get('relationships')),
        'rating': tags.get('rating') or '',
        'warning': joined(record.get('warnings')),
        'category': joined(tags.get('categories')),
        'words': number(record.get('words')),
        'chapters': number(record.get('chapters_published')),
        'published': record.get('date_created') or '',
        'updated': record.get('date_updated') or '',
        # a listing page carries none of these
        'language': '',
        'series_title': '',
        'series_index': '',
    }


def get_work_metadata_from_work(soup: BeautifulSoup, link: str) -> dict:
    metadata = {}
    metadata['worknum'] = parse_text.get_work_number(link)
    metadata['title'] = get_text_or_empty(soup, '.preface .title')
    metadata['author'] = get_text_or_empty(soup, '.preface .byline')
    metadata['fandom'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.fandom a'))))
    metadata['pairing'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.relationship a'))))
    metadata['rating'] = get_text_or_empty(soup, 'dd.rating')
    metadata['warning'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.warning a'))))
    metadata['category'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.category a'))))
    metadata['words'] = get_text_or_empty(soup, 'dd.words').replace(',', '').strip()
    metadata['chapters'] = get_current_chapters(soup)
    metadata['language'] = get_text_or_empty(soup, 'dd.language')
    metadata['published'] = get_text_or_empty(soup, 'dd.published')
    metadata['updated'] = get_text_or_empty(soup, 'dd.status')
    series_list = list(map(lambda x: get_series_from_span(x), soup.select('dd.series span.series span.position')))
    metadata['series_title'] = str.join(', ', list(map(lambda x: x[0], series_list)))
    metadata['series_index'] = str.join(', ', list(map(lambda x: x[1], series_list)))
    return metadata


def get_text_or_empty(soup: BeautifulSoup | Tag, selector: str) -> str:
    """Get text from a selector, or return an empty string if it doesn't exist"""

    try:
        return soup.select(selector)[0].get_text().strip()
    except:
        return ''


def get_series_from_span(tag: Tag) -> tuple[str, str]:
    """Get series title and index from span element"""

    series_link = tag.find('a')
    if not series_link: raise SeriesLinkException(strings.ERROR_SERIES_LINK)
    series_title = series_link.get_text().strip()
    work_index = re.sub(r'\D', '', tag.decode_contents().replace(str(series_link), '')).strip()
    return series_title, work_index


def get_work_metadata_from_list(soup: BeautifulSoup, link: str) -> dict:
    metadata = {}
    try:
        worknum = parse_text.get_work_number(link)
        blurb = soup.find('li', class_=f'work-{worknum}')
        if not isinstance(blurb, Tag):
            metadata['error'] = strings.ERROR_WORK_BLURB
            return metadata
        metadata['title'] = blurb.select('h4.heading a')[0].get_text()
        metadata['author'] = str.join(', ', list(x.get_text() for x in blurb.find_all('a', rel='author')))
        if not metadata['author']: metadata['author'] = 'Anonymous'
        summary = blurb.find('blockquote', class_='summary')
        if isinstance(summary, Tag):
            metadata['summary'] = summary.decode_contents()
        else:
            metadata['summary'] = '' # some works don't have a summary
        metadata['fandoms'] = [x.get_text() for x in blurb.select('h5.fandoms a')]
        metadata['warnings'] = [x.get_text() for x in blurb.select('li.warnings a')]
        metadata['characters'] = [x.get_text() for x in blurb.select('li.characters a')]
        metadata['relationships'] = [x.get_text() for x in blurb.select('li.relationships a')]
        metadata['tags'] = [x.get_text() for x in blurb.select('li.freeforms a')]
        metadata['words'] = get_text_or_empty(blurb, 'dd.words')
        metadata['rating'] = get_text_or_empty(blurb, 'span.rating')
        metadata['chapters'] = get_text_or_empty(blurb, 'dd.chapters')
        metadata['categories'] = get_text_or_empty(blurb, 'span.category')
        metadata['complete'] = get_text_or_empty(blurb, 'span.iswip') == 'Complete Work'
        metadata['series'] = [' '.join(x.get_text().split()) for x in blurb.select('ul[class="series"] li')]
        metadata['updated'] = get_text_or_empty(blurb, 'div.header p.datetime')
        metadata['date_bookmarked'] = get_text_or_empty(blurb, 'div.user p.datetime')
        metadata['bookmarker_tags'] = [x.get_text() for x in blurb.select('div.user ul.meta.tags a.tag')]
        notes = blurb.select_one('div.user blockquote.notes')
        metadata['bookmarker_notes'] = notes.decode_contents() if notes else ''
        viewed = get_text_or_empty(blurb, 'div.user h4.viewed')
        metadata['last_visited'] = parse_text.get_last_visited(viewed)
        metadata['times_visited'] = parse_text.get_times_visited(viewed)
    except Exception as e: # don't crash the entire download if there is an unhandled exception
        metadata['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return metadata


def get_collection_blurbs(soup: BeautifulSoup) -> list[Tag]:
    """Every collection blurb on a collections listing page."""

    blurbs = soup.select('li.collection.blurb')
    if not blurbs:
        # a listing that styles its blurbs differently still links to /collections/
        blurbs = [x for x in soup.select('li.blurb')
                  if x.select_one('h4.heading a[href*="/collections/"]')]
    return [x for x in blurbs if isinstance(x, Tag)]


def get_collection_slug(blurb: Tag) -> str | None:
    """The short name a collection's urls are built from, e.g. 'Best_of_Hollanov_MS'."""

    link = blurb.select_one('h4.heading a[href*="/collections/"]')
    if not link: return None
    match = re.search(r'/collections/([^/?#]+)', str(link.get('href') or ''))
    return match.group(1) if match else None


def get_collection_flags(blurb: Tag) -> list[str]:
    """The parenthesised list ao3 shows under a collection, split into its parts.

    Renders as '(Closed, Moderated)', or for a challenge as
    '(Prompt Meme Challenge, Moderated)'. Kept whole as well as read for known flags, so
    anything ao3 adds later is still captured.
    """

    text = get_text_or_empty(blurb, 'p.type').strip()
    if text.startswith('(') and text.endswith(')'): text = text[1:-1]
    return [part.strip() for part in text.split(',') if part.strip()]


def get_flag_fields(flags: list[str]) -> dict:
    """The known flags, read out of the parenthesised list.

    Membership is exact rather than substring: ao3 writes 'Unmoderated' as well as
    'Moderated', and a substring test would read the first as the second.
    """

    return {
        'flags': flags,
        'closed': 'Closed' in flags,
        'moderated': 'Moderated' in flags,
        'unrevealed': 'Unrevealed' in flags,
        'anonymous': 'Anonymous' in flags,
        # a challenge collection names its type among the flags; anything else has none
        'challenge_type': next((x for x in flags if x.endswith('Challenge')), None)
                          or 'No Challenge',
    }


def get_collection_header(soup: BeautifulSoup) -> dict:
    """What a collection's own page says about itself, with no listing blurb to read.

    Indexing a collection by url has no listing behind it, so the three things a blurb
    would have supplied - the display title, the description, and the parenthesised flags -
    are taken from the profile page instead, which carries all of them.
    """

    header: dict[str, Any] = {}
    try:
        header['title'] = get_text_or_empty(soup, '#main h2.heading')
        summary = soup.select_one('#main blockquote.userstuff')
        header['description'] = get_userstuff_text(summary) if summary else ''
        header.update(get_flag_fields(get_collection_flags(soup)))
    except Exception as e: # a header we cannot read should not lose the collection
        header['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return header


def get_collection_metadata(blurb: Tag) -> dict:
    """What a collections listing says about one collection.

    Ao3 does not put a collection's tags or fandoms on this page, and multifandom is a
    search filter rather than something a collection declares, so neither is here.
    """

    metadata: dict[str, Any] = {}
    try:
        slug = get_collection_slug(blurb)
        metadata['name'] = slug
        metadata['link'] = f'{strings.AO3_BASE_URL}/collections/{slug}' if slug else None
        metadata['title'] = get_text_or_empty(blurb, 'h4.heading a')
        metadata['maintainers'] = [x.get_text().strip() for x in blurb.select('a.owner')]

        summary = blurb.select_one('blockquote.userstuff.summary')
        metadata['description'] = get_userstuff_text(summary) if summary else ''

        metadata.update(get_flag_fields(get_collection_flags(blurb)))

        metadata['created'] = get_text_or_empty(blurb, 'p.datetime')
        metadata['work_count'] = parse_text.get_count(get_text_or_empty(blurb, 'dd.works'))
        metadata['bookmark_count'] = parse_text.get_count(
            get_text_or_empty(blurb, 'dd.bookmarks'))
    except Exception as e: # don't lose the rest of the page over one unparseable blurb
        metadata['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return metadata


def get_collection_sidebar(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Every collection link in a collection's dashboard sidebar, as (label, href).

    Ao3 splits that sidebar across several navigation lists rather than one, so they are
    all gathered - taking only the first misses Fandoms, Works and Bookmarked Items.
    """

    links = []
    for nav in soup.select('ul.navigation.actions'):
        for anchor in nav.find_all('a'):
            href = str(anchor.get('href') or '')
            # '/collections/' with the slash excludes the site-wide Collections menu item
            if '/collections/' not in href: continue
            links.append((' '.join(anchor.get_text().split()), href))
    return links


def get_sidebar_count(label: str) -> int | None:
    """The number ao3 puts in a sidebar label, as in 'Fandoms (1193)'."""

    match = re.search(r'\((\d[\d,]*)\)', label)
    return parse_text.get_count(match.group(1)) if match else None


def get_collection_profile(soup: BeautifulSoup) -> dict:
    """What a collection's profile page adds to what its listing blurb already said.

    The meta list here is malformed - ao3 never closes the first <dt>, so everything
    after it ends up nested inside. Pairing on document order rather than siblings is
    what makes this work.
    """

    profile: dict[str, Any] = {}
    try:
        pairs = {}
        meta = soup.select_one('#main dl.meta')
        if meta:
            for term in meta.find_all('dt'):
                # only the term's own text: its children are the rest of the list.
                # comments are strings to beautifulsoup, and ao3 puts one inside the
                # first term on a challenge collection, so they are dropped here.
                label = ''.join(x for x in term.find_all(string=True, recursive=False)
                                if isinstance(x, NavigableString) and not isinstance(x, Comment))
                label = ' '.join(label.split()).rstrip(':').strip().lower()
                value = term.find_next('dd')
                if label and value is not None and label not in pairs:
                    pairs[label] = value

        profile['active_since'] = ' '.join(pairs['active since'].get_text().split()) \
            if 'active since' in pairs else ''
        profile['tags'] = [x.get_text().strip()
                           for x in pairs['collection tags'].select('a.tag')] \
            if 'collection tags' in pairs else []
        profile['maintainers'] = [x.get_text().strip()
                                  for x in soup.select('#main dd.maintainers a')]

        sidebar = get_collection_sidebar(soup)
        profile['parent_collection'] = next(
            (full_url(href) for label, href in sidebar if label == 'Parent Collection'), None)
        profile['subcollections_link'] = next(
            (full_url(href) for label, href in sidebar
             if label.startswith('Subcollections')), None)

        counts = {label.split(' (')[0]: get_sidebar_count(label) for label, _ in sidebar}
        profile['fandom_count'] = counts.get('Fandoms')
        profile['work_count'] = counts.get('Works')
        profile['bookmark_count'] = counts.get('Bookmarked Items')
        profile['subcollection_count'] = counts.get('Subcollections')

        # more than one fandom is what makes a collection multifandom
        fandoms = profile['fandom_count']
        profile['multifandom'] = fandoms > 1 if fandoms is not None else None

        profile['challenge_type'] = get_challenge_type(pairs, counts)
    except Exception as e: # a profile we cannot read should not lose the collection
        profile['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return profile


def get_challenge_type(pairs: dict, counts: dict) -> str:
    """Which kind of challenge a collection runs, judged by what its profile shows.

    A prompt meme has prompts; a gift exchange has a tag set and assignments. A
    collection that is not a challenge has neither.
    """

    if 'Prompts' in counts: return 'Prompt Meme Challenge'
    if 'tag set' in pairs or 'assignments due' in pairs: return 'Gift Exchange Challenge'
    return 'No Challenge'


def full_url(href: str) -> str:
    """Make an ao3 link absolute, leaving one that already is alone."""

    if href.startswith('http'): return href
    return strings.AO3_BASE_URL + href


def get_blurbs(soup: BeautifulSoup) -> list[Tag]:
    """Get every work/bookmark blurb element from an ao3 listing page."""

    blurbs = soup.select('ol.index.group > li.blurb')
    if not blurbs: blurbs = soup.select('li.blurb')
    return [x for x in blurbs if isinstance(x, Tag)]


def get_blurb_id(blurb: Tag) -> str | None:
    """Get the id attribute of a blurb, which uniquely identifies the bookmark it belongs to."""

    blurb_id = blurb.get('id')
    return str(blurb_id) if blurb_id else None


def get_blurb_work_number(blurb: Tag) -> str | None:
    """Get the work number from a blurb, or None if the blurb isn't for a work.
    Bookmarks of series, external works, and deleted works all return None."""

    classes = blurb.get('class') or []
    if not isinstance(classes, list): classes = [str(classes)]
    for classname in classes:
        if str(classname).startswith('work-'):
            worknum = str(classname)[len('work-'):]
            if worknum.isdigit(): return worknum

    # not every listing puts the work number in the class list, so fall back to the title link
    heading = blurb.select_one('h4.heading a')
    if heading:
        href = heading.get('href')
        if href: return parse_text.get_work_number(str(href))

    return None


def get_blurb_skip_reason(blurb: Tag) -> dict:
    """Why a bookmark has no work number, as far as the listing is willing to say.

    A bookmarks listing holds more than works: bookmarks of series, of works hosted
    somewhere else entirely, and of works that have since been deleted or hidden. None of
    those has a work number, so none can be indexed or downloaded - and a count on its own
    leaves no way to tell which bookmark was passed over or to go and look at it.

    Returns the same `{id, link, error}` shape a failed download does, so both lists render
    and export the same way. The reason is what the page shows, not a guess dressed up as
    one: when the listing does not say, it says that it does not say.
    """

    heading = blurb.select_one('h4.heading a')
    href = str(heading.get('href') or '') if heading else ''
    title = get_text_or_empty(blurb, 'h4.heading a') or get_text_or_empty(blurb, 'h4.heading')

    series = parse_text.get_series_number(href)
    if series:
        return {'id': series, 'link': full_url(href), 'title': title,
                'error': strings.SKIPPED_SERIES}

    if href.startswith('http') and strings.AO3_DOMAIN not in href.lower():
        return {'id': None, 'link': href, 'title': title, 'error': strings.SKIPPED_EXTERNAL}

    # when ao3 will say why, it says so in a `p.message` where the work would have been, and
    # the blurb is otherwise empty - no heading, no link, nothing. checked against a real
    # listing: a deleted work renders exactly this way and nothing else does.
    message = get_text_or_empty(blurb, 'p.message').strip()
    if message:
        lowered = message.lower()
        if 'deleted' in lowered: reason = strings.SKIPPED_DELETED
        elif 'private' in lowered: reason = strings.SKIPPED_PRIVATE
        # ao3's own words beat anything invented here, for a message not seen before
        else: reason = message
        return {'id': None, 'link': '', 'title': title, 'error': reason}

    return {'id': None, 'link': full_url(href) if href else '', 'title': title,
            'error': strings.SKIPPED_UNKNOWN}


def is_unrevealed_blurb(blurb: Tag) -> bool:
    """Whether a blurb is a work that exists but cannot be read yet.

    A work in an unrevealed collection shows as 'Mystery Work' with **no link on its
    title** - ao3 will not say which work it is until the collection opens. The catch is
    that the blurb still carries the `work-<id>` class, so it has a work number and is
    indexed like any other; only the download is impossible.

    Checked against a real listing and against the bookmarks fixture: every ordinary work
    blurb carries both a work number and a title link, and the only blurbs with a number
    but no link are these. So the absence of the link is the test - not the words 'Mystery
    Work', which are ao3's wording of the day rather than a structure.
    """

    if not get_blurb_work_number(blurb): return False
    return blurb.select_one('h4.heading a[href*="/works/"]') is None


def get_blurb_metadata(blurb: Tag) -> dict:
    """Get work metadata, and the bookmarker's own data where it exists, from a single blurb.

    Everything here comes off the listing page itself, so a whole page of works costs one
    request. The one thing a listing doesn't carry is the original publication date, which
    is why 'date_created' starts out as None - see Ao3.add_work_dates.
    """

    metadata: dict[str, Any] = {}
    try:
        worknum = get_blurb_work_number(blurb)
        metadata['id'] = worknum
        metadata['link'] = get_full_work_url('/works/' + worknum) if worknum else None
        metadata['title'] = get_text_or_empty(blurb, 'h4.heading a')
        metadata['authors'] = [x.get_text().strip() for x in blurb.find_all('a', rel='author')]
        if not metadata['authors']: metadata['authors'] = ['Anonymous']
        metadata['date_created'] = None # not available on listing pages
        metadata['date_updated'] = get_text_or_empty(blurb, 'div.header p.datetime')
        metadata['fandoms'] = [x.get_text().strip() for x in blurb.select('h5.fandoms a')]
        metadata['warnings'] = [x.get_text().strip() for x in blurb.select('li.warnings a')]
        metadata['tags'] = {
            'rating': get_text_or_empty(blurb, 'span.rating'),
            'categories': [x.strip() for x in get_text_or_empty(blurb, 'span.category').split(',') if x.strip()],
            'relationships': [x.get_text().strip() for x in blurb.select('li.relationships a')],
            'characters': [x.get_text().strip() for x in blurb.select('li.characters a')],
            'additional': [x.get_text().strip() for x in blurb.select('li.freeforms a')],
        }
        summary = blurb.select_one('blockquote.summary')
        metadata['summary'] = get_userstuff_text(summary) if summary else '' # some works don't have a summary
        metadata['words'] = parse_text.get_count(get_text_or_empty(blurb, 'dd.words'))
        published, total = parse_text.get_chapter_counts(get_text_or_empty(blurb, 'dd.chapters'))
        metadata['chapters_published'] = published
        metadata['chapters_total'] = total # None for a work in progress, which ao3 displays as '?'
        # ao3 leaves a stat out of the blurb entirely when it is zero, so these stay None
        # rather than 0 - a missing count isn't the same claim as a count of nothing.
        metadata['comments'] = parse_text.get_count(get_text_or_empty(blurb, 'dd.comments'))
        metadata['kudos'] = parse_text.get_count(get_text_or_empty(blurb, 'dd.kudos'))
        metadata['bookmarks'] = parse_text.get_count(get_text_or_empty(blurb, 'dd.bookmarks'))
        metadata['hits'] = parse_text.get_count(get_text_or_empty(blurb, 'dd.hits'))
        metadata.update(get_bookmark_metadata(blurb))
    except Exception as e: # don't lose the rest of the page over one unparseable blurb
        metadata['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return metadata


def get_bookmark_metadata(blurb: Tag) -> dict:
    """Get the bookmarker's own data from a blurb. A blurb from a listing that isn't a
    bookmarks page has none of this, in which case the fields come back empty."""

    metadata: dict[str, Any] = {}
    metadata['date_bookmarked'] = get_text_or_empty(blurb, 'div.user p.datetime')
    notes = blurb.select_one('div.user blockquote.notes')
    metadata['bookmark_notes'] = get_userstuff_text(notes) if notes else ''
    metadata['bookmark_tags'] = [x.get_text().strip() for x in blurb.select('div.user ul.meta.tags a.tag')]
    metadata['bookmark_collections'] = [x.get_text().strip() for x in blurb.select('div.user a[href*="/collections/"]')]
    status = blurb.select_one('p.status')
    metadata['bookmark_private'] = has_bookmark_symbol(status, 'private', 'Private Bookmark')
    metadata['bookmark_rec'] = has_bookmark_symbol(status, 'rec', 'Rec')
    return metadata


def get_userstuff_text(tag: Tag) -> str:
    """Plain text of a userstuff block (a summary or a bookmark note).

    Breaks on paragraphs and line breaks only. Splitting on every string node instead
    would put a break in the middle of any sentence containing inline markup, turning
    'It <em>is</em> the first time' into three lines.
    """

    working = copy.copy(tag)
    for linebreak in working.find_all('br'):
        linebreak.replace_with('\n')

    blocks = working.find_all(['p', 'div'], recursive=False)
    parts = [x.get_text() for x in blocks] if blocks else [working.get_text()]

    lines = []
    for part in parts:
        for line in part.split('\n'):
            line = ' '.join(line.split())
            if line: lines.append(line)
    return '\n'.join(lines)


def has_bookmark_symbol(status: Tag | None, classname: str, title: str) -> bool:
    """Check the bookmark symbols block for one of ao3's status icons.
    Checks the title as well as the class, so a css rename doesn't silently flip these to false."""

    if not status: return False
    if status.select_one('span.' + classname): return True
    return status.find('span', title=title) is not None


def get_current_chapters(soup: BeautifulSoup) -> str:
    chapters = list(soup.select('dl.stats dd.chapters'))
    if not chapters: return '-1'
    text = chapters[0].get_text().strip()
    index = text.find('/')
    if index == -1: return '-1'
    return parse_text.get_current_chapters(text, index)


def is_locked(soup: BeautifulSoup) -> bool:
    return soup.find('div', id='main', class_='sessions-new') is not None


def is_deleted(soup: BeautifulSoup) -> bool:
    return soup.find('div', id='main', class_='error-404') is not None


def is_hidden(soup: BeautifulSoup) -> bool:
    notice = soup.find('p', class_='notice')
    if not notice or not isinstance(notice, Tag):
        return False
    return notice.find('a', href=lambda x: bool(x and x.startswith('/collections/'))) is not None


def is_explicit(soup: BeautifulSoup) -> bool:
    return soup.find('p', class_='caution') is not None


def is_logged_in(soup: BeautifulSoup) -> bool:
    return soup.find('body', class_='logged-in') is not None
