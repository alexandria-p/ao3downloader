"""Tests for ao3downloader.parse_pdf — PDF metadata extraction."""

import glob
import os
from unittest.mock import MagicMock

import pytest
from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from ao3downloader import exceptions, parse_pdf

from test.conftest import EBOOK_DIR, ebook_fixtures


def _load_pages(path: str) -> list[PageObject]:
    return list(PdfReader(path).pages[:3])


def _load_lines(path: str) -> list[str]:
    return parse_pdf.get_lines_pdf(_load_pages(path))


def _ids(paths):
    return [os.path.basename(p) for p in paths]


def _annotation(uri: str | None = None) -> DictionaryObject:
    """Build a link annotation like the ones AO3 pdfs use for series links."""
    annotation = DictionaryObject()
    if uri is not None:
        action = DictionaryObject()
        action[NameObject('/URI')] = TextStringObject(uri)
        annotation[NameObject('/A')] = action
    return annotation


def _page_with_annotations(annotations: list[DictionaryObject]) -> PageObject:
    page = PageObject.create_blank_page(width=612, height=792)
    page[NameObject('/Annots')] = ArrayObject(annotations)
    return page


# region fixture snapshots

_CURRENT_PDFS = sorted(glob.glob(os.path.join(EBOOK_DIR, '*', 'current', '*.pdf')))


@pytest.mark.parametrize('path', _CURRENT_PDFS, ids=_ids(_CURRENT_PDFS))
def test_extracted_metadata_snapshot(path, snapshot):
    """Pin the exact metadata extracted from every current pdf fixture."""
    pages = _load_pages(path)
    lines = parse_pdf.get_lines_pdf(pages)

    assert {
        'link': parse_pdf.get_work_link_pdf(lines),
        'stats': parse_pdf.get_stats_pdf(lines),
        'series': parse_pdf.get_series_pdf(pages),
    } == snapshot

# endregion


# region get_lines_pdf

def test_get_lines_pdf_wraps_extraction_errors():
    page = MagicMock()
    page.extract_text.side_effect = Exception('boom')

    with pytest.raises(exceptions.PdfParsingException):
        parse_pdf.get_lines_pdf([page])

# endregion


# region get_work_link_pdf

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.pdf'),
                         ids=_ids(ebook_fixtures('23009290', '.pdf')))
def test_get_work_link_pdf_extracts_url_from_real_fixture(path):
    link = parse_pdf.get_work_link_pdf(_load_lines(path))

    assert link is not None
    assert 'archiveofourown.org/works/' in link


def test_get_work_link_pdf_returns_none_when_marker_text_missing():
    assert parse_pdf.get_work_link_pdf(['some text', 'that is not', 'an ao3 preface']) is None
    assert parse_pdf.get_work_link_pdf([]) is None

# endregion


# region get_stats_pdf

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.pdf'),
                         ids=_ids(ebook_fixtures('23009290', '.pdf')))
def test_get_stats_pdf_returns_chapters_when_on_same_line(path):
    stats = parse_pdf.get_stats_pdf(_load_lines(path))

    assert stats is not None
    assert 'Chapters:' in stats
    assert '/' in stats


@pytest.mark.parametrize('path', ebook_fixtures('20907563', '.pdf'),
                         ids=_ids(ebook_fixtures('20907563', '.pdf')))
def test_get_stats_pdf_appends_next_line_for_multi_line_stats(path):
    result = parse_pdf.get_stats_pdf(_load_lines(path))

    assert result is not None
    assert 'Chapters:' in result
    assert '/' in result


def test_get_stats_pdf_returns_line_when_chapter_count_complete():
    assert parse_pdf.get_stats_pdf(['Words: 100 Chapters: 3/10', 'next line']) == 'Words: 100 Chapters: 3/10'


def test_get_stats_pdf_inserts_space_after_colon_when_missing():
    assert parse_pdf.get_stats_pdf(['Chapters:', '3/10']) == 'Chapters: 3/10'


def test_get_stats_pdf_appends_next_line_when_total_chapters_missing():
    assert parse_pdf.get_stats_pdf(['Chapters: 3/', '10']) == 'Chapters: 3/10'


def test_get_stats_pdf_handles_chapters_marker_on_last_line():
    assert parse_pdf.get_stats_pdf(['Chapters:']) == 'Chapters: '


def test_get_stats_pdf_returns_none_when_chapters_marker_missing():
    assert parse_pdf.get_stats_pdf(['no chapter data here']) is None
    assert parse_pdf.get_stats_pdf([]) is None

# endregion


# region get_series_pdf

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.pdf'),
                         ids=_ids(ebook_fixtures('23009290', '.pdf')))
def test_get_series_pdf_returns_empty_when_no_series(path):
    assert parse_pdf.get_series_pdf(_load_pages(path)) == []


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.pdf'),
                         ids=_ids(ebook_fixtures('334557', '.pdf')))
def test_get_series_pdf_returns_series_from_work_in_series(path):
    series = parse_pdf.get_series_pdf(_load_pages(path))

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


def test_get_series_pdf_filters_non_series_annotations():
    """Guard against partial URIs: only /series/ links should pass the filter."""
    pages = [
        PageObject.create_blank_page(width=612, height=792),  # no annotations at all
        _page_with_annotations([
            _annotation('https://archiveofourown.org/works/111'),
            _annotation('https://archiveofourown.org/series/222'),
            _annotation(),  # no link action
            _annotation('https://example.com/unrelated'),
        ]),
    ]

    assert parse_pdf.get_series_pdf(pages) == ['https://archiveofourown.org/series/222']

# endregion
