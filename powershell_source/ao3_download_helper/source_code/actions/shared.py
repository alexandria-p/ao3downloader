import datetime
import os
import traceback

from source_code import exceptions, indexing, parse_text, strings
from source_code.fileio import FileOps
from source_code.repo import Repository


def series() -> bool:
    print(strings.AO3_PROMPT_SERIES)
    series = True if input() == strings.PROMPT_YES else False
    return series


def link(fileops: FileOps) -> str:
    link = get_last_page_downloaded(fileops)
    if not link: 
        print(strings.AO3_PROMPT_LINK)
        link = input()
    return link


def pages() -> int | None:
    print(strings.AO3_PROMPT_PAGES)
    pages = input()

    try:
        pages = int(pages)
        if pages <= 0:
            pages = None
    except:
        pages = None

    return pages


def images() -> bool:
    print(strings.AO3_PROMPT_IMAGES)
    images = True if input() == strings.PROMPT_YES else False
    return images


def links_only() -> bool:
    print(strings.PROMPT_LINKS_ONLY)
    return True if input() == strings.PROMPT_YES else False


def write_links_file(fileops: FileOps, urls: list[str], prefix: str) -> str:
    filename = f'{prefix}_{datetime.datetime.now().strftime("%m%d%Y%H%M%S")}.txt'
    path = os.path.join(fileops.downloadfolder, filename)
    with open(path, 'w') as f:
        for url in urls:
            f.write(url + '\n')
    return path


def metadata() -> bool:
    print(strings.AO3_PROMPT_METADATA)
    return True if input() == strings.PROMPT_YES else False


def metadata_work_dates() -> bool:
    print(strings.AO3_PROMPT_METADATA_WORK_DATES)
    return True if input() == strings.PROMPT_YES else False


def ignorelist_check_deleted() -> bool:
    print(strings.IGNORELIST_PROMPT_CHECK_DELETED)
    return True if input() == strings.PROMPT_YES else False


def visited(fileops: FileOps, filetypes: list[str]) -> list[str]:
    visited = []
    logs = fileops.load_logfile()
    if logs:
        print(strings.AO3_INFO_VISITED)
        titles = parse_text.get_title_dict(logs)
        # a downloaded work's name ends in the date it was updated on, so the stamp has to
        # be rebuilt too or every existing file would look like one that is missing
        suffixes = parse_text.get_date_dict(logs)
        maximum = fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        visited = list({x for x in titles if
            fileops.file_exists(x, titles, filetypes, maximum, suffixes)})
    if os.path.exists(strings.IGNORELIST_FILE_NAME):
        with open(strings.IGNORELIST_FILE_NAME, 'r', encoding='utf-8') as f: 
                visited.extend([x[:x.find('; ')] for x in f.readlines()])
    return visited


def pinboard_date() -> datetime.datetime | None:
    print(strings.PINBOARD_PROMPT_DATE)
    getdate = True if input() == strings.PROMPT_YES else False
    if getdate:
        date_format = 'mm/dd/yyyy'
        print(strings.PINBOARD_PROMPT_ENTER_DATE.format(date_format))
        inputdate = input()
        date = datetime.datetime.strptime(inputdate, '%m/%d/%Y')
    else:
        date = None
    return date


def pinboard_exclude() -> bool:
    print(strings.PINBOARD_PROMPT_INCLUDE_UNREAD)
    exclude_toread = False if input() == strings.PROMPT_YES else True
    return exclude_toread


def api_token(fileops: FileOps) -> str:
    return fileops.setting(
            strings.PINBOARD_PROMPT_API_TOKEN, 
            strings.SETTING_API_TOKEN)


def links_file() -> str:
    while True:
        print(strings.AO3_PROMPT_FILE_INPUT)
        path = parse_text.normalize_path_input(input())
        if os.path.exists(path):
            break
        else:
            print(strings.INFO_NO_FILE.format(path))
    return path


def redownload_folder() -> str:
    while True:
        print(strings.REDOWNLOAD_PROMPT_FOLDER)
        folder = parse_text.normalize_path_input(input())
        if os.path.isdir(folder):
            break
        else:
            print(strings.INFO_NO_FOLDER.format(folder))
    return folder


