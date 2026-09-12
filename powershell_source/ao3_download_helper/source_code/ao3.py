"""Download works from ao3."""

import datetime
import os
import traceback
from collections.abc import Callable

from bs4 import BeautifulSoup

from source_code import exceptions, indexing, parse_soup, parse_text, progress, strings
from source_code.fileio import FileOps
from source_code.progress import ProgressCallback
from source_code.repo import Repository


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
        # bookmarks that are not works at all, so could never be indexed or downloaded.
        # kept as a list rather than a count so the run can name each one at the end
        self.skipped_works: list[dict] = []
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
                     known: set[str] | None = None) -> list[dict]:
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
        # positions are places in the whole listing, so a run starting at page 5 carries on
        # from where page 4 left off rather than numbering its first fic 1. ao3 serves
        # listings 20 to a page, which is what makes the pages before this one countable.
        position_offset = (self.start - 1) * strings.AO3_LISTING_PAGE_SIZE
        # one timestamp for the whole run, so every file this run touches agrees on when
        # it was indexed, and a second save of the same fic updates rather than appends
        self.indexed_on = indexing.now()

        records: list[dict] = []
        seen: set[str] = set()
        skipped = 0
        total_pages = None

        try:
            while True:
                self.check_cancelled()
                current = parse_text.get_page_number(link)
                print(strings.AO3_INFO_METADATA_FETCHING.format(str(current), str(total_pages))
                      if total_pages else
                      strings.AO3_INFO_METADATA_FETCHING_FIRST.format(str(current)))
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                page_records = []
                reached_known = False
                for blurb in parse_soup.get_blurbs(thesoup):
                    worknum = parse_soup.get_blurb_work_number(blurb)
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
                    # a work can be bookmarked more than once, and can shift between pages
                    # while we're paging through, so dedupe on the bookmark rather than the work
                    key = parse_soup.get_blurb_id(blurb) or str(worknum)
                    if key in seen: continue
                    seen.add(key)
                    document = {
                        'source': source,
                        # the listing order, which is the order ao3 shows the bookmarks in
                        'position': position_offset + len(records) + 1,
                    }
                    document.update(parse_soup.get_blurb_metadata(blurb))
                    records.append(document)
                    page_records.append(document)
                # nothing is written until the whole page has been read. a page is one unit
                # of work: it is fetched, parsed and only then saved, so a page abandoned
                # partway leaves no half-built entries and simply gets asked for again.
                # saving as each blurb was parsed made the page half-written by definition
                for document in page_records:
                    self.save_metadata(document)
                # the works ahead of the familiar one are still new, so they are kept and
                # written; it is only the walking that stops here
                if reached_known: break
                done, of = self.page_progress(current, total_pages)
                # two sets of numbers on purpose: the bar measures the slice being fetched,
                # so it runs 1..n and ends full, while the words say where that actually is
                # in the listing - 'page 42 of 80' is what you would go and look at
                progress.report(self.progress, progress.PAGE, page=done, total=of,
                                listingPage=current, listingTotal=total_pages,
                                works=len(records))
                # said as soon as the page is in, and before any decision to stop: this used
                # to sit after the break checks, so the page a run ended on - the last one
                # of the listing, or the one the page limit stopped at - never reported
                # finishing at all
                print(strings.AO3_INFO_METADATA_PAGE.format(
                          str(current), str(total_pages), str(len(records)))
                      if total_pages else
                      strings.AO3_INFO_METADATA_PAGE_ONLY.format(
                          str(current), str(len(records))))
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

        fresh = {**record, **stats}
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

        fresh = {**record, **stats}
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
                # one work that will not come down should not end the run
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
        for filetype in self.filetypes:
            self.check_cancelled()
            progress.report(self.progress, progress.WORK, title=display,
                            link=record['link'], filetype=filetype,
                            phase=progress.DOWNLOADING, done=done, total=total)
            content = self.repo.download_file(
                parse_text.get_direct_download_link(work, filetype), filetype)
            saved = self.fileops.save_bytes(
                filename + parse_text.get_file_type(filetype), content)
            self.replace_superseded(record['link'], filetype, saved, len(content))

        log['success'] = True
        self.fileops.write_log(log)


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


    def save_metadata(self, document: dict) -> None:
        """Write one bookmark to its own json file, in the indexing subfolder.

        Named with the same pattern as a downloaded work, so a fic's metadata carries the
        same name as its epub or html - it just sits in indexing/ rather than beside them,
        which keeps the downloads folder to actual works.
        """

        try:
            pattern = strings.FILE_NAME_PATTERN
            maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
            name = parse_soup.apply_name_pattern(parse_soup.get_name_metadata_from_blurb(document), pattern)
            filename = parse_text.get_valid_filename(name, maximum)
            # a pattern can resolve to nothing if every field it uses is empty
            if not filename: filename = str(document.get('id') or document.get('position'))
            path = os.path.join(
                strings.INDEXING_FOLDER_NAME,
                filename + parse_text.get_file_type(strings.AO3_DOWNLOAD_TYPE_METADATA))

            # keep whatever readings the file already holds, and add this one only if it
            # says something new
            merged = indexing.merge(self.fileops.load_json(path), document, self.indexed_on)
            self.fileops.save_json(path, merged)
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

        for filetype in self.filetypes:
            self.check_cancelled()
            progress.report(self.progress, progress.WORK, title=display, link=work_url,
                            filetype=filetype, phase='downloading')
            link = parse_soup.get_download_link(thesoup, filetype)
            response = self.repo.get_book(link)
            saved = self.fileops.save_bytes(
                filename + parse_text.get_file_type(filetype), response)
            self.replace_superseded(work_url, filetype, saved, len(response))

        if self.images:
            self.save_images(thesoup, filename, work_url, title)

        if self.mark:
            self.repo.mark_work_as_read(thesoup, work_url)

        return True


    def replace_superseded(self, work_url: str, filetype: str,
                           saved_path: str, size: int) -> None:
        """Remove the copy a download has just replaced, once it is safe to.

        Deliberately cautious, because the alternative is losing a file the user still has
        and we no longer have. Four things all have to hold:

          - there was an older copy recorded for this work
          - it is the *same* file type. re-downloading the html must never remove the epub
          - the new file is not the old one under a different name - if the name did not
            change there is nothing to remove, the write already replaced it
          - the new file is on disk, in the folder in use, at its full length

        Anything short of that leaves the old file exactly where it is.
        """

        old = self.superseded.get(work_url, {}).get(filetype)
        if not old: return

        try:
            if os.path.abspath(old) == os.path.abspath(saved_path): return
            if not self.fileops.saved_intact(saved_path, size):
                self.fileops.write_log({
                    'link': work_url, 'message': strings.INFO_KEPT_OLD_COPY.format(old),
                    'level': 'debug'})
                return
            if self.fileops.delete_file(old):
                print(strings.INFO_REPLACED_OLD_COPY.format(os.path.basename(old)))
                self.fileops.write_log({
                    'link': work_url, 'message': strings.INFO_REPLACED_OLD_COPY.format(old),
                    'level': 'debug'})
            else:
                print(strings.INFO_KEPT_OLD_COPY.format(os.path.basename(old)))
        except Exception as e:
            # never let tidying up an old file break a download that succeeded
            self.log_error({'message': strings.ERROR_REPLACE_OLD_COPY, 'link': work_url}, e)


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
