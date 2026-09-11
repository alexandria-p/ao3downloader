# region file ops

# based on https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file#naming-conventions
INVALID_FILENAME_CHARACTERS = r'<>:"/\|?*.' + ''.join(chr(i) for i in range(32))
TIMESTAMP_FORMAT = '%m/%d/%Y, %H:%M:%S'

DOWNLOAD_FOLDER_NAME = 'downloads'
IMAGE_FOLDER_NAME = 'images'
INDEXING_FOLDER_NAME = 'indexing'
COLLECTIONS_FOLDER_NAME = 'collections'
HTML_FOLDER_NAME = 'source_code.html'
SETTINGS_FOLDER_NAME = 'source_code.settings'
LOG_FOLDER_NAME = 'logs'
LOG_FILE_NAME = 'log.jsonl'
SETTINGS_FILE_NAME = 'data.json'
TEMPLATE_FILE_NAME = 'template.html'
VISUALIZATION_FILE_NAME = 'logvisualization{}.html'
IGNORELIST_FILE_NAME = 'ignorelist.txt'

# settings, data and logs normally sit in the working directory. a deployed bundle keeps
# them in separate folders, so these let it say where without moving the working directory.
ENV_CONFIG_FOLDER = 'AO3DOWNLOADER_CONFIG_FOLDER'
ENV_LOG_FOLDER = 'AO3DOWNLOADER_LOG_FOLDER'
INI_FILE_NAME = 'settings.ini'
INI_SECTION_NAME = 'settings'

INI_WAIT_TIME = 'ExtraWaitTime'
INI_PASSWORD_SAVE = 'SavePassword'
INI_NAME_LENGTH = 'FileNameLength'
INI_DEBUG_LOGGING = 'EnableDebugLogging'
INI_MAX_RETRIES = 'MaxRetries'
INI_MAX_TIMEOUTS = 'MaxTimeouts'
INI_DOWNLOAD_FOLDER = 'DownloadFolder'

INI_DEFAULT_NAME_LENGTH = 50

# how the date stamp on a downloaded file is written, and how long it is with its space.
# it goes on the end because the work number has to stay first for files to be matched
# back to their index entry.
DATE_STAMP_FORMAT = '%Y-%m-%d'
DATE_STAMP_LENGTH = 11

# How a downloaded file is named. Fixed rather than configurable: the work number has to
# come first for a file to be matched back to its index entry, and the date has to come
# last for the version it holds to be readable, so the parts that could vary are the ones
# that matter least. The ui shows this back instead of offering it as a setting.
FILE_NAME_PATTERN = '{worknum} {title} - {author}'

# how the date on the end is described when the naming is shown back to the user, and an
# example of the whole thing, so the rule can be read rather than deduced
DATE_STAMP_PLACEHOLDER = '{date updated}'
FILE_NAME_EXAMPLE_PARTS = ['34816549', 'No Paths Are Bound', 'Cataclysmic_Cal', '2026-08-23']

SETTING_USERNAME = 'username'
SETTING_PASSWORD = 'password'
SETTING_FILETYPES = 'filetypes'
SETTING_API_TOKEN = 'api_token'
SETTING_UPDATE_FOLDER = 'update_folder'
SETTING_UPDATE_FILETYPES = 'update_filetypes'

# endregion

# region ui

PROMPT_YES = 'y'
PROMPT_NO = 'n'

PROMPT_MENU = '\'{}\' to display the menu again'
PROMPT_CHOOSE = 'please enter your choice, or \'{}\' to quit:'
PROMPT_OPTIONS = 'options'
PROMPT_INVALID_ACTION = 'please choose a valid action'