def redownload_oldtypes() -> list[str]:
    oldtypes = []
    while True:
        filetype = ''
        while filetype not in strings.UPDATE_ACCEPTABLE_FILE_TYPES:
            print(strings.REDOWNLOAD_PROMPT_FILE_TYPE)
            filetype = input()
        oldtypes.append(filetype)
        print(strings.REDOWNLOAD_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            oldtypes = list(set(oldtypes))
            break
    return oldtypes


def redownload_newtypes() -> list[str]:
    newtypes = []
    while True:
        filetype = ''
        while filetype not in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES:
            print(strings.AO3_PROMPT_DOWNLOAD_TYPE)
            filetype = input()
        newtypes.append(filetype)
        print(strings.AO3_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            newtypes = list(set(newtypes))
            break
    return newtypes


def marked_for_later_link(fileops: FileOps) -> str:
    username = fileops.get_setting(strings.SETTING_USERNAME)
    return f'{strings.AO3_BASE_URL}/users/{username}/readings?show=to-read'


def ao3_login(repo: Repository, fileops: FileOps, force: bool=False) -> None:

    if force:
        login = True
    else:
        print(strings.AO3_PROMPT_LOGIN)
        login = False if input() == strings.PROMPT_NO else True

    if login:
        savepassword = fileops.get_ini_value_boolean(strings.INI_PASSWORD_SAVE, False)
        passwordprompt = strings.AO3_PROMPT_PASSWORD_SAVE_TRUE if savepassword else strings.AO3_PROMPT_PASSWORD_SAVE_FALSE

        username = fileops.setting(
            strings.AO3_PROMPT_USERNAME,
            strings.SETTING_USERNAME)
        password = fileops.setting(
            strings.AO3_PROMPT_PASSWORD.format(passwordprompt),
            strings.SETTING_PASSWORD,
            savepassword, True)

        print(strings.AO3_INFO_LOGIN)
        try:
            repo.login(username, password)
        except exceptions.LoginException:
            fileops.save_setting(strings.SETTING_USERNAME, None)
            fileops.save_setting(strings.SETTING_PASSWORD, None)
            print(strings.MESSAGE_LOGIN_RESET)
            raise


def download_types(fileops: FileOps, allow_metadata: bool = False) -> list[str]:
    acceptable = strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA if allow_metadata else strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES
    prompt = strings.AO3_PROMPT_DOWNLOAD_TYPE_WITH_METADATA if allow_metadata else strings.AO3_PROMPT_DOWNLOAD_TYPE
    filetypes = fileops.get_setting(strings.SETTING_FILETYPES)
    if isinstance(filetypes, list):
        # the saved list is shared with actions that can't produce metadata, so drop
        # anything the action we're running now has no way to use
        filetypes = [x for x in filetypes if x in acceptable]
        if filetypes:
            print(strings.AO3_PROMPT_USE_SAVED_DOWNLOAD_TYPES)
            if input() == strings.PROMPT_YES: return filetypes
    filetypes = []
    while(True):
        filetype = ''
        while filetype not in acceptable:
            print(prompt)
            filetype = input()
        filetypes.append(filetype)
        print(strings.AO3_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            filetypes = list(set(filetypes))
            fileops.save_setting(strings.SETTING_FILETYPES, filetypes)
            return filetypes


def update_types(fileops: FileOps) -> list[str]:
    filetypes = fileops.get_setting(strings.SETTING_UPDATE_FILETYPES)
    if isinstance(filetypes, list):
        print(strings.UPDATE_PROMPT_USE_SAVED_FILE_TYPES)
        if input() == strings.PROMPT_YES: return filetypes
    filetypes = []
    while(True):
        filetype = ''
        while filetype not in strings.UPDATE_ACCEPTABLE_FILE_TYPES:
            print(strings.UPDATE_PROMPT_FILE_TYPE)
            filetype = input()
        filetypes.append(filetype)
        print(strings.UPDATE_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            filetypes = list(set(filetypes))
            fileops.save_setting(strings.SETTING_UPDATE_FILETYPES, filetypes)
            return filetypes


def update_folder(fileops: FileOps) -> str:
    saved = fileops.get_setting(strings.SETTING_UPDATE_FOLDER)
    if saved:
        normalized = parse_text.normalize_path_input(saved)
        if os.path.isdir(normalized):
            print(strings.UPDATE_PROMPT_USE_SAVED_FOLDER)
            if input() == strings.PROMPT_YES:
                return normalized
        else:
            print(strings.INFO_SAVED_FOLDER_MISSING.format(saved))
        fileops.save_setting(strings.SETTING_UPDATE_FOLDER, None)
    while True:
        print(strings.UPDATE_PROMPT_INPUT)
        folder = parse_text.normalize_path_input(input())
        if os.path.isdir(folder):
            fileops.save_setting(strings.SETTING_UPDATE_FOLDER, folder)
            return folder
        print(strings.INFO_NO_FOLDER.format(folder))


def get_files_of_type(folder: str, filetypes: list[str]) -> list[dict[str, str]]:
    print(strings.UPDATE_INFO_FILES)
    if not os.path.isdir(folder):
        print(strings.INFO_NO_FOLDER.format(folder))
        print(strings.UPDATE_INFO_NUM_RETURNED.format(0))
        return []
    results = []
    for subdir, dirs, files in os.walk(folder):
        for file in files:
            filetype = os.path.splitext(file)[1].upper()[1:]
            if filetype in filetypes:
                path = os.path.join(subdir, file)
                results.append({'path': path, 'filetype': filetype})
    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(results)))
    return results


def read_index(fileops: FileOps) -> list[dict]:
    """Every work the index describes, as the record it currently stands at.

    Reads downloads/indexing rather than the listing on ao3, so it costs no requests at
    all. A file that cannot be read is skipped rather than ending the run - one damaged
    json should not hide the rest of the library.
    """

    folder = os.path.join(fileops.downloadfolder, strings.INDEXING_FOLDER_NAME)
    records: list[dict] = []
    if not os.path.isdir(folder): return records

    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith('.json'): continue
        document = fileops.load_json(os.path.join(strings.INDEXING_FOLDER_NAME, name))
        record = indexing.flatten(document)
        if record and record.get('link'): records.append(record)

    return records


def indexed_work_ids(fileops: FileOps) -> set[str]:
    """The work numbers the index already holds, read from the file names alone.

    Deliberately does not parse the json. This answers one question - "have we seen this
    work before?" - for every blurb on every page of a listing, and an index of a few
    thousand fics would otherwise be read in full to answer it. The work number leads the
    file name by the same rule that pairs a download to its entry, so a directory listing
    is all it takes.
    """

    folder = os.path.join(fileops.downloadfolder, strings.INDEXING_FOLDER_NAME)
    if not os.path.isdir(folder): return set()

    found = set()
    for name in os.listdir(folder):
        if not name.lower().endswith('.json'): continue
        work = parse_text.get_work_number_from_filename(name)
        if work: found.add(work)
    return found


def incomplete_works(records: list[dict]) -> list[dict]:
    """The works the index last saw unfinished."""

    return [x for x in records if indexing.is_incomplete(x)]


def scan_downloaded_works(folder: str, filetypes: list[str]) -> dict[str, dict[str, dict]]:
    """Every downloaded work in the folder, by work number and then file type.

    Files are matched to a work by the number their name starts with - the same rule the
    web page uses - so this reads the folder as it actually is rather than trusting the log
    to describe it. The metadata folders are skipped: an index or collection file is not a
    downloaded work, and its name carries no date by design.

    Each entry is {'path': ..., 'date': 'YYYY-MM-DD' or None}. A date of None means the
    file was saved before names carried one, so which version it holds is unknown.
    """

    found: dict[str, dict[str, dict]] = {}
    if not folder or not os.path.isdir(folder): return found

    skip = {strings.INDEXING_FOLDER_NAME, strings.COLLECTIONS_FOLDER_NAME,
            strings.IMAGE_FOLDER_NAME, strings.RUNS_FOLDER_NAME}
    wanted = {x.upper() for x in filetypes}

    for subdir, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in skip]
        for file in files:
            filetype = os.path.splitext(file)[1].upper()[1:]
            if filetype not in wanted: continue
            work = parse_text.get_work_number_from_filename(file)
            if not work: continue

            entry = {'path': os.path.join(subdir, file),
                     'date': parse_text.get_date_from_filename(file)}
            existing = found.setdefault(work, {}).get(filetype)
            # more than one copy of the same type means an older one is still lying about;
            # the newest date is the one that counts, and an undated file is the oldest
            if existing is None or (entry['date'] or '') > (existing['date'] or ''):
                found[work][filetype] = entry

    return found


def stamp_undated_works(fileops: FileOps, existing: dict[str, dict[str, dict]],
                        works: set[str], stamp: str, maximum: int) -> dict:
    """Write a date onto the files that have none, by renaming them where they sit.

    This is the middle road between leaving files that predate dated names alone and
    fetching every one of them again: it says "treat what I have as the version from this
    date". Nothing is downloaded, nothing leaves the machine, and once the files carry a
    date the ordinary rule takes over - anything ao3 has updated since then is fetched
    again on this same run.

    `works` is the work numbers to touch, and is **not** optional. `existing` is the whole
    downloads folder, which is far more than any one run asked about - an update run asks
    about the couple of hundred fics the index calls unfinished, not the thousands of files
    sitting next to them. Renaming the lot was a real bug: the run reported a few hundred
    undated works and then dated every file in the library. Only what the caller asked
    about, and only in the types it scanned for, may be renamed here.

    `existing` is updated in place, so the caller can plan from it straight afterwards.

    Two things it will not do: overwrite a file that is already there, and lose characters
    without saying so. The base name is cut to leave room for the date, exactly as a fresh
    download would be, so a long name comes out shorter than it went in.
    """

    suffix = ' ' + stamp
    renamed = 0
    skipped = 0

    for work, types in existing.items():
        if work not in works: continue
        for filetype, entry in types.items():
            if entry['date'] is not None: continue

            old = entry['path']
            folder, name = os.path.split(old)
            base, extension = os.path.splitext(name)
            room = max(1, maximum - len(suffix)) if maximum > 0 else 0
            trimmed = base[:room].strip() if room else base.strip()
            new = os.path.join(folder, trimmed + suffix + extension)

            if os.path.exists(new):
                # something is already called that. renaming would destroy it
                skipped += 1
                continue
            if not fileops.rename_file(old, new):
                skipped += 1
                continue

            entry['path'] = new
            entry['date'] = stamp
            renamed += 1

    return {'renamed': renamed, 'skipped': skipped}


def plan_downloads(records: list[dict], existing: dict[str, dict[str, dict]],
                   filetypes: list[str], refresh_undated: bool = False,
                   overwrite: bool = False) -> dict:
    """Work out which already-downloaded works this run should fetch again.

    A work is out of date when ao3 says it was updated after the date on the file we hold.
    Works with no local copy are not listed here - they are downloaded anyway, by the usual
    'not visited yet' route.

    A file saved before names carried a date cannot be judged either way, so by default it
    is left alone and only counted. `refresh_undated` treats those as out of date too,
    which is what the ui's offer to refresh them does.

    `overwrite` replaces every copy of a requested type, however current it looks. Nothing
    here can see a file that is damaged or truncated - the name and the date are both right
    and only the bytes are wrong - so that judgement is the user's to make, and this is
    where their answer is applied. It is the one case where a copy the version check calls
    current is still fetched again.

    Returns the links to re-fetch, the links that are merely undated, and the exact file
    each download will replace - {link: {FILETYPE: path}} - so nothing is removed on a guess.
    """

    stale: list[str] = []
    undated: list[str] = []
    superseded: dict[str, dict[str, str]] = {}

    for record in records:
        work = record.get('id')
        link = record.get('link')
        if not work or not link: continue

        have = existing.get(str(work))
        if not have: continue

        current = parse_text.get_date_stamp(record.get('date_updated') or '')
        replacing: dict[str, str] = {}
        is_undated = False

        for filetype in filetypes:
            copy = have.get(filetype.upper())
            if not copy: continue
            if overwrite:
                replacing[filetype] = copy['path']
            elif copy['date'] is None:
                is_undated = True
                if refresh_undated: replacing[filetype] = copy['path']
            elif current and copy['date'] < current:
                replacing[filetype] = copy['path']

        if replacing:
            stale.append(link)
            superseded[link] = replacing
        elif is_undated:
            undated.append(link)

    return {'stale': stale, 'undated': undated, 'superseded': superseded}


def get_last_page_downloaded(fileops: FileOps) -> str | None:
    latest = None
    try:
        logs = fileops.load_logfile()
        starts = filter(lambda x: x and 'message' in x and x['message'] == strings.INFO_STARTING_PAGE, logs)
        if not starts: starts = filter(lambda x: 'starting' in x, logs) # backwards compatibility
        bydate = sorted(starts, key=lambda x: datetime.datetime.strptime(x['timestamp'], '%m/%d/%Y, %H:%M:%S'), reverse=True)
        if bydate: latest = bydate[0]
    except Exception as e:
        fileops.write_log({'error': str(e), 'message': strings.ERROR_LOG_FILE, 'stacktrace': traceback.format_exc()})

    link = None
    if latest:
        print(strings.AO3_PROMPT_LAST_PAGE)
        if input() == strings.PROMPT_YES:
            link = latest['link'] if 'link' in latest else latest['starting']

    return link
