from source_code import strings
from source_code.actions import shared
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository


def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        filetypes = shared.download_types(fileops)
        series = shared.series()
        images = shared.images()

        shared.ao3_login(repo, fileops, True)

        link = shared.marked_for_later_link(fileops)
        visited = shared.visited(fileops, filetypes)

        print(strings.AO3_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, filetypes, 0, series, images, True)
        ao3.download(link, visited)
