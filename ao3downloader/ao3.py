"""Download works from ao3."""

import datetime
import os
import traceback
from collections.abc import Callable

from bs4 import BeautifulSoup

from ao3downloader import exceptions, parse_soup, parse_text, progress, strings
from ao3downloader.fileio import FileOps
from ao3downloader.progress import ProgressCallback
from ao3downloader.repo import Repository


class Ao3:
    def __init__(
            self, 
            repo: Repository, 
            fileops: FileOps, 
            filetypes: list[str], 
            pages: int | None, 
            series: bool, 
            images: bool,
            mark: bool = False,
            progress: ProgressCallback | None = None,
            cancelled: Callable[[], bool] | None = None) -> None:
        self.repo = repo
        self.fileops = fileops
        self.progress = progress
        self.cancelled = cancelled
        self.filetypes = filetypes
        self.pages = pages
        self.series = series
        self.images = images
        self.mark = mark
        self.debug = fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False)


    def download(self, link: str, visited: list[str] | None = None) -> None:

        log = {}
        if not visited: visited = []

        try:
            self.download_recursive(link, log, visited)
        except exceptions.CancelledException:
            # works already downloaded stay where they are; this is not a failure
            print(strings.INFO_CANCELLED)
        except Exception as e:
            self.log_error(log, e)


    def update(self, link: str, chapters: str) -> None:
        
        log = {}
        
        try:
            self.download_work(link, log, chapters)
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
        except Exception as e:
            self.log_error(log, e)


    def update_series(self, link: str, visited: list[str]) -> None:

        log = {}

        try:
            self.download_series(link, log, visited)
        except Exception as e:
            self.log_error(log, e)


    def get_metadata(self, link: str, workdates: bool) -> list[dict]:
        """Walk a listing and save metadata for every work on it, one file per bookmark.

        One request per page rather than per work, so a bookmarks list of any size is
        cheap. Each file is written as its page is parsed, so a long run leaves usable
        output behind even if it is interrupted partway. Bookmarks of series, external
        works, and deleted works have none of the fields we're collecting, so they're
        counted and skipped rather than exported.
        """

        if parse_text.is_work(link):
            raise exceptions.InvalidLinkException(
                strings.ERROR_METADATA_NOT_A_LISTING.format(strings.AO3_DOWNLOAD_TYPE_METADATA))
        if strings.AO3_BASE_URL not in link:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)

        source = link # the loop below walks `link` on to the next page
        retrieved = datetime.datetime.now().strftime(strings.TIMESTAMP_FORMAT)

        records: list[dict] = []
        seen: set[str] = set()
        skipped = 0
        total_pages = None

        try:
            while True:
                self.check_cancelled()
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                for blurb in parse_soup.get_blurbs(thesoup):
                    if not parse_soup.get_blurb_work_number(blurb):
                        skipped += 1
                        continue
                    # a work can be bookmarked more than once, and can shift between pages
                    # while we're paging through, so dedupe on the bookmark rather than the work
                    key = parse_soup.get_blurb_id(blurb) or str(parse_soup.get_blurb_work_number(blurb))
                    if key in seen: continue
                    seen.add(key)
                    document = {
                        'source': source,
                        'retrieved': retrieved,
                        # the listing order, which is the order ao3 shows the bookmarks in
                        'position': len(records) + 1,
                    }
                    document.update(parse_soup.get_blurb_metadata(blurb))
                    records.append(document)
                    self.save_metadata(document)
                progress.report(self.progress, progress.PAGE,
                                page=parse_text.get_page_number(link),
                                total=total_pages, works=len(records))
                pagenum = parse_text.get_page_number(link)
                if not total_pages or pagenum >= total_pages:
                    break
                link = parse_text.get_next_page(link)
                pagenum = parse_text.get_page_number(link)
                if self.pages and pagenum == self.pages + 1:
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                    break
                print(strings.AO3_INFO_METADATA_PAGE.format(str(pagenum - 1), str(total_pages), str(len(records))))
        except exceptions.CancelledException:
            # everything written so far stays on disk; this is not an error
            print(strings.INFO_CANCELLED)
        except Exception as e:
            print(strings.ERROR_LINKS_LIST)
            self.log_error({'message': strings.ERROR_LINKS_LIST, 'link': link}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        if skipped: print(strings.AO3_INFO_METADATA_SKIPPED.format(str(skipped)))
        if workdates and records: self.add_work_dates(records)

        return records


    def save_metadata(self, document: dict) -> None:
        """Write one bookmark to its own json file.

        Named with the same pattern as a downloaded work, so a fic's metadata sits next
        to its epub or html under the same name.
        """

        try:
            pattern = self.fileops.get_ini_value(strings.INI_NAME_PATTERN, strings.INI_DEFAULT_NAME_PATTERN)
            maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
            name = parse_soup.apply_name_pattern(parse_soup.get_name_metadata_from_blurb(document), pattern)
            filename = parse_text.get_valid_filename(name, maximum)
            # a pattern can resolve to nothing if every field it uses is empty
            if not filename: filename = str(document.get('id') or document.get('position'))
            self.fileops.save_json(
                filename + parse_text.get_file_type(strings.AO3_DOWNLOAD_TYPE_METADATA), document)
        except Exception as e:
            # one unwritable file shouldn't end the run
            self.log_error({'message': strings.ERROR_METADATA_SAVE, 'link': document.get('link')}, e)


    def add_work_dates(self, records: list[dict]) -> None:
        """Fill in date_created, and refine date_updated, by loading each work page.

        Listing pages show a single date and no publication date at all, so this is the
        only way to get both. It costs one request per work, hence the separate prompt.
        """

        print(strings.AO3_INFO_METADATA_WORK_DATES.format(str(len(records))))

        for index, record in enumerate(records, start=1):
            work_link = record.get('link')
            if not work_link: continue
            try:
                self.check_cancelled()
                thesoup = self.proceed(self.repo.get_soup(work_link))
                record['date_created'] = parse_soup.get_text_or_empty(thesoup, 'dd.published')
                # single chapter works have no status line; keep the listing date in that case
                updated = parse_soup.get_text_or_empty(thesoup, 'dd.status')
                if updated: record['date_updated'] = updated
                # the file was written during the crawl, so rewrite it with the dates in
                self.save_metadata(record)
            except exceptions.CancelledException:
                print(strings.INFO_CANCELLED)
                break
            except KeyboardInterrupt:
                print(strings.INFO_LINKS_LIST_CANCELED)
                break
            except Exception as e:
                self.log_error({'message': strings.ERROR_METADATA_WORK_DATES, 'link': work_link}, e)
            progress.report(self.progress, progress.WORK, done=index, total=len(records),
                            title=record.get('title', ''))
            if index % 10 == 0 or index == len(records):
                print(strings.AO3_INFO_METADATA_PROGRESS.format(str(index), str(len(records))))


    def get_work_links(self, link: str, metadata: bool) -> dict[str, dict]:
        
        links_list = {}
        visited_series = []

        try:
            self.get_work_links_recursive(links_list, link, visited_series, metadata)
        except Exception as e:
            print(strings.ERROR_LINKS_LIST)
            self.log_error({'message': strings.ERROR_LINKS_LIST}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        return links_list


    def get_work_links_recursive(
            self, 
            links_list: dict[str, dict | None], 
            link: str, 
            visited_series: list[str], 
            metadata: bool, 
            soup: BeautifulSoup | None = None) -> None:

        if parse_text.is_work(link):
            if link not in links_list:
                if metadata and soup:
                    work_metadata = parse_soup.get_work_metadata_from_list(soup, link)
                    links_list[link] = work_metadata
                else:
                    links_list[link] = None
        elif parse_text.is_series(link):
            if link not in visited_series:
                visited_series.append(link)
                total_pages = None
                while True:
                    series_soup = self.repo.get_soup(link)
                    series_soup = self.proceed(series_soup)
                    if total_pages is None:
                        total_pages = parse_soup.get_total_pages(series_soup)
                    work_urls = parse_soup.get_work_urls(series_soup)
                    for work_url in work_urls:
                        self.get_work_links_recursive(links_list, work_url, visited_series, metadata, series_soup)
                    pagenum = parse_text.get_page_number(link)
                    if not total_pages or pagenum >= total_pages:
                        break
                    link = parse_text.get_next_page(link)
        elif strings.AO3_BASE_URL in link:
            # special case for subscriptions page - it doesn't have blurbs, so any series
            # links encountered are directly subscribed to and should always be downloaded.
            include_series = parse_text.is_subscriptions(link) or self.series
            total_pages = None
            while True:
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                urls = parse_soup.get_work_and_series_urls(thesoup, include_series)
                for url in urls:
                    self.get_work_links_recursive(links_list, url, visited_series, metadata, thesoup)
                pagenum = parse_text.get_page_number(link)
                if not total_pages or pagenum >= total_pages:
                    break
                link = parse_text.get_next_page(link)
                pagenum = parse_text.get_page_number(link)
                if self.pages and pagenum == self.pages + 1:
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                    break
                print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum), str(total_pages)))
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_recursive(self, link: str, log: dict, visited: list[str]) -> None:

        self.check_cancelled()

        if link in visited: return
        visited.append(link)

        if parse_text.is_work(link):
            log = {}
            self.download_work(link, log, None)
        elif parse_text.is_series(link):
            log = {}
            self.download_series(link, log, visited)        
        elif strings.AO3_BASE_URL in link:
            # special case for subscriptions page - it doesn't have blurbs, so any series
            # links encountered are directly subscribed to and should always be downloaded.
            include_series = parse_text.is_subscriptions(link) or self.series
            total_pages = None
            while True:
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                urls = parse_soup.get_work_and_series_urls(thesoup, include_series)
                for url in urls:
                    self.download_recursive(url, log, visited)
                if not self.mark:
                    pagenum = parse_text.get_page_number(link)
                    if not total_pages or pagenum >= total_pages:
                        break
                    link = parse_text.get_next_page(link)
                    pagenum = parse_text.get_page_number(link)
                    if self.pages and pagenum == self.pages + 1:
                        if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                        break
                    print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum), str(total_pages)))
                    progress.report(self.progress, progress.PAGE, page=pagenum - 1, total=total_pages)
                else:
                    total_pages = parse_soup.get_total_pages(thesoup)
                    if not total_pages or total_pages <= 1:
                        break
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_series(self, link: str, log: dict, visited: list[str]) -> None:
        """"Download all works in a series"""

        try:
            total_pages = None
            while True:
                series_soup = self.repo.get_soup(link)
                series_soup = self.proceed(series_soup)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(series_soup)
                work_urls = parse_soup.get_work_urls(series_soup)
                if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                for work_url in work_urls:
                    self.download_recursive(work_url, log, visited)
                pagenum = parse_text.get_page_number(link)
                if not total_pages or pagenum >= total_pages:
                    break
                link = parse_text.get_next_page(link)
        except exceptions.CancelledException:
            raise # let a stop unwind rather than being logged as a series failure
        except Exception as e:
            log['link'] = link
            self.log_error(log, e)


    def download_work(self, link: str, log: dict, chapters: str | None) -> None:
        """Download a single work"""

        try:
            log['link'] = link
            downloaded = self.try_download(link, log, chapters)
            if downloaded == False: return
        except exceptions.CancelledException:
            raise # a stop is not a failed download, and must not be logged as one
        except Exception as e:
            self.log_error(log, e)
        else:
            log['success'] = True
            self.fileops.write_log(log)
            progress.report(self.progress, progress.WORK, title=log.get('title', ''), link=link)


    def try_download(self, work_url: str, log: dict, chapters: str | None) -> bool:
        """Main download logic"""

        thesoup = self.repo.get_soup(work_url)
        thesoup = self.proceed(thesoup)

        if chapters is not None: # TODO this is a super awkward place for this logic to be and I don't like it.
            currentchapters = parse_soup.get_current_chapters(thesoup)
            if int(currentchapters) <= int(chapters):
                return False
        
        pattern = self.fileops.get_ini_value(strings.INI_NAME_PATTERN, strings.INI_DEFAULT_NAME_PATTERN)
        maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        title = parse_soup.get_title(thesoup, work_url, pattern)
        filename = parse_text.get_valid_filename(title, maximum)
        log['title'] = title
        log['workskin'] = parse_soup.has_custom_skin(thesoup)

        # what is being fetched right now, so the ui can name the fic and the format
        display = ' / '.join(x for x in title if x)
        progress.report(self.progress, progress.WORK, title=display, link=work_url,
                        phase='downloading')

        for filetype in self.filetypes:
            self.check_cancelled()
            progress.report(self.progress, progress.WORK, title=display, link=work_url,
                            filetype=filetype, phase='downloading')
            link = parse_soup.get_download_link(thesoup, filetype)
            response = self.repo.get_book(link)
            filetype = parse_text.get_file_type(filetype)
            self.fileops.save_bytes(filename + filetype, response)

        if self.images:
            counter = 0
            imagelinks = parse_soup.get_image_links(thesoup)
            for img in imagelinks:
                if str.startswith(img, '/'): continue
                try:
                    ext = os.path.splitext(img)[1]
                    if '?' in ext: ext = ext[:ext.index('?')]
                    response = self.repo.get_book(img)
                    imagefile = filename + ' img' + str(counter).zfill(3) + ext
                    self.fileops.save_bytes(os.path.join(strings.IMAGE_FOLDER_NAME, imagefile), response)
                    counter += 1
                except Exception as e:
                    self.fileops.write_log({
                        'message': strings.ERROR_IMAGE, 'link': work_url, 'title': title, 
                        'img': img, 'error': str(e), 'stacktrace': traceback.format_exc()})

        if self.mark:
            self.repo.mark_work_as_read(thesoup, work_url)

        return True


    def proceed(self, thesoup: BeautifulSoup) -> BeautifulSoup:
        """Check locked/deleted and proceed through explicit agreement if needed"""

        if parse_soup.is_locked(thesoup):
            raise exceptions.LockedException(strings.ERROR_LOCKED)
        if parse_soup.is_deleted(thesoup):
            raise exceptions.DeletedException(strings.ERROR_DELETED)
        if parse_soup.is_hidden(thesoup):
            raise exceptions.HiddenException(strings.ERROR_HIDDEN)
        if parse_soup.is_explicit(thesoup):
            proceed_url = parse_soup.get_proceed_link(thesoup)
            thesoup = self.repo.get_soup(proceed_url)
        return thesoup


    def check_cancelled(self) -> None:
        """Stop the run if the caller has asked it to.

        Called at loop boundaries rather than mid-work, so whatever was being written
        finishes first and nothing is left half-saved.
        """

        if self.cancelled is not None and self.cancelled():
            raise exceptions.CancelledException(strings.INFO_CANCELLED)


    def log_error(self, log: dict, exception: Exception):
        log['error'] = str(exception)
        log['success'] = False
        if not isinstance(exception, exceptions.Ao3DownloaderException):
            log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(exception).format())
        self.fileops.write_log(log)
