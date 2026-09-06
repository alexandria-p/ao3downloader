from pypdf import PageObject

from source_code import exceptions, strings


def get_lines_pdf(pages: list[PageObject]) -> list[str]:
    '''extract text from pdf pages as a list of lines'''
    try:
        text = '\n'.join(page.extract_text() for page in pages)
    except Exception as e:
        raise exceptions.PdfParsingException(strings.ERROR_PDF_PARSE) from e
    return text.splitlines()


def get_work_link_pdf(lines: list[str]) -> str | None:
    # assumption: work link is on the same line as preceding text. probably fine. ¯\_(ツ)_/¯
    linktext = next((line for line in lines if 'Posted originally on the Archive of Our Own at ' in line), '')
    workindex = linktext.find('/works/')
    if workindex == -1: return None
    endindex = linktext.find('.', workindex)
    if endindex == -1: return None
    worknumber = linktext[workindex:endindex]
    if worknumber: return strings.AO3_BASE_URL + worknumber
    return None


def get_stats_pdf(lines: list[str]) -> str | None:

    # assumption: the exact text 'Chapters:' only appears once in the intro
    # and this indicates the chapter count will be on this or the next line
    index = next((i for i, line in enumerate(lines) if 'Chapters:' in line), None)

    # if we couldn't find any chapter data, return nothing
    if index is None: return None

    chapterstext = lines[index].strip()

    # if the chapter data is all on this line, return it
    if (
        not chapterstext.find('/') == -1 and # chapter count exists on this line
        not chapterstext.endswith('/') # and it includes the remaining chapters
    ): return chapterstext

    # insert whitespace after colon if there wasn't any
    if chapterstext.endswith(':'): chapterstext = chapterstext + ' '

    # append the next line since (full) chapter count wasn't on the previous line
    nextline = lines[index + 1].strip() if index + 1 < len(lines) else ''

    return chapterstext + nextline


def get_series_pdf(pages: list[PageObject]) -> list[str]:
    links = []
    for page in pages:
        annotations = page.get('/Annots')
        if annotations is None: continue
        for annotation in annotations.get_object():
            action = annotation.get_object().get('/A')
            if action is None: continue
            uri = action.get_object().get('/URI')
            if uri is not None: links.append(str(uri))
    series = filter(lambda x: 'archiveofourown.org/series/' in x, links)
    return list(series)