# for action description changes be sure to update readme
ACTION_DESCRIPTION_DISPLAY_MENU = 'display menu'
ACTION_DESCRIPTION_AO3 = 'download from ao3 link'
ACTION_DESCRIPTION_UPDATE = 'download latest version of incomplete fics'
ACTION_DESCRIPTION_PINBOARD = 'download bookmarks from pinboard'
ACTION_DESCRIPTION_VISUALIZATION = 'convert logfile into interactable html'
ACTION_DESCRIPTION_REDOWNLOAD = 're-download fics saved in one format in a different format'
ACTION_DESCRIPTION_UPDATE_SERIES = 'download missing fics from series'
ACTION_DESCRIPTION_LINKS_ONLY = 'get all work links from an ao3 listing (saves links only)'
ACTION_DESCRIPTION_MARKED_FOR_LATER = 'download marked for later list and mark all as read (requires login)'
ACTION_DESCRIPTION_FILE_INPUT = 'download links from file'
ACTION_DESCRIPTION_CONFIGURE_IGNORELIST = 'configure ignore list (list of links to never try to download)'

PINBOARD_PROMPT_API_TOKEN = 'please enter api token'
PINBOARD_PROMPT_INCLUDE_UNREAD = 'do you want to include unread bookmarks? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_DATE = 'do you want to get bookmarks only after a specific date? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_ENTER_DATE = 'please enter the date formatted {}:'
PINBOARD_INFO_GETTING_BOOKMARKS = 'getting bookmark urls from pinboard'
PINBOARD_INFO_NUM_RETURNED = '{} bookmarks returned'

AO3_PROMPT_LOGIN = 'do you want to log in to ao3? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_USERNAME = 'please enter username:'
AO3_PROMPT_PASSWORD = 'please enter password:\nNOTE: password {} be saved. to change this behavior,\nquit the script (using ctrl+c or by closing the window)\nand edit the \'' + INI_PASSWORD_SAVE + '\' setting in the ' + INI_FILE_NAME + '\nfile before running the script again\nNOTE: password input will not be displayed in this window'
AO3_PROMPT_PASSWORD_SAVE_TRUE = 'will'
AO3_PROMPT_PASSWORD_SAVE_FALSE = 'will not'
AO3_PROMPT_USE_SAVED_DOWNLOAD_TYPES = 'use saved download type list? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_ACCEPTABLE_DOWNLOAD_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
AO3_DOWNLOAD_TYPE_METADATA = 'JSON'
AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA = AO3_ACCEPTABLE_DOWNLOAD_TYPES + [AO3_DOWNLOAD_TYPE_METADATA]
AO3_PROMPT_DOWNLOAD_TYPE = 'please enter download type. choose from the following (case-sensitive):\n' + '\n'.join(AO3_ACCEPTABLE_DOWNLOAD_TYPES)
AO3_PROMPT_DOWNLOAD_TYPE_WITH_METADATA = (
    'please enter download type. choose from the following (case-sensitive):\n'
    + '\n'.join(AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA)
    + '\nNOTE: ' + AO3_DOWNLOAD_TYPE_METADATA + ' does not download the works themselves. it saves work and\n'
    + 'bookmark metadata for every work on the page to a single ' + AO3_DOWNLOAD_TYPE_METADATA.lower() + ' file.')
AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE = 'done entering file types? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_LINK = 'please enter a link to ao3 (for example bookmarks, search results, or a series)'
AO3_PROMPT_LAST_PAGE = 'do you want to start downloading from the page you stopped on last time? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_PAGES = 'please enter page number to stop on. enter 0 to download all pages.'
AO3_PROMPT_IMAGES = 'do you want to download embedded images? (will be saved separately) ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_SERIES = 'do you want to get works from all encountered series links? (bookmarked series and subscriptions will always be downloaded, regardless of this option) ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_METADATA = 'do you want to include work metadata? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_FILE_INPUT = 'please enter complete file path (including file extension) to file containing links to download (must be a text file with one link on each line)'
AO3_PROMPT_METADATA_WORK_DATES = 'do you want to look up the original publication date of every work? this is the only\nfield that is not on the listing page, so it requires loading each work separately\nand is a lot slower. ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_INFO_LOGIN = 'logging in'
# the web ui shows the console output as the run's log, and logging in is the first thing
# it does. without a line here the modal opens on an empty log and looks like it hung
AO3_INFO_LOGGING_IN = 'logging in as {}'
AO3_INFO_LOGGED_IN = 'successfully logged in'
AO3_INFO_DOWNLOADING = 'downloading works'
AO3_INFO_FILE_TYPE = 'added {} to list of download types'
AO3_INFO_VISITED = 'generating list of work links that are already in the downloads folder (will be skipped)'
AO3_INFO_METADATA = 'getting metadata'
AO3_INFO_INDEXING = 'indexing: saving a json file for every bookmark before downloading any works'
AO3_INFO_COLLECTIONS = 'syncing collections'
AO3_INFO_COLLECTION_SAVED = 'saved collection {}'
AO3_INFO_COLLECTION_UNCHANGED = 'collection {} still has {} {}, so the saved ones are kept'
AO3_INFO_COLLECTIONS_DONE = 'saved {} collections to {}'
AO3_INFO_COLLECTIONS_NONE = 'no collections found for that user'
AO3_INFO_COLLECTION_ONE = 'indexing the collection {}'

