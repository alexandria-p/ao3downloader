import datetime
import os
import re

from source_code import strings


def get_pinboard_url(api_token: str, date: datetime.datetime | None) -> str:
    """
    correctly formats a pinboard url to include an api token and (optionally) a timestamp, then returns it as a string
    """

    if date == None:
        return strings.ALL_POSTS_URL.format(api_token)
    else:
        year = str(date.year)
        month = str(date.month).zfill(2)
        day = str(date.day).zfill(2)
        timestamp = strings.TIMESTAMP_URL.format(year, month, day)
        return strings.POSTS_FROM_DATE_URL.format(api_token, timestamp)


def get_valid_filename(filename: list[str], maximum: int, suffix: str = '') -> str:
    """Create a valid filename path from a list of strings.

    `suffix` is appended to the last segment and is never truncated away: the segment is cut
    to leave room for it first. That is what keeps the date stamp on the end of every name,
    however long the title is.
    """

    segments = [get_valid_filepath(segment, maximum) for segment in filename]

    if suffix:
        # the last segment is the file name itself; anything before it is a folder. cut it
        # short enough that the suffix fits inside the same limit, then put the suffix back.
        room = max(1, maximum - len(suffix)) if maximum > 0 else 0
        last = get_valid_filepath(filename[-1], room) if filename else ''
        segments = segments[:-1] + [(last + suffix).strip()]

    valid_path = list(filter(lambda x: x, segments))
    if len(valid_path) == 0: return ''
    if len(valid_path) == 1: return valid_path[0]
    return os.path.join(*valid_path)


def get_valid_filepath(filename: str, maximum: int) -> str:
    """
    removes any invalid filename characters and leading/trailing whitespace from an input string
    the output will also be trimmed to the provided maximum amount of characters if maximum is greater than 0
    """

    valid_name = filename.translate({ord(i):None for i in strings.INVALID_FILENAME_CHARACTERS})
    if maximum == 0: return valid_name.strip()
    return valid_name[:maximum].strip()


def normalize_path_input(folder: str) -> str:
    """For file or folder path inputs. Strips enclosing quotes and leading and trailing whitespace."""
    if not folder:
        return folder
    folder = folder.strip()
    if len(folder) >= 2 and folder[0] == folder[-1] and folder[0] in ('"', "'"):
        folder = folder[1:-1].strip()
    return folder


def get_date_stamp(text: str) -> str:
    """An ao3 date turned into the YYYY-MM-DD stamp that goes in a file name.

    Ao3 writes dates two ways: a listing blurb says '14 Dec 2024', while a work page's
    status line is already '2024-12-14'. Anything that parses as neither gives back an
    empty string, which simply means the file gets no date on it rather than a wrong one.
    """

    # anything that is not text gets no date rather than an exception: a date is a nicety
    # on a file name, and must never be the reason a download fails
    if not isinstance(text, str): return ''
    value = text.strip()
    if not value: return ''

    # a status line can be prefixed, e.g. 'Updated: 2024-12-14'
    if ':' in value: value = value.split(':')[-1].strip()

    for pattern in ('%Y-%m-%d', '%d %b %Y', '%d %B %Y'):
        try:
            return datetime.datetime.strptime(value, pattern).strftime(strings.DATE_STAMP_FORMAT)
        except ValueError:
            continue
    return ''


def get_date_suffix(text: str) -> str:
    """The date stamp as it appears on the end of a file name, or nothing."""

    stamp = get_date_stamp(text)
    return ' ' + stamp if stamp else ''


def get_direct_download_link(work_number: str, filetype: str) -> str:
    """Where ao3 serves a work file, built from the work number alone.

    The usual route reads this link off the work page, which costs a request per work just
    to learn something the work number already determines. The segment after the number is
    a slug of the title that ao3 ignores, and the 'updated_at' query ao3 adds is only a
    cache-buster, so neither is needed.
    """

    return (f'{strings.AO3_DOWNLOAD_BASE_URL}/downloads/{work_number}/'
            f'{strings.AO3_DOWNLOAD_SLUG}{get_file_type(filetype)}')


def get_work_number_from_filename(name: str) -> str | None:
    """The ao3 work number a downloaded file's name starts with, or None.

    The same rule the web page uses: digits at the very start, followed by a separator, so
    a title that merely begins with digits is not mistaken for a work number. Keep this in
    step with workIdFromFilename in the gui's bookmarks.ts.
    """

    base = str(name or '').split('/')[-1].split('\\')[-1]
    match = re.match(r'^(\d+)(?:[\s_.\-]|$)', base)
    return match.group(1) if match else None


