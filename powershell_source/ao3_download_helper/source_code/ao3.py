"""Download works from ao3."""

import contextlib
import datetime
import os
import sys
import traceback
from collections.abc import Callable

from bs4 import BeautifulSoup

from source_code import exceptions, indexing, parse_soup, parse_text, progress, strings
from source_code.fileio import FileOps
from source_code.progress import ProgressCallback
from source_code.repo import Repository


# what replace_superseded did about an older copy
REPLACED = 'replaced'
KEPT = 'kept'
UNCONFIRMED = 'unconfirmed'


def bookmark_state(soup) -> dict:
    """The `bookmarked` field to write for a fic read from its own page, or nothing.

    Only a page that actually says - 'Edit Bookmark' or 'Bookmark' - changes the field. When
    it cannot tell (logged out, an unexpected page) the entry keeps whatever it had, so a
    fic a bookmarks walk marked as yours is not unmarked by a page that could not see.
    """

    try:
        state = parse_soup.get_bookmarked(soup)
    except Exception:
        return {}
    return {} if state is None else {strings.BOOKMARKED_FIELD: state}


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
            cancelled: Callable[[], bool] | None = None,
            start: int = 1) -> None:
        self.repo = repo
        self.fileops = fileops
        self.progress = progress
        self.cancelled = cancelled
        # replaced at the start of each indexing run, so every file it touches agrees
        self.indexed_on = indexing.now()
        self.filetypes = filetypes
        self.pages = pages
        # which page of a listing to begin at. 'pages' is where to stop, and both are
        # absolute page numbers, so a run can cover a slice in the middle of a listing.
        self.start = start if start and start > 1 else 1
        # {work link: {FILETYPE: path of the copy this run is replacing}}. filled in by the
        # caller when it has worked out which downloads are out of date.
        self.superseded: dict[str, dict[str, str]] = {}
        # works this run could not download, in the order they were attempted. the log
        # records them too, but a run that leaves gaps should be able to say which ones
        # without anyone having to read a log file to find out.
        self.failures: list[dict] = []
        # new copies that arrived while the older copy they replace could not be removed.
        # nothing is lost, but there are now two copies, so the run names each one
        self.kept_copies: list[dict] = []
        # bookmarks that are not works at all, so could never be indexed or downloaded.
        # kept as a list rather than a count so the run can name each one at the end
        self.skipped_works: list[dict] = []
        # whether this run has already asked ao3 whether its login is still good. asked at
        # most once: it costs a request, and a lapsed session fails every work after it
        self.session_checked = False
        # what this run did to which fics, for the history file. three sets rather than one
        # because they answer different questions: what got a fresh index entry, what
        # arrived as a file, and what replaced a copy that was already on disk.
        self.reindexed: set[str] = set()
        # bookmarked series read this run, and the works each held - a series bookmarked
        # twice, or met by both of a quick scan's walks, is read once
        self.series_read: dict[str, list[str]] = {}
        self.downloaded: set[str] = set()
        self.updated: set[str] = set()
        # work numbers seen on this run's listing that ao3 will not serve a file for yet,
        # because the work is in a collection that has not been revealed. they index fine;
        # it is only the download that is impossible, so they are held back from it.
        self.unrevealed: set[str] = set()
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
        except exceptions.SessionExpiredException:
            raise  # every work after this one would fail the same way; let it end the run
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


    def get_metadata(self, link: str, workdates: bool,
                     known: set[str] | None = None, stop_before: str = '',
                     stop_on: str = 'updated', own_bookmarks: bool = False) -> list[dict]:
        """Walk a listing and save metadata for every work on it, one file per bookmark.

        One request per page rather than per work, so a bookmarks list of any size is
        cheap. Each page is written once it has been read in full, so a long run leaves
        usable output behind even if it is interrupted partway. Bookmarks of series,
        external works, and deleted works have none of the fields we're collecting, so
        they're counted and skipped rather than exported.

        `known` turns this into a **new bookmarks only** pass: walking stops at the first
        work already in that set, and only the works ahead of it are returned. Ao3 lists
        bookmarks newest first, so everything before the first familiar one is new and
        everything after it has been seen - which is what makes one stop enough, and what
        turns a run over a whole library into a request or two.

        That assumption is the catch, and it is why this is not the default. Re-bookmarking
        an old fic moves it to the front; a bookmark deleted and remade does the same. The
        run stops correctly either way, but a fic bookmarked *before* the stopping point
        and never indexed - because an earlier run was interrupted, say - stays unseen. A
        full walk is the answer to that, and the ui says so.

        `stop_before` is the other short walk: stop at the first work ao3 last updated
        before that date (`YYYY-MM-DD`). **It is only correct on a listing sorted by that
        date** - `strings.AO3_SORT_BY_UPDATED` - and the caller is responsible for asking
        for one. Verified against the live site: the default order is by when each work was
        bookmarked and jumps about by years, so this walk down an unsorted listing would
        stop almost immediately and miss nearly everything.

        `stop_on` says which date `stop_before` is measured against: `'updated'` (the
        work's own date, `div.header p.datetime`) or `'bookmarked'` (the bookmark's date,
        `div.user p.datetime`). The listing has to be sorted by the same date - a
        bookmarked stop down an updated-date listing is exactly as wrong as the reverse.

        `own_bookmarks` says the listing is the logged-in user's own bookmarks, and marks
        every work read off it `bookmarked: True`. That is the one place the answer is
        certain - the fic is on the page because you bookmarked it. The caller says so rather
        than this guessing from the url, because a bookmarks url does not say whose.
        """

        if parse_text.is_work(link):
            raise exceptions.InvalidLinkException(
                strings.ERROR_METADATA_NOT_A_LISTING.format(strings.AO3_DOWNLOAD_TYPE_METADATA))
        if strings.AO3_BASE_URL not in link:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)

        source = link # the loop below walks `link` on to the next page
        # the listing itself is the source, not whichever page the run happened to begin
        # on, so a run that starts partway through still writes the same provenance
        link = parse_text.set_page_number(link, self.start)
        # one timestamp for the whole run, so every file this run touches agrees on when
        # it was indexed, and a second save of the same fic updates rather than appends
        self.indexed_on = indexing.now()

        # whether this walk can end before the listing does. a floor or a set of known works
        # stops it wherever the first older or familiar fic happens to sit, so the listing's
        # page count says nothing about how many pages this run will read - and 'page 3 of
        # 80' on a walk that stops at page 4 would be a promise it never meant to keep.
        # `total_pages` is still read and still ends the walk; it is only never *said*
        open_ended = bool(stop_before) or known is not None

        records: list[dict] = []
        seen: set[str] = set()
        skipped = 0
        total_pages = None

        try:
            while True:
                self.check_cancelled()
                current = parse_text.get_page_number(link)
                shown_total = None if open_ended else total_pages
                print(strings.AO3_INFO_METADATA_FETCHING.format(str(current), str(shown_total))
                      if shown_total else
                      strings.AO3_INFO_METADATA_FETCHING_FIRST.format(str(current)))
                # said before the request, so the ui names the page being fetched rather
                # than the last one that finished. the fetch is the slow part, and a
                # caption written only afterwards describes the wrong page for all of it
                asking, asking_of = self.page_progress(current, shown_total)
                progress.report(self.progress, progress.PAGE, page=asking, total=asking_of,
                                listingPage=current, listingTotal=shown_total, fetching=True)
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                page_records = []
                # bookmarks of a series or of a work off ao3: indexed in their own folders,
                # never downloaded, and never what a walk stops at
                page_series: list[dict] = []
                page_external: list[dict] = []
                reached_known = False
                for blurb in parse_soup.get_blurbs(thesoup):
                    kind, number = parse_soup.get_blurb_kind(blurb)
                    if kind in (parse_soup.BLURB_SERIES, parse_soup.BLURB_EXTERNAL) and \
                            (number or kind == parse_soup.BLURB_EXTERNAL):
                        key = parse_soup.get_blurb_id(blurb) or f'{kind}-{number}'
                        if key in seen: continue
                        seen.add(key)
                        if kind == parse_soup.BLURB_SERIES:
                            document = parse_soup.get_series_bookmark_metadata(blurb, number)
                            document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_SERIES
                            page_series.append(document)
                        else:
                            document = parse_soup.get_external_bookmark_metadata(blurb, number)
                            document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_EXTERNAL
                            page_external.append(document)
                        document['source'] = source
                        if own_bookmarks: document[strings.BOOKMARKED_FIELD] = True
                        continue
                    worknum = number if kind == parse_soup.BLURB_WORK else None
                    if not worknum:
                        skipped += 1
                        # why, not just how many - a count leaves no way to tell which
                        # bookmark was passed over or to go and look at it
                        self.skipped_works.append(parse_soup.get_blurb_skip_reason(blurb))
                        continue
                    if parse_soup.is_unrevealed_blurb(blurb):
                        # it still gets indexed below - it has a number and a place in the
                        # listing - but asking ao3 for the file would fail by definition
                        self.unrevealed.add(str(worknum))
                        self.skipped_works.append(
                            {'id': str(worknum),
                             'link': parse_soup.get_full_work_url('/works/' + str(worknum)) or '',
                             'title': parse_soup.get_text_or_empty(blurb, 'h4.heading'),
                             'error': strings.SKIPPED_UNREVEALED})

                    if known is not None and str(worknum) in known:
                        # the first fic we already hold. everything past it on this page,
                        # and every page after it, has been seen before
                        print(strings.AO3_INFO_REACHED_KNOWN)
                        reached_known = True
                        break

                    if stop_before:
                        # only sound on a listing sorted by this date - see the docstring
                        selector = ('div.user p.datetime' if stop_on == 'bookmarked'
                                    else 'div.header p.datetime')
                        updated = parse_text.get_date_stamp(parse_soup.get_text_or_empty(
                            blurb, selector))
                        if updated and updated < stop_before:
                            print(strings.AO3_INFO_REACHED_OLDER.format(stop_before))
                            reached_known = True
                            break
                    # a work can be bookmarked more than once, and can shift between pages
                    # while we're paging through, so dedupe on the bookmark rather than the work
                    key = parse_soup.get_blurb_id(blurb) or str(worknum)
                    if key in seen: continue
                    seen.add(key)
                    document = {'source': source}
                    document.update(parse_soup.get_blurb_metadata(blurb))
                    document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_WORK
                    if own_bookmarks: document[strings.BOOKMARKED_FIELD] = True
                    records.append(document)
                    page_records.append(document)
                # nothing is written until the whole page has been read. a page is one unit
                # of work: it is fetched, parsed and only then saved, so a page abandoned
                # partway leaves no half-built entries and simply gets asked for again.
                # saving as each blurb was parsed made the page half-written by definition
                for document in page_records:
                    self.save_metadata(document)
                for document in page_external:
                    self.save_entry(document, strings.EXTERNAL_INDEX_FOLDER_NAME)
                # a bookmarked series is read for its works once the page is written, so
                # works already on this page are not read again from the series; the ones it
                # indexes are downloaded with the rest, as the individual works they are
                for document in page_series:
                    records.extend(self.index_series(document))
                shown_total = None if open_ended else total_pages
                done, of = self.page_progress(current, shown_total)
                # two sets of numbers on purpose: the bar measures the slice being fetched,
                # so it runs 1..n and ends full, while the words say where that actually is
                # in the listing - 'page 42 of 80' is what you would go and look at
                progress.report(self.progress, progress.PAGE, page=done, total=of,
                                listingPage=current, listingTotal=shown_total,
                                works=len(records))
                # said as soon as the page is in, and before any decision to stop: this used
                # to sit after the break checks, so the page a run ended on - the last one
                # of the listing, or the one the page limit stopped at - never reported
                # finishing at all
                print(strings.AO3_INFO_METADATA_PAGE.format(
                          str(current), str(shown_total), str(len(records)))
                      if shown_total else
                      strings.AO3_INFO_METADATA_PAGE_ONLY.format(
                          str(current), str(len(records))))
                # the works ahead of the familiar or older one are still new, so they were kept
                # and written; it is only the walking that stops here. after the page has said
                # it finished, not before - a walk stopped by a floor used to end on 'fetching
                # page 4' and never report the page it had actually read
                if reached_known: break
                if not total_pages or current >= total_pages:
                    break
                link = parse_text.get_next_page(link)
                if self.pages and parse_text.get_page_number(link) == self.pages + 1:
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                    break
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


    def save_images(self, soup, filename: list[str] | str, work_url: str,
                    title: str) -> int:
        """Save the images embedded in a work's page as files of their own.

        These are `<img>` tags in the work's rendered html, usually pointing at somewhere
        else entirely. The downloaded work normally carries them inside it already - this
        writes a second, separate copy of each, for when the pictures themselves are what
        is wanted.

        One image that will not come down never ends the run: ao3 has no say over hosts it
        does not own, and a dead image link is the single most ordinary failure here. Each
        is logged and the rest carry on. Returns how many were saved.
        """

        counter = 0
        for img in parse_soup.get_image_links(soup):
            # a site-relative src is ao3's own furniture, not part of the work
            if str.startswith(img, '/'): continue
            try:
                ext = os.path.splitext(img)[1]
                if '?' in ext: ext = ext[:ext.index('?')]
                response = self.repo.get_book(img)
                imagefile = filename + ' img' + str(counter).zfill(3) + ext
                self.fileops.save_bytes(
                    os.path.join(strings.IMAGE_FOLDER_NAME, imagefile), response)
                counter += 1
            except Exception as e:
                self.fileops.write_log({
                    'message': strings.ERROR_IMAGE, 'link': work_url, 'title': title,
                    'img': img, 'error': str(e), 'stacktrace': traceback.format_exc()})
        return counter


    def save_images_for(self, record: dict, maximum: int) -> int:
        """Fetch one indexed work's page purely to save the images embedded in it.

        The indexed download path never reads a work page - that is the whole of what makes
        it cheap - so there is nothing for `get_image_links` to read. This fetches the page
        separately, *after* the files themselves are safely down, which costs one extra
        request per work and is why nothing does it unless asked.

        The url is built from the work number rather than taken from the record, for the
        same reason the download links are: the number is the only part that matters.
        """

        link = f'{strings.AO3_BASE_URL}/works/{record["id"]}'
        soup = self.proceed(self.repo.get_soup(link))
        title = parse_soup.apply_name_pattern(
            parse_soup.get_name_metadata_from_blurb(record), strings.FILE_NAME_PATTERN)
        filename = parse_text.get_valid_filename(
            title, maximum, parse_text.get_date_suffix(record.get('date_updated') or '')) \
            or str(record['id'])

        return self.save_images(soup, filename, link, ' / '.join(x for x in title if x))


    def index_one_work(self, link: str, existing: dict | None = None) -> dict:
        """Index a single fic from its own page, seen before or not.

        A work page and a bookmarks listing describe a fic differently, and the index is
        shaped by the listing. So an entry created here fills in only what a work page can
        honestly answer for - the title, the author, and the stats that get versioned - and
        leaves tags, the summary and the bookmark's own fields empty rather than inventing
        a second schema for them. A later bookmarks run fills those in, and `merge` treats
        it as the same document because the identity fields match.

        A fic already in the index keeps everything it has; only the stats are rewritten,
        exactly as `refresh_one` does.
        """

        soup = self.proceed(self.repo.get_soup(link))
        stats = parse_soup.get_work_stats(soup)
        if 'error' in stats:
            raise exceptions.Ao3DownloaderException(strings.ERROR_WORK_STATS)

        record = dict(existing or {})
        if not record:
            page = parse_soup.get_work_metadata_from_work(soup, link)
            authors = [x.strip() for x in (page.get('author') or '').split(',') if x.strip()]
            record = {'id': parse_text.get_work_number(link), 'link': link,
                      'title': page.get('title') or '', 'authors': authors}

        fresh = {**record, **stats, **bookmark_state(soup)}
        self.save_metadata(fresh)
        return fresh


    def refresh_one(self, record: dict) -> dict:
        """Re-read one fic from its own page and bring its index entry up to date.

        One request, going straight to the link the index already holds - no listing is
        walked to find it, because the index is the list.

        Only the fields a work page can speak to are written (see parse_soup.get_work_stats);
        the entry keeps the shape a bookmarks pass gave it, so tags and the bookmark's own
        fields are left as they were rather than half-overwritten from a page that says
        them differently.

        Returns the record as it now stands. Raises if the work cannot be read, which the
        caller turns into a recorded failure - the entry it already had stays as it was.
        """

        soup = self.proceed(self.repo.get_soup(record.get('link') or ''))
        stats = parse_soup.get_work_stats(soup)
        if 'error' in stats:
            raise exceptions.Ao3DownloaderException(strings.ERROR_WORK_STATS)

        fresh = {**record, **stats, **bookmark_state(soup)}
        self.save_metadata(fresh)
        return fresh


    def download_indexed(self, records: list[dict], visited: list[str] | None = None) -> None:
        """Download the works the index lists, without reading ao3's listing again.

        The index already holds every work number and everything needed to name a file, so
        this skips two things the long way round pays for: walking the listing pages a
        second time to rediscover links we already have, and fetching each work's page to
        read a download link that the work number already determines.

        The trade-off is that nothing looks at the work page, so a work that is locked,
        deleted or hidden is not recognised as such - it just fails to download and is
        logged. Anything that genuinely needs the page (embedded images, marking as read,
        following series links) goes the long way round instead; see server.can_use_index.
        """

        visited = visited or []
        maximum = self.fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        skip = set(visited)
        # an unrevealed work is held back rather than attempted: ao3 answers with a page
        # instead of a file, so the request is spent for certain and the run would report
        # it as a failure when nothing has actually gone wrong
        pending = [x for x in records
                   if x.get('id') and x.get('link') and x['link'] not in skip
                   and str(x['id']) not in self.unrevealed]

        print(strings.AO3_INFO_FROM_INDEX.format(len(pending)))

        for done, record in enumerate(pending, start=1):
            log: dict = {'link': record['link']}
            try:
                self.check_cancelled()
                self.download_one_indexed(record, maximum, log, done, len(pending))
            except exceptions.CancelledException:
                print(strings.INFO_CANCELLED)
                return
            except Exception as e:
                # one work that will not come down should not end the run - unless the
                # login has lapsed, in which case every work after it fails the same way
                self.check_session()
                self.record_failure(record['link'], e)
                self.log_error(log, e)


    def download_one_indexed(self, record: dict, maximum: int, log: dict,
                             done: int, total: int) -> None:
        """Fetch one work's files straight from its work number."""

        work = str(record['id'])
        title = parse_soup.apply_name_pattern(
            parse_soup.get_name_metadata_from_blurb(record), strings.FILE_NAME_PATTERN)
        updated = record.get('date_updated') or ''
        filename = parse_text.get_valid_filename(
            title, maximum, parse_text.get_date_suffix(updated)) or work

        log['title'] = title
        # the same two fields the long way round records, so the 'already downloaded' check
        # can rebuild this exact name next time
        log['updated'] = updated

        display = ' / '.join(x for x in title if x)
        failed: list[tuple[str, Exception]] = []
        for filetype in self.filetypes:
            self.check_cancelled()
            progress.report(self.progress, progress.WORK, title=display,
                            link=record['link'], filetype=filetype,
                            phase=progress.DOWNLOADING, done=done, total=total)
            with self.one_format(filetype, failed):
                content = self.repo.download_file(
                    parse_text.get_direct_download_link(work, filetype), filetype)
                self.save_download(record['link'], filetype,
                                   filename + parse_text.get_file_type(filetype), content)

        # anything that did arrive is a download, even when a format beside it failed
        if len(failed) < len(self.filetypes): self.downloaded.add(work)
        self.raise_if_formats_failed(failed)
        log['success'] = True
        self.fileops.write_log(log)


    @contextlib.contextmanager
    def one_format(self, filetype: str, failed: list[tuple[str, Exception]]):
        """Try one format of a work, noting a failure and carrying on to the next format.

        A work used to stop at its first failing format, so a fic ao3 had no epub for never
        got its pdf either, and the failure named only the first. Each format is a separate
        file at its own url, so one missing says nothing about the others.

        A stop and a lapsed login still end everything - every format after would fail the
        same way, and a stop means stop.
        """

        try:
            yield
        except (exceptions.CancelledException, exceptions.SessionExpiredException):
            raise
        except Exception as e:
            failed.append((filetype, e))
            print(strings.INFO_FORMAT_FAILED.format(filetype, e))


    def raise_if_formats_failed(self, failed: list[tuple[str, Exception]]) -> None:
        """Fail the work once every format has been tried, naming each one that failed.

        One exception for the lot, because a work is one entry in the failure list and a
        work already counted as failed would not be recorded a second time. It is a
        `SavedFileException` only if every failure was one, so a folder problem still does
        not spend a request checking the login - but a single ao3 failure among them does.
        """

        if not failed: return
        message = '; '.join(strings.ERROR_FORMAT_FAILED.format(ft, e) for ft, e in failed)
        if all(isinstance(e, exceptions.SavedFileException) for _, e in failed):
            raise exceptions.SavedFileException(message)
        raise exceptions.DownloadException(message)


    def page_progress(self, current: int, total_pages: int | None) -> tuple[int, int | None]:
        """Where a page sits in the slice being fetched, rather than in the whole listing.

        A run over pages 42 to 80 is fetching 39 pages, and the first of them is page 1 of
        39. Reporting it as 42 of 80 would start the bar at half full and leave it at 100%
        having fetched less than half the listing. The stop page counts too: pages 42 to 60
        is 19 pages, not 39.
        """

        done = current - self.start + 1
        if not total_pages: return done, None
        last = min(total_pages, self.pages) if self.pages else total_pages
        return done, max(1, last - self.start + 1)


    def walk_pages(self, link: str):
        """Yield each page of a paginated ao3 listing, following 'next' until it runs out."""

        total_pages = None
        while True:
            self.check_cancelled()
            soup = self.repo.get_soup(link)
            yield soup
            if total_pages is None:
                total_pages = parse_soup.get_total_pages(soup)
            pagenum = parse_text.get_page_number(link)
            if not total_pages or pagenum >= total_pages: break
            link = parse_text.get_next_page(link)
            if self.pages and parse_text.get_page_number(link) == self.pages + 1: break


    def collect_work_ids(self, link: str) -> list[str]:
        """Every work id on a listing, which is all a collection needs to record.

        The works themselves are described by the index in downloads/indexing, so there
        is nothing to gain from repeating their metadata here.
        """

        found: list[str] = []
        for soup in self.walk_pages(link):
            for blurb in parse_soup.get_blurbs(soup):
                work = parse_soup.get_blurb_work_number(blurb)
                if work and work not in found: found.append(work)
        return found


    def collect_collection_links(self, link: str) -> list[str]:
        """Every collection linked from a collections listing."""

        found: list[str] = []
        for soup in self.walk_pages(link):
            for blurb in parse_soup.get_collection_blurbs(soup):
                slug = parse_soup.get_collection_slug(blurb)
                if not slug: continue
                url = f'{strings.AO3_BASE_URL}/collections/{slug}'
                if url not in found: found.append(url)
        return found


    def get_collections(self, link: str) -> list[dict]:
        """Walk a user's collections and save each one to its own file.

        Each collection is written as it is finished, so stopping partway keeps whatever
        was already saved, the same as indexing bookmarks does.
        """

        if strings.AO3_BASE_URL not in link:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)

        source = link
        self.indexed_on = indexing.now()
        records: list[dict] = []

        try:
            for soup in self.walk_pages(link):
                for blurb in parse_soup.get_collection_blurbs(soup):
                    slug = parse_soup.get_collection_slug(blurb)
                    if not slug: continue
                    document = self.read_collection(slug, source, blurb)
                    records.append(document)
                    self.save_collection(document)
                    progress.report(self.progress, progress.WORK,
                                    title=document.get('title') or slug,
                                    phase=progress.COLLECTIONS, done=len(records))
                    print(strings.AO3_INFO_COLLECTION_SAVED.format(slug))
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
        except Exception as e:
            print(strings.ERROR_COLLECTIONS)
            self.log_error({'message': strings.ERROR_COLLECTIONS, 'link': link}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        return records


    def get_collection(self, link: str) -> list[dict]:
        """Index a single collection, given a link to any of its pages.

        Returns a list so a caller can treat this and get_collections alike. Costs one
        request for the profile plus the item listings, and skips those listings entirely
        when the counts say nothing has moved - the same as indexing your own collections.
        """

        if strings.AO3_BASE_URL not in link:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)
        slug = parse_text.get_collection_name(link)
        if not slug:
            raise exceptions.InvalidLinkException(strings.ERROR_NOT_A_COLLECTION)

        self.indexed_on = indexing.now()
        records: list[dict] = []

        try:
            print(strings.AO3_INFO_COLLECTION_ONE.format(slug))
            document = self.read_collection(slug, link)
            records.append(document)
            self.save_collection(document)
            progress.report(self.progress, progress.WORK,
                            title=document.get('title') or slug,
                            phase=progress.COLLECTIONS, done=1, total=1)
            print(strings.AO3_INFO_COLLECTION_SAVED.format(slug))
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
        except Exception as e:
            print(strings.ERROR_COLLECTIONS)
            self.log_error({'message': strings.ERROR_COLLECTIONS, 'link': link}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        return records


    def read_collection(self, slug: str, source: str, blurb=None) -> dict:
        """Everything one collection has to say, across its listing blurb and its pages.

        `blurb` is its entry in a collections listing, when the crawl came from one. There
        is none when a single collection is indexed by url, so the three things a blurb
        would have supplied - display title, description and flags - are read off the
        profile page instead, which carries all of them.
        """

        base = f'{strings.AO3_BASE_URL}/collections/{slug}'
        document = {'source': source, 'name': slug, 'link': base}
        if blurb is not None:
            document.update(parse_soup.get_collection_metadata(blurb))

        try:
            profile = self.repo.get_soup(f'{base}/profile')
            # only when there is no blurb: the listing is otherwise the established source
            # for these, and taking them from elsewhere would show up as a spurious change
            if blurb is None:
                document.update(parse_soup.get_collection_header(profile))
            document.update(parse_soup.get_collection_profile(profile))
        except exceptions.CancelledException:
            raise
        except Exception as e:
            self.log_error({'message': strings.ERROR_COLLECTION_PROFILE, 'link': base}, e)

        # what we already know about this collection, to avoid re-walking what has not moved
        previous = self.previous_collection(slug)

        for key, count_key, label, url in (
                ('work_ids', 'work_count', 'works', f'{base}/works'),
                ('bookmark_ids', 'bookmark_count', 'bookmarked items', f'{base}/bookmarks')):
            kept = self.unchanged_items(previous, document, key, count_key)
            if kept is not None:
                document[key] = kept
                print(strings.AO3_INFO_COLLECTION_UNCHANGED.format(slug, len(kept), label))
                continue
            try:
                document[key] = self.collect_work_ids(url)
            except exceptions.CancelledException:
                raise
            except Exception as e:
                document[key] = []
                self.log_error({'message': strings.ERROR_COLLECTION_ITEMS, 'link': url}, e)

        # only worth asking for when the sidebar says there are some
        document['subcollections'] = []
        if document.get('subcollection_count'):
            kept = self.unchanged_items(previous, document, 'subcollections',
                                        'subcollection_count')
            if kept is not None:
                document['subcollections'] = kept
                print(strings.AO3_INFO_COLLECTION_UNCHANGED.format(
                    slug, len(kept), 'subcollections'))
            else:
                try:
                    document['subcollections'] = self.collect_collection_links(
                        document.get('subcollections_link') or f'{base}/collections')
                except exceptions.CancelledException:
                    raise
                except Exception as e:
                    self.log_error({'message': strings.ERROR_COLLECTION_ITEMS, 'link': base}, e)

        return document


    def previous_collection(self, name: str) -> dict:
        """The newest reading of this collection from an earlier run, or nothing.

        A missing or unreadable file is not a problem: it only means there is nothing to
        reuse, and everything gets fetched as it would on a first run.
        """

        try:
            stored = self.fileops.load_json(self.collection_path(name))
        except Exception:
            return {}
        if not isinstance(stored, dict): return {}

        readings = stored.get(indexing.INDEXES)
        if isinstance(readings, list) and readings and isinstance(readings[-1], dict):
            # identity lives at the root and is not versioned, so it goes back on top
            return {**readings[-1], **stored}
        return stored


    def unchanged_items(self, previous: dict, document: dict,
                        key: str, count_key: str) -> list | None:
        """The ids saved last time, when the count says a crawl would find the same ones.

        Walking a collection's works costs one request per twenty of them, so a large
        collection runs to hundreds of requests - by far the most expensive thing this
        does. Ao3 puts the total on the profile page we have already fetched, so an
        unchanged total is enough to keep what we have.

        Returns None whenever anything is uncertain, which means fetch it properly: no
        saved list, an empty one, or a count missing from either side.

        A partly-gathered list is never saved, so it cannot be reused: a stop raises out
        of read_collection before anything is written, and a failed crawl stores an empty
        list, which is rejected here. The length of the list is deliberately not compared
        against the count - a listing can hold bookmarks of series and external works,
        which have no work number and so are counted by ao3 but not recorded here.

        The one thing this cannot see is a collection that had a work added and another
        removed between runs, leaving the total the same. Delete its json file to force a
        full crawl.
        """

        saved = previous.get(key)
        if not isinstance(saved, list) or not saved: return None

        count = document.get(count_key)
        if count is None or count != previous.get(count_key): return None

        return list(saved)


    def collection_path(self, name: str) -> str:
        """Where one collection's file lives, named the same way everything else is."""

        maximum = self.fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        filename = parse_text.get_valid_filename([name], maximum) or name
        return os.path.join(
            strings.COLLECTIONS_FOLDER_NAME,
            filename + parse_text.get_file_type(strings.AO3_DOWNLOAD_TYPE_METADATA))


    def save_collection(self, document: dict) -> None:
        """Write one collection to its own json file, keeping its history."""

        try:
            path = self.collection_path(document.get('name') or 'collection')
            merged = indexing.merge(self.fileops.load_json(path), document, self.indexed_on,
                                    indexing.COLLECTION_IDENTITY_FIELDS)
            self.fileops.save_json(path, merged)
        except Exception as e:
            self.log_error({'message': strings.ERROR_COLLECTION_SAVE,
                            'link': document.get('link')}, e)


    def metadata_path(self, document: dict, subfolder: str = '') -> str:
        """Where one entry's json lives: named with the same pattern as a downloaded work,
        so a fic's metadata carries the same name as its epub or html, in indexing/ - or in
        a folder inside it, for the entries that are not works."""

        pattern = strings.FILE_NAME_PATTERN
        maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        name = parse_soup.apply_name_pattern(parse_soup.get_name_metadata_from_blurb(document), pattern)
        filename = parse_text.get_valid_filename(name, maximum)
        # a pattern can resolve to nothing if every field it uses is empty
        if not filename: filename = str(document.get('id') or 'bookmark')
        return os.path.join(
            strings.INDEXING_FOLDER_NAME, *([subfolder] if subfolder else []),
            filename + parse_text.get_file_type(strings.AO3_DOWNLOAD_TYPE_METADATA))


    def save_metadata(self, document: dict) -> None:
        """Write one work to its own json file, in the indexing subfolder."""

        try:
            path = self.metadata_path(document)
            # keep whatever readings the file already holds, and add this one only if it
            # says something new
            merged = indexing.merge(self.fileops.load_json(path), document, self.indexed_on)
            self.fileops.save_json(path, merged)
            if document.get('id'): self.reindexed.add(str(document['id']))
        except Exception as e:
            # one unwritable file shouldn't end the run
            self.log_error({'message': strings.ERROR_METADATA_SAVE, 'link': document.get('link')}, e)


    def save_entry(self, document: dict, subfolder: str) -> None:
        """Write a bookmark that is not a work - a series, an external work - to its folder
        inside indexing/, keeping its history the way a work's file does."""

        try:
            path = self.metadata_path(document, subfolder)
            merged = indexing.merge(self.fileops.load_json(path), document, self.indexed_on)
            self.fileops.save_json(path, merged)
        except Exception as e:
            self.log_error({'message': strings.ERROR_METADATA_SAVE, 'link': document.get('link')}, e)


    def index_series(self, series: dict) -> list[dict]:
        """Write a bookmarked series' own entry, and index every work in it.

        The series' page lists its works with the same blurbs a bookmarks listing uses, 20
        to a page, so a series costs a request per 20 works. For each work on it:

        - **already indexed this run** - a work bookmarked in its own right, read off the
          listing a moment ago - it is left alone. It is not read twice.
        - **otherwise** it is indexed from the series page (`save_series_work`), keeping
          what its entry already says about your own bookmark of it.

        Returns the works it indexed, so they are downloaded with the rest of the run.
        """

        series_id = str(series.get('id') or '')
        title = series.get('title') or series_id
        if series_id in self.series_read:
            print(strings.AO3_INFO_SERIES_AGAIN.format(title))
            series[strings.SERIES_WORKS_FIELD] = self.series_read[series_id]
            self.save_entry(series, strings.SERIES_INDEX_FOLDER_NAME)
            return []

        print(strings.AO3_INFO_SERIES_READING.format(title))
        found: list[str] = []
        indexed: list[dict] = []
        already = 0
        link = series.get('link') or f'{strings.AO3_BASE_URL}/series/{series_id}'
        page = link
        try:
            total = None
            while True:
                self.check_cancelled()
                soup = self.repo.get_soup(page)
                if total is None: total = parse_soup.get_total_pages(soup)
                readings = []
                for blurb in parse_soup.get_blurbs(soup):
                    kind, work = parse_soup.get_blurb_kind(blurb)
                    if kind != parse_soup.BLURB_WORK or not work or work in found: continue
                    found.append(work)
                    if work in self.reindexed:
                        already += 1
                        continue
                    readings.append(parse_soup.get_blurb_metadata(blurb))
                # a page at a time, as a listing is written
                for document in readings:
                    indexed.append(self.save_series_work(document, series_id, link))
                if not total or parse_text.get_page_number(page) >= total: break
                page = parse_text.get_next_page(page)
            series[strings.SERIES_WORKS_FIELD] = found
            self.series_read[series_id] = found
            print(strings.AO3_INFO_SERIES_READ.format(len(found), len(indexed), already))
        except exceptions.CancelledException:
            raise
        except Exception as e:
            # a series that will not read keeps the works list it had, rather than being
            # recorded as holding only the ones reached before it failed
            print(strings.ERROR_SERIES)
            self.log_error({'message': strings.ERROR_SERIES, 'link': link}, e)
            previous = indexing.flatten(self.fileops.load_json(
                self.metadata_path(series, strings.SERIES_INDEX_FOLDER_NAME))) or {}
            if strings.SERIES_WORKS_FIELD in previous:
                series[strings.SERIES_WORKS_FIELD] = previous[strings.SERIES_WORKS_FIELD]
        self.save_entry(series, strings.SERIES_INDEX_FOLDER_NAME)
        return indexed


    def save_series_work(self, document: dict, series_id: str, series_link: str) -> dict:
        """Index one work read off a bookmarked series' page.

        A series page knows the work but nothing about your own bookmark of it, so an
        entry that already exists keeps its bookmark fields as they were - whether you
        bookmarked it, when, your notes and tags - and its source. A new one is recorded as
        **not bookmarked**: it is in the index because of the series. If the same run then
        meets it in your bookmarks listing, that reading says bookmarked, as any does.
        """

        existing = indexing.flatten(self.fileops.load_json(self.metadata_path(document))) or {}
        for field in strings.BOOKMARK_OWN_FIELDS:
            if field in existing: document[field] = existing[field]
        document.setdefault(strings.BOOKMARKED_FIELD, False)
        document['source'] = existing.get('source') or series_link
        document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_WORK
        document[indexing.FROM_SERIES] = [series_id]
        self.save_metadata(document)
        return document


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
                    done, of = self.page_progress(pagenum - 1, total_pages)
                    progress.report(self.progress, progress.PAGE, page=done, total=of,
                                    listingPage=pagenum - 1, listingTotal=total_pages)
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
            self.check_session()
            self.record_failure(link, e)
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
        
        maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        title = parse_soup.get_title(thesoup, work_url, strings.FILE_NAME_PATTERN)
        # the name ends in the date the work was last updated, so a file says which version
        # of a fic it holds. the title is cut short to leave room for it rather than the
        # other way round.
        updated = parse_soup.get_updated_date(thesoup)
        filename = parse_text.get_valid_filename(title, maximum, parse_text.get_date_suffix(updated))
        log['title'] = title
        # recorded so the same name can be rebuilt when checking what is already downloaded
        log['updated'] = updated
        log['workskin'] = parse_soup.has_custom_skin(thesoup)

        # what is being fetched right now, so the ui can name the fic and the format
        display = ' / '.join(x for x in title if x)
        progress.report(self.progress, progress.WORK, title=display, link=work_url,
                        phase='downloading')

        failed: list[tuple[str, Exception]] = []
        for filetype in self.filetypes:
            self.check_cancelled()
            progress.report(self.progress, progress.WORK, title=display, link=work_url,
                            filetype=filetype, phase='downloading')
            with self.one_format(filetype, failed):
                link = parse_soup.get_download_link(thesoup, filetype)
                response = self.repo.get_book(link)
                self.save_download(work_url, filetype,
                                   filename + parse_text.get_file_type(filetype), response)

        if self.images:
            self.save_images(thesoup, filename, work_url, title)

        if self.mark:
            self.repo.mark_work_as_read(thesoup, work_url)

        self.raise_if_formats_failed(failed)

        return True


    def save_download(self, work_url: str, filetype: str, name: str, content: bytes) -> str:
        """Write one downloaded format, tidy up what it replaced, and say which happened.

        Both download paths come through here, so every file a run writes gets exactly one
        line in the modal. Only a deleted older copy used to be announced - a format arriving
        for the first time, or a copy overwritten under the same name, said nothing, and a
        run downloading hundreds of new files looked as though it was doing nothing at all.
        """

        # into works/, never the top level - that is the only place anything looks for them
        name = os.path.join(strings.WORKS_FOLDER_NAME, name)
        try:
            existed = self.fileops.is_file(os.path.join(self.fileops.downloadfolder, name))
        except Exception:
            # only decides the wording. a folder that cannot be asked is not a failed download
            existed = False

        saved = self.fileops.save_bytes(name, content)
        new = os.path.basename(saved) if isinstance(saved, str) else name
        work = parse_text.get_work_number(work_url)
        old = self.superseded.get(work_url, {}).get(filetype)
        try:
            # a separate older file, as opposed to the one this write has just landed on top of
            separate = bool(old) and not self.fileops.same_file(old, saved)
        except Exception:
            separate = False
        old_name = os.path.basename(old) if separate else ''

        # the new file is checked before anything else happens, and for every download - a
        # first download can be cut short or snatched by a sync tool as easily as a
        # replacement can, and a short file named as current would be judged current forever
        try:
            intact = self.fileops.saved_intact(saved, len(content))
        except Exception as e:
            # cannot tell either way: leave everything where it is, and say so
            self.log_error({'message': strings.ERROR_REPLACE_OLD_COPY, 'link': work_url}, e)
            print(strings.INFO_UNCONFIRMED.format(new))
            self.note_kept(work, work_url, new, old_name,
                           strings.UNCONFIRMED_REASON.format(new, e))
            return saved

        if not intact:
            self.discard_damaged(work_url, saved, new, old_name, len(content))

        outcome, _, reason = self.replace_superseded(work_url, filetype, saved, len(content))

        if outcome == REPLACED:
            print(strings.INFO_REPLACED_OLD_COPY.format(new))
        elif outcome == KEPT:
            print(strings.INFO_KEPT_OLD_COPY.format(new))
            self.note_kept(work, work_url, new, old_name, reason)
        elif outcome == UNCONFIRMED:
            print(strings.INFO_UNCONFIRMED.format(new))
            self.note_kept(work, work_url, new, old_name, reason)
        elif existed:
            # same name, so the write itself was the replacement - which is still an update
            if work: self.updated.add(work)
            print(strings.INFO_REPLACED_OLD_COPY.format(new))
        else:
            print(strings.INFO_SAVED_NEW_COPY.format(new))
        return saved


    def note_kept(self, work: str | None, work_url: str, new: str, old: str,
                  reason: str) -> None:
        """Remember a download that arrived but needs a person to look at it.

        The same {id, link, error} shape a failure has, so it reports and exports the same
        way - plus both file names, because there may now be two copies to find.
        """

        self.kept_copies.append({'id': work or '', 'link': work_url, 'file': new,
                                 'old': old, 'error': reason})


    def discard_damaged(self, work_url: str, saved: str, new: str, old_name: str,
                        size: int) -> None:
        """Remove a download that is not on disk as it arrived, and fail the work with why.

        A missing or short file must not stay: its name carries the current date, so every
        later run would call it up to date and never fetch it again. Any older copy is left
        exactly where it is. Raises `SavedFileException`, so the caller records a failure
        and the work is not counted as downloaded.
        """

        problem = self.fileops.saved_problem(saved, size)
        if not isinstance(problem, str) or not problem:
            problem = strings.SAVED_FINE_ON_SECOND_LOOK
        removed = self.fileops.delete_file(saved) is True

        if old_name:
            print(strings.INFO_DAMAGED_KEPT_OLD.format(old_name))
            detail = strings.DAMAGED_REASON_KEPT_OLD.format(new, problem, old_name)
        else:
            print(strings.INFO_DAMAGED_REMOVED.format(new))
            detail = strings.DAMAGED_REASON.format(new, problem)
        if not removed: detail += strings.DAMAGED_NOT_REMOVED
        raise exceptions.SavedFileException(detail)


    def replace_superseded(self, work_url: str, filetype: str,
                           saved_path: str, size: int) -> tuple[str | None, str]:
        """Remove the copy a download has just replaced, once it is safe to.

        Deliberately cautious, because the alternative is losing a file the user still has
        and we no longer have. Four things all have to hold:

          - there was an older copy recorded for this work
          - it is the *same* file type. re-downloading the html must never remove the epub
          - the new file is not the old one under a different name - if the name did not
            change there is nothing to remove, the write already replaced it
          - the new file is on disk, in the folder in use, at its full length

        Anything short of that leaves the old file exactly where it is.

        Returns what happened - `REPLACED`, `KEPT` (would not delete), `UNCONFIRMED` (the new
        file could not be vouched for) or None (nothing older to remove) - with the old
        file's name and, when not replaced, why. It prints nothing itself, or a replacement
        would be announced twice; `save_download` does the saying. `save_download` checks the
        new file before calling this, so the check here is a second line of defence.
        """

        old = self.superseded.get(work_url, {}).get(filetype)
        if not old: return None, '', ''
        name = os.path.basename(old)
        new = os.path.basename(saved_path) if isinstance(saved_path, str) else ''

        try:
            if os.path.abspath(old) == os.path.abspath(saved_path): return None, '', ''
            if not self.fileops.saved_intact(saved_path, size):
                self.fileops.write_log({
                    'link': work_url, 'message': strings.INFO_UNCONFIRMED.format(saved_path),
                    'old': old, 'level': 'debug'})
                return UNCONFIRMED, name, strings.UNCONFIRMED_REASON.format(
                    new, strings.SAVED_FINE_ON_SECOND_LOOK)
            if self.fileops.delete_file(old):
                # an old copy actually gone is what makes this an update rather than a
                # first download, which is the distinction the history file records
                work = parse_text.get_work_number(work_url)
                if work: self.updated.add(work)
                self.fileops.write_log({
                    'link': work_url, 'message': strings.INFO_REPLACED_OLD_COPY.format(old),
                    'level': 'debug'})
                return REPLACED, name, ''
            return KEPT, name, strings.KEPT_NOT_DELETED.format(name)
        except Exception as e:
            # never let tidying up an old file break a download that succeeded
            self.log_error({'message': strings.ERROR_REPLACE_OLD_COPY, 'link': work_url}, e)
            return UNCONFIRMED, name, strings.UNCONFIRMED_REASON.format(new, e)


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


    def check_session(self) -> None:
        """End the run if ao3 has stopped recognising the login it started with.

        A lapsed session does not announce itself. Ao3 simply serves the logged-out view,
        so a restricted work comes back as a page instead of a file and
        `repo.download_file` rejects it - the same failure a deleted work produces. The
        difference is that a lapsed session fails *everything* from then on.

        So the check is made only when a download has already failed, and **only once per
        run**: it costs a request, and asking again after each of four hundred failures
        would cost four hundred. If the session is alive this is a per-work failure like
        any other and the run carries on.
        """

        # always called from an except block, so the exception being handled is the current
        # one. a damaged file on disk says nothing about the login - don't pay to ask
        if isinstance(sys.exc_info()[1], exceptions.SavedFileException): return
        if self.session_checked: return
        self.session_checked = True
        if self.repo.still_logged_in(): return
        raise exceptions.SessionExpiredException(strings.ERROR_SESSION_EXPIRED)


    def record_failure(self, link: str, exception: Exception) -> None:
        """Remember a work that would not come down, so the run can say so at the end.

        Recorded once per work rather than once per file type: a work that fails usually
        fails for every format, and a list with the same number in it five times is worse
        than useless for feeding back in.
        """

        work = parse_text.get_work_number(link or '')
        if any(x['link'] == link for x in self.failures): return
        self.failures.append({'id': work, 'link': link, 'error': str(exception)})


    def log_error(self, log: dict, exception: Exception):
        log['error'] = str(exception)
        log['success'] = False
        if not isinstance(exception, exceptions.Ao3DownloaderException):
            log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(exception).format())
        self.fileops.write_log(log)