INFO_REPLACED_OLD_COPY = 'replaced the older copy: {}'
INFO_KEPT_OLD_COPY = 'kept the older copy, the new file could not be confirmed: {}'
ERROR_REPLACE_OLD_COPY = 'Problem removing the copy a download replaced. The old file is still there.'
AO3_INFO_OUT_OF_DATE = '{} downloaded works have been updated on ao3 since you saved them'
AO3_INFO_UNDATED = '{} downloaded works were saved before file names carried a date'
AO3_INFO_CHECKING_FILES = 'checking which of these you have already downloaded'
AO3_INFO_CHECKING_VERSIONS = 'checking which of your downloads ao3 has a newer version of'
AO3_INFO_UNDATED_WAITING = 'waiting for you to say what to do about them'
AO3_INFO_UNDATED_REFRESH = 'treating all {} as out of date, so they will be downloaded again'
AO3_INFO_UNDATED_SKIPPED = 'leaving all {} as they are'
AO3_INFO_UP_TO_DATE = 'everything else you have is already the current version'
AO3_INFO_STAMPED = 'dated {} existing files as {}'
AO3_INFO_FROM_INDEX = 'downloading {} works straight from the index, without walking the listing again'
AO3_INFO_FAILED_WORKS = '{} works could not be downloaded'
AO3_INFO_READING_INDEX = 'reading your index for fics it last saw unfinished'
AO3_INFO_INCOMPLETE_FOUND = 'the index lists {} works as unfinished'
# said per fic, so the log reads as a running account of what is happening to each one
AO3_INFO_UPDATE_WORK = '[{} of {}] {}'
# said before the request, not after: opening the fic page is the slow part, so without a
# line first the run looks stalled on the fic it has only just named
AO3_INFO_UPDATE_READING = '    reading latest index'
AO3_INFO_UPDATE_INDEXED = '    index updated'
AO3_INFO_UPDATE_CURRENT = '    you already have the current version - nothing to download'
AO3_INFO_UPDATE_BEHIND = '    your copy is behind, downloading the new version'
AO3_INFO_UPDATE_MISSING = '    you have no copy of this one, downloading it'
AO3_INFO_UPDATE_NOTHING = '    nothing to download, only the index was updated'
AO3_INFO_UPDATE_DONE = 'checked {} works and downloaded {}'
AO3_INFO_INCOMPLETE_NONE = 'the index lists no unfinished works. nothing to check.'
AO3_INFO_INCOMPLETE_GREW = '{} of them need downloading again'
AO3_INFO_INCOMPLETE_UNCHANGED = 'none of them have changed since you last downloaded them'
ERROR_WORK_STATS = 'Could not read the stats from that work page'
ERROR_NOT_A_WORK_FILE = 'Ao3 answered with a page rather than the file. The work may have been deleted, made restricted, or be unavailable in that format.'
AO3_INFO_STAMP_SKIPPED = '{} files were left as they were - a file of that name already existed'