def get_date_from_filename(name: str) -> str | None:
    """The YYYY-MM-DD stamp a downloaded file carries, or None if it has none.

    Older files were saved before names carried a date. They are not out of date - there is
    simply nothing recorded about which version they are - so they come back as None rather
    than as an old date, and the caller decides what to do about that.
    """

    base = os.path.splitext(str(name or '').split('/')[-1].split('\\')[-1])[0]
    match = re.search(r'(\d{4}-\d{2}-\d{2})$', base.strip())
    return match.group(1) if match else None


def get_file_type(filetype: str) -> str:
    """
    creates a filename suffix string for an input (uppercase) filetype and returns it
    """

    return '.' + filetype.lower()


def get_work_number(link: str) -> str | None:
    """
    gets the work number from an ao3 work link
    """

    return get_digits_after('/works/', link)


def get_series_number(link: str) -> str | None:
    """
    gets the series number from an ao3 series link
    """

    return get_digits_after('/series/', link)


def get_collection_name(link: str) -> str | None:
    """The ao3 name of a collection, from a link to any of its pages.

    Accepts the dashboard, the profile, the works listing and so on, so a link pasted
    straight out of the address bar works. A user's own collections listing
    (/users/<name>/collections) is not one collection and returns None, as does the site
    wide /collections listing - neither has a name after /collections/.
    """

    if not link: return None
    match = re.search(r'/collections/([^/?#]+)', link)
    if not match: return None
    name = match.group(1).strip()
    # /collections/new is the form for making one, not a collection that exists
    return name if name and name.lower() != 'new' else None


def is_collection(link: str) -> bool:
    """
    checks if a link is for a single ao3 collection
    """

    return get_collection_name(link) != None


def is_work(link: str) -> bool:
    """
    checks if a link is for an ao3 work
    """

    return get_work_number(link) != None


def is_series(link: str) -> bool:
    """
    checks if a link is for an ao3 series
    """

    return get_series_number(link) != None


def is_subscriptions(link: str) -> bool:
    """
    checks if a link is for an ao3 subscriptions page.
    matches the url path regardless of username casing or query string.
    """

    path = link.split('?')[0].rstrip('/')
    return path.endswith('/subscriptions')


def get_digits_after(test: str, url: str) -> str | None:
    """
    retrieves all consecutive numerical digits in a url after a given test string.
    if the test string doesn't exist or there are no numbers found, the function returns None
    """

    index = str.find(url, test)
    #make sure that the test string is actually in our url
    if index == -1: return None
    digits = get_num_from_link(url, index + len(test))
    #check if we have a number to return
    if not digits or len(digits) == 0: return None
    return digits


def get_next_page(link: str) -> str:
    """
    increment the page number in an ao3 link, and return the updated url
    """

    index = str.find(link, 'page=')

    # if 'page=' isn't already in the link, we need to add it
    # we can assume that this means we're on the first page, and so we always add 'page=2'
    if index == -1:
        # if there's no querystring, add one with 'page=' as the first element
        if str.find(link, '?') == -1:
            newlink = link + '?page=2'
        # if the querystring already exists, add the 'page=' element at the end
        else:
            newlink = link + '&page=2'
    else:
        # we already have a 'page=' element, so we need to increment it by one
        i = index + 5
        page = get_num_from_link(link, i)
        nextpage = int(page) + 1
        newlink = link.replace('page=' + page, 'page=' + str(nextpage))
    return newlink


def set_page_number(link: str, page: int) -> str:
    """
    point an ao3 link at a particular page of a listing, and return the updated url
    """

    # ao3 serves the first page with no 'page=' element, so page 1 is the link as it stands
    if page <= 1: return link

    index = str.find(link, 'page=')
    if index == -1:
        separator = '&' if str.find(link, '?') != -1 else '?'
        return link + separator + 'page=' + str(page)

    current = get_num_from_link(link, index + 5)
    return link.replace('page=' + current, 'page=' + str(page))


def get_page_number(link: str) -> int:
    """
    gets the page number from an ao3 link and returns it as an int
    """

    index = str.find(link, 'page=')
    # there's no 'page=' element in the link, so we have to be on the first page
    if index == -1:
        return 1
    else:
        # our index starts after 'page=' so increment by five
        i = index + 5
        page = get_num_from_link(link, i)
        return int(page)


