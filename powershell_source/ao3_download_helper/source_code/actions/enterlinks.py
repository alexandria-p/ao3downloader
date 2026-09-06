from source_code import strings
from source_code.actions import shared
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository

from tqdm import tqdm

def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        filetypes = shared.download_types(fileops)
        images = shared.images()
        path = shared.links_file()
        
        with open(path) as f:
            links = f.readlines()

        shared.ao3_login(repo, fileops)

        visited = shared.visited(fileops, filetypes)

        print(strings.AO3_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, filetypes, 0, True, images)
        for link in tqdm(links):
            ao3.download(link.strip(), visited)