# how many entries ao3 puts on a page of a listing. only used to work out how many works
# sit before a run that starts partway through, so its positions carry on from there.
AO3_LISTING_PAGE_SIZE = 20
AO3_INFO_METADATA_WORK_DATES = 'looking up publication dates for {} works'
AO3_INFO_METADATA_PROGRESS = 'finished {} of {} works'
# said before the request, not after it. fetching a listing page is the slow part, and a
# log that only reports finished pages sits unchanged for the whole of every wait - which
# reads as a hang rather than as work in progress. the total is not known until the first
# page comes back, so the first one has nothing to count towards.
AO3_INFO_METADATA_FETCHING = 'fetching page {} of {}'
AO3_INFO_METADATA_FETCHING_FIRST = 'fetching page {}'
AO3_INFO_METADATA_PAGE = 'finished page {} of {}. {} works so far'
# a listing of one page carries no pagination for the total to be read from, so there is
# genuinely nothing to count towards - saying 'of None' would be worse than saying nothing
AO3_INFO_METADATA_PAGE_ONLY = 'finished page {}. {} works so far'
AO3_INFO_METADATA_SKIPPED = 'skipped {} bookmarks that are not works (series, external works, or deleted works)'
AO3_INFO_METADATA_WRITTEN = 'wrote metadata for {} works to {}'
AO3_INFO_METADATA_INCREMENTAL = 'saving one json file per work as each page is read. if you need to stop\nearly, press ctrl+c rather than closing the window'
AO3_INFO_METADATA_NONE = 'no works found on that page. nothing was written'

PROMPT_LINKS_ONLY = 'save links to a file instead of downloading? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
INFO_LINKS_FILE_WRITTEN = 'wrote {} links to {}'
INFO_NO_LINKS_TO_WRITE = 'no links to write'

UPDATE_PROMPT_INPUT = 'input path to folder containing files you want to check for updates (also checks subfolders)'
UPDATE_INFO_FILES = 'getting list of files'
UPDATE_INFO_NUM_RETURNED = '{} files found'
UPDATE_INFO_URLS = 'getting urls of incomplete fics'
UPDATE_INFO_URLS_DONE = 'finished getting urls of incomplete fics'
UPDATE_INFO_DOWNLOADING = 're-downloading incomplete works'
UPDATE_ACCEPTABLE_FILE_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
UPDATE_PROMPT_USE_SAVED_FILE_TYPES = 'use saved list of file types to check for updates? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
UPDATE_PROMPT_USE_SAVED_FOLDER = 'check same folder as last time? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
UPDATE_PROMPT_FILE_TYPE = 'please enter the file type of the files you would like to check for updates. choose from the following (case-sensitive):\n' + '\n'.join(UPDATE_ACCEPTABLE_FILE_TYPES)
UPDATE_INFO_FILE_TYPE = 'added {} to list of file types to check for updates'
UPDATE_INFO_FILTER = 'filtering out works that could not be downloaded on previous runs'

SERIES_INFO_FILES = 'getting list of works belonging to series'
SERIES_INFO_URLS = 'finding all series urls'
SERIES_INFO_NUM = '{} series found'
SERIES_INFO_DOWNLOADING = 'downloading works missing from series'
SERIES_INFO_FILTER = 'filtering out series that could not be downloaded on previous runs'

REDOWNLOAD_PROMPT_FOLDER = 'please enter the folder containing the files you want to re-download (also checks subfolders):'
REDOWNLOAD_PROMPT_FILE_TYPE = 'please enter file type you want to convert from. choose from the following (case sensitive):\n' + '\n'.join(UPDATE_ACCEPTABLE_FILE_TYPES)
REDOWNLOAD_INFO_FILE_TYPE = 'added {} to list of file types to convert from'
REDOWNLOAD_INFO_URLS = 'getting work urls'
REDOWNLOAD_INFO_DONE = 'done getting work urls. {} urls found'

