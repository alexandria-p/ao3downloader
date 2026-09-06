import os

from source_code import strings
from source_code.actions import shared
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository


def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        filetypes = shared.download_types(fileops, allow_metadata=True)

        # JSON isn't a format ao3 will hand us a work in - it means "export what the
        # listing knows about these works" - so it runs as its own pass over the link.
        metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in filetypes
        downloadtypes = [x for x in filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]

        series = shared.series() if downloadtypes else False
        link = shared.link(fileops)
        pages = shared.pages()
        images = shared.images() if downloadtypes else False
        workdates = shared.metadata_work_dates() if metadata else False

        shared.ao3_login(repo, fileops)

        # an empty filetype list would make every work look like it was already
        # downloaded, so only build the skip list when we're actually downloading
        visited = shared.visited(fileops, downloadtypes) if downloadtypes else []

        ao3 = Ao3(repo, fileops, downloadtypes, pages, series, images)

        if metadata:
            print(strings.AO3_INFO_METADATA)
            print(strings.AO3_INFO_METADATA_INCREMENTAL)
            records = ao3.get_metadata(link, workdates)
            if records:
                print(strings.AO3_INFO_METADATA_WRITTEN.format(
                    str(len(records)), os.path.abspath(fileops.downloadfolder)))
            else:
                print(strings.AO3_INFO_METADATA_NONE)

        if downloadtypes:
            print(strings.AO3_INFO_DOWNLOADING)
            ao3.download(link, visited)