def get_num_from_link(link: str, start: int) -> str:
    """
    used to extract a number in a string that occurs after a specific start point
    """

    end = start
    #iterate through the string until we hit a non-digit character
    while end < len(link) and str.isdigit(link[start:end+1]):
        end = end + 1
    return link[start:end]


def get_count(text: str) -> int | None:
    """
    parses a stat count as displayed on ao3, for example '1,158,737', and returns it as an int.
    returns None if there is no number in the text. ao3 omits a stat entirely when it is zero,
    so a missing value is not the same thing as a value of zero and shouldn't be reported as one.
    """

    digits = re.sub(r'\D', '', text)
    return int(digits) if digits else None


def get_chapter_counts(text: str) -> tuple[int | None, int | None]:
    """
    parses the chapter count as displayed on ao3, for example '12/25' or '12/?',
    and returns it as a (published, total) tuple. total is None for a work in progress.
    """

    parts = ' '.join(text.split()).split('/')
    if len(parts) != 2: return get_count(text), None
    return get_count(parts[0]), get_count(parts[1])


def get_total_chapters(text: str, index: int) -> str:
    """
    read characters after index until encountering a space.
    """

    totalchap = ''
    for c in text[index+1:]:
        if c.isspace():
            break
        else:
            totalchap += c
    return totalchap


def get_current_chapters(text: str, index: int) -> str:
    """
    reverse text before index, then read characters from beginning of reversed text
    until encountering a space, then un-reverse the value you got.
    we assume here that the text does not include unicode values.
    this should be safe because ao3 doesn't have localization... I think.
    """

    currentchap = ''
    for c in reversed(text[:index]):
        if c.isspace():
            break
        else:
            currentchap += c
    currentchap = currentchap[::-1]
    return currentchap


def get_last_visited(text: str) -> str:
    """
    extracts the date from 'Last visited: 10 Jul 2026' text found on ao3 reading history pages.
    returns an empty string if no last visited date is found.
    """

    normalized = ' '.join(text.split())
    match = re.search(r'Last visited: (\d{1,2} \w{3} \d{4})', normalized)
    return match.group(1) if match else ''


def get_times_visited(text: str) -> str:
    """
    extracts the visit count from 'Visited 6 times' or 'Visited once' text found on ao3 reading history pages.
    returns an empty string if no visit count is found.
    """

    normalized = ' '.join(text.split())
    if 'Visited once' in normalized: return '1'
    match = re.search(r'Visited ([\d,]+) times', normalized)
    return match.group(1).replace(',', '') if match else ''


def get_payload(username: str, password: str, token: str) -> dict[str, str]:
    """
    constructs a payload for ao3 login.
    """

    payload = {
        'user[login]': username,
        'user[password]': password,
        'user[remember_me]': '1',
        'authenticity_token': token
    }
    return payload


def get_title_dict(logs: list[dict]) -> dict[str, list[str]]:
    """
    creates a dict of form [work link, [work title]] from the logfile
    this dict contains every unique work listed in the logs
    """

    dictionary = {}
    titles = filter(lambda x: 'title' in x and 'link' in x, logs)
    for obj in list(titles):
        link = obj['link']
        # make sure we don't include duplicates in our dict
        if link not in dictionary:
            title = obj['title']
            if not isinstance(title, list): title = [title]
            dictionary[link] = title
    return dictionary


def get_date_dict(logs: list[dict]) -> dict[str, str]:
    """The date suffix each logged work was last saved under, keyed by work link.

    Pairs with get_title_dict: together they rebuild the exact name a download was written
    as, which is what tells an existing file apart from a missing one.
    """

    dictionary = {}
    for obj in logs:
        link = obj.get('link')
        if not link or link in dictionary: continue
        if 'title' not in obj: continue
        dictionary[link] = get_date_suffix(obj.get('updated', ''))
    return dictionary


def get_unsuccessful_downloads(logs: list[dict]) -> list[str]:
    """
    checks the logs for any unsuccessful downloads
    if these exist, the function returns a list of links to those works (otherwise it returns an empty list)
    """

    links = []
    errors = filter(lambda x:'link' in x and 'success' in x and x['success'] == False, logs)
    for error in errors:
        link = error['link']
        # check if the work link is already in the list
        if link not in links: 
            links.append(link)
    return links