IGNORELIST_INFO_INITIALIZED = f'{IGNORELIST_FILE_NAME} has been added to the main script folder. you can use this file to perma-skip downloading works or series that you know you don\'t want to download. to use this file open it in a text editor (the default text editor for Windows is called Notepad. on Mac, you can use TextEdit) and add the links you want to ignore, one on each line. these should be links to ao3 works or series. other links will be ignored. each link MUST begin with https://archiveofourown.org and be placed at the start of a new line. you may also *optionally* add a comment after each link. comments must begin with a SEMICOLON followed by a SPACE: `; ` and must not contain any newline characters (the entire comment must be on the same line as the link). otherwise, you can write anything you want in the comment. comments are for your personal reference only and are not used by the script.'
IGNORELIST_PROMPT_CHECK_DELETED = 'do you want to check the log file for deleted links and add them to the ignore list automatically? ({}/{})'.format(PROMPT_YES, PROMPT_NO)

INFO_NO_LOG_FILE = 'no log file'
INFO_NO_FILE = 'file does not exist: {}'
INFO_NO_FOLDER = 'folder does not exist: {}'
INFO_SAVED_FOLDER_MISSING = 'previously saved folder no longer exists: {}'
INFO_EXCLUDING_WORKS = 'filtering out works that are already in the downloads folder'
INFO_STARTING_PAGE = 'starting page'
INFO_FINISHED_PAGE = 'finished getting page {}. starting page {} of {}'
INFO_PARSING_LOGS = 'parsing data from log entries with timestamps starting at {} and ending at {}'
INFO_CANCELLED = 'stopped at your request. anything already saved has been kept.'
INFO_LINKS_LIST_CANCELED = '\nlink list generation manually canceled. list may not be complete.'
INFO_NO_WORKS_ON_PAGE = 'ending scrape because no work or series urls were found on page'
INFO_PAGE_LIMIT_REACHED = 'ending scrape because page limit was reached'

MESSAGE_TOO_MANY_REQUESTS = 'ao3 has requested a {} second break\npaused at: {}\nresuming at: {}'
MESSAGE_RESUMING = 'resuming execution'
# a break the user asked for, as opposed to one ao3 demanded. it says where the run got to
# because that is the whole reassurance being offered: nothing was left half done
MESSAGE_HELD = 'paused. the work in progress has finished and nothing new will be started'
MESSAGE_RELEASED = 'resuming'
MESSAGE_INCOMPLETE_FIC = 'found incomplete fic'
MESSAGE_FIC_FILE = 'found fic file'
MESSAGE_SERIES_FILE = 'found work in series'
MESSAGE_RETRY = 'Retrying {} request. Attempt {}. {} seconds until next attempt.'
MESSAGE_SUCCESS = 'Successful {} request with status code {}'
MESSAGE_WELCOME = 'welcome to ao3downloader!\nthe script has been initialized in the following directory:\n\t{}\nif you would like to change any settings, you may do so by entering\n\'{}\' to quit this menu and then editing the file \'{}\'\n(located at the above folder path) before running the script again.\n'
MESSAGE_DOWNLOAD_FOLDER = 'downloads will be saved to:\n\t{}\n'
MESSAGE_DOWNLOAD_FOLDER_ERROR = 'could not create the download folder: {}\nplease check the \'' + INI_DOWNLOAD_FOLDER + '\' setting in ' + INI_FILE_NAME
MESSAGE_EXIT = '\nexiting'
MESSAGE_INI_FILE_CHANGED = 'the options available in ' + INI_FILE_NAME + ' have changed. a copy of the new default settings file has been saved as {}. please review the changes and update ' + INI_FILE_NAME + ' accordingly.'
MESSAGE_INI_DIFFERENCES = 'the following differences were found:\n'
MESSAGE_INI_ADDED_KEY = 'added \'{}\' to \'{}\' section.\n'
MESSAGE_INI_REMOVED_KEY = 'removed \'{}\' from \'{}\' section.\n'
MESSAGE_INI_ADDED_SECTION = '\'{}\' section has been added.\n'
MESSAGE_INI_REMOVED_SECTION = '\'{}\' section has been removed.\n'
MESSAGE_LOGIN_RESET = 'login details have been reset; please try again'

# endregion

# region ao3 scraping

AO3_DOMAIN = 'archiveofourown.org'
AO3_BASE_URL = 'https://' + AO3_DOMAIN

# ao3 serves work files from a host of their own, and the links on a work page redirect
# there. going straight to it skips that redirect. the segment after the work number is a
# slug of the title which ao3 ignores, so a fixed one does just as well - verified against
# the live site: both spellings return byte-identical files.
AO3_DOWNLOAD_BASE_URL = 'https://download.' + AO3_DOMAIN
AO3_DOWNLOAD_SLUG = 'fic'
AO3_LOGIN_URL = AO3_BASE_URL + '/users/login'
AO3_MARK_READ_URL = AO3_BASE_URL + '/works/{}/mark_as_read'

AO3_PROCEED = 'Yes, Continue'
AO3_MARK_READ = 'Mark as Read'

# endregion

# region pinboard scraping

POSTS_FROM_DATE_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}&fromdt={}'
ALL_POSTS_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}'
TIMESTAMP_URL = '{}-{}-{}T00:00:00Z'

# endregion

# region error messages

ERROR_INVALID_LINK = 'Not an ao3 link'
ERROR_LOCKED = 'Locked'
ERROR_DELETED = 'Deleted'
ERROR_HIDDEN = 'Hidden'
ERROR_FAILED_LOGIN = 'Failed login: {}'
ERROR_PROCEED_LINK = 'Problem getting proceed link'
ERROR_DOWNLOAD_LINK = 'Problem getting download link'
ERROR_LOG_FILE = 'Problem parsing log file during initial setup'
ERROR_INCOMPLETE_FIC = 'Problem parsing file while checking for incomplete fics'
ERROR_FIC_IN_SERIES = 'Problem parsing file while checking for fics in series'
ERROR_REDOWNLOAD = 'Error processing file for re-download'
ERROR_IMAGE = 'Problem getting image'
ERROR_LINKS_LIST = 'Error encountered while getting links list. List may not be complete.'
ERROR_HTTP_REQUEST = 'Unrecoverable error encountered while making web request'
ERROR_INVALID_STATUS_CODE = 'Request failed with status code {}'
ERROR_TIMEOUT = 'Request exceeded the timeout limit of {} seconds'
ERROR_CLOUDFLARE = 'Cloudflare challenge or error page detected'
ERROR_MARK_READ = 'Problem marking work as read'
ERROR_MARK_READ_SKIP = 'Skipping marking work as read; could not find form input'
ERROR_PDF_PARSE = 'Problem parsing pdf; skipping update check'
ERROR_SERIES_LINK = 'Expected series information, but could not find it'
ERROR_WORK_BLURB = 'Could not find work metadata in list'
ERROR_METADATA_BLURB = 'Problem parsing work metadata from listing'
ERROR_METADATA_SAVE = 'Problem saving work metadata file'
ERROR_COLLECTIONS = 'Error encountered while syncing collections. Some may be missing.'
ERROR_NOT_A_COLLECTION = 'That is not a link to an ao3 collection. It should look like https://archiveofourown.org/collections/somename'
ERROR_COLLECTION_PROFILE = 'Problem reading a collection profile page'
ERROR_COLLECTION_ITEMS = 'Problem reading the items in a collection'
ERROR_COLLECTION_SAVE = 'Problem saving collection file'
ERROR_METADATA_WORK_DATES = 'Problem getting publication dates from work page'
ERROR_METADATA_NOT_A_LISTING = 'The {} download type needs a link to a listing of works, such as bookmarks, search results, or a series. It cannot be used with a link to a single work.'

FAILED_LOGIN_NOT_FOUND = 'could not retrieve login page'
FAILED_LOGIN_NO_RESPONSE = 'could not get a response from login request'
FAILED_LOGIN_INVALID_CREDENTIALS = 'invalid username or password'
FAILED_LOGIN_NO_FORM = 'could not find login form. page title was: {}'
FAILED_LOGIN_NO_TOKEN = 'could not find authenticity token field in login form'
FAILED_LOGIN_NO_TOKEN_VALUE = 'authenticity token field was empty'

# endregion
