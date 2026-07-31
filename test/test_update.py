"""Tests for ao3downloader.update — process_file across all supported formats.

- Snapshot tests (one per format) pin the exact `process_file` output of the
  *current* live fixture. Updated on fixture refresh; they detect fixture drift.
- Structural tests parameterize over all fixtures for a work (current + archive
  via `ebook_fixtures()`) so every preserved format version is verified to still
  parse correctly.
"""

import os
import shutil
import xml.etree.ElementTree as ET
import zipfile

import pytest

from ao3downloader import exceptions, strings, update

from test.conftest import ebook_fixtures


EBOOK_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'ebook')


def _ids(paths):
    """Use the filename as the parametrize id instead of the full path."""
    return [os.path.basename(p) for p in paths]


# region EPUB

def test_process_file_epub_incomplete_work_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '218676', 'current', 'incompleteWork.epub')
    assert update.process_file(path, 'EPUB') == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('218676', '.epub'),
                         ids=_ids(ebook_fixtures('218676', '.epub')))
def test_process_file_epub_incomplete_work_structural(path):
    result = update.process_file(path, 'EPUB')

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']
    assert result['chapters']


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.epub'),
                         ids=_ids(ebook_fixtures('23009290', '.epub')))
def test_process_file_epub_complete_work_returns_none(path):
    assert update.process_file(path, 'EPUB') is None


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.epub'),
                         ids=_ids(ebook_fixtures('334557', '.epub')))
def test_process_file_epub_work_in_series_returns_series(path):
    result = update.process_file(path, 'EPUB', update_series=True)

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


def test_get_epub_preface_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '23009290', 'current', 'epubTest.epub')
    xml = update.get_epub_preface(path)
    assert ET.tostring(xml, encoding='unicode') == snapshot


def test_get_epub_preface_returns_none_on_bad_zip(tmp_path):
    bogus = tmp_path / 'not-a-zip.epub'
    bogus.write_bytes(b'not a zip file')

    assert update.get_epub_preface(str(bogus)) is None


def test_get_epub_preface_returns_none_on_missing_file(tmp_path):
    assert update.get_epub_preface(str(tmp_path / 'missing.epub')) is None


def test_get_epub_preface_returns_none_when_preface_path_missing(tmp_path):
    # minimal epub-like zip with content.opf but no xhtml item in manifest
    zp = tmp_path / 'no_preface.epub'
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr(
            'content.opf',
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="css" href="style.css" media-type="text/css"/>'
            '</manifest></package>'
        )

    assert update.get_epub_preface(str(zp)) is None


def test_get_epub_preface_azw3_returns_none_on_bad_zip(tmp_path):
    bogus = tmp_path / 'not-a-zip.epub'
    bogus.write_bytes(b'not a zip file')

    assert update.get_epub_preface_azw3(str(bogus)) is None


def test_get_epub_preface_azw3_returns_none_on_missing_file(tmp_path):
    assert update.get_epub_preface_azw3(str(tmp_path / 'missing.epub')) is None


def test_get_epub_preface_azw3_returns_none_when_oebps_content_opf_missing(tmp_path):
    # a flat-layout epub (content.opf at root) must NOT match the OEBPS probe —
    # this is what makes the fallback pattern in process_file meaningful.
    zp = tmp_path / 'flat_layout.epub'
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr(
            'content.opf',
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="p" href="preface.xhtml" media-type="application/xhtml+xml"/>'
            '</manifest></package>'
        )
        zf.writestr('preface.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"/>')

    assert update.get_epub_preface_azw3(str(zp)) is None


def test_get_epub_preface_azw3_returns_none_when_preface_path_missing(tmp_path):
    # OEBPS/content.opf exists, but manifest has no xhtml item
    zp = tmp_path / 'no_preface.epub'
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr(
            'OEBPS/content.opf',
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="css" href="style.css" media-type="text/css"/>'
            '</manifest></package>'
        )

    assert update.get_epub_preface_azw3(str(zp)) is None


def test_oebps_layout_falls_through_from_flat_probe(tmp_path):
    # pins the fallback contract without relying on mobi.extract: on an
    # OEBPS-layout zip, the flat probe returns None and the OEBPS probe finds
    # the preface. process_file relies on exactly this pair of behaviors.
    zp = tmp_path / 'oebps_layout.epub'
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr(
            'OEBPS/content.opf',
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="p" href="preface.xhtml" media-type="application/xhtml+xml"/>'
            '</manifest></package>'
        )
        zf.writestr('OEBPS/preface.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"/>')

    assert update.get_epub_preface(str(zp)) is None
    assert update.get_epub_preface_azw3(str(zp)) is not None

# endregion


# region HTML

def test_process_file_html_incomplete_work_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '218676', 'current', 'incompleteWork.html')
    assert update.process_file(path, 'HTML') == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('218676', '.html'),
                         ids=_ids(ebook_fixtures('218676', '.html')))
def test_process_file_html_incomplete_work_structural(path):
    result = update.process_file(path, 'HTML')

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']
    assert result['chapters']


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_process_file_html_complete_work_returns_none(path):
    assert update.process_file(path, 'HTML') is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_process_file_html_update_false_returns_link(path):
    result = update.process_file(path, 'HTML', update=False)

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.html'),
                         ids=_ids(ebook_fixtures('334557', '.html')))
def test_process_file_html_work_in_series_returns_series(path):
    result = update.process_file(path, 'HTML', update_series=True)

    assert result is not None
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_process_file_html_update_series_returns_none_for_solo_work(path):
    assert update.process_file(path, 'HTML', update_series=True) is None

# endregion


# region MOBI

def test_process_file_mobi_incomplete_work_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '218676', 'current', 'incompleteWork.mobi')
    assert update.process_file(path, 'MOBI') == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('218676', '.mobi'),
                         ids=_ids(ebook_fixtures('218676', '.mobi')))
def test_process_file_mobi_incomplete_work_structural(path):
    result = update.process_file(path, 'MOBI')

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']
    assert result['chapters']


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_process_file_mobi_complete_work_returns_none(path):
    assert update.process_file(path, 'MOBI') is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_process_file_mobi_update_false_returns_link(path):
    result = update.process_file(path, 'MOBI', update=False)

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.mobi'),
                         ids=_ids(ebook_fixtures('334557', '.mobi')))
def test_process_file_mobi_work_in_series_returns_series(path):
    result = update.process_file(path, 'MOBI', update_series=True)

    assert result is not None
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


def test_process_file_mobi_returns_none_when_extracted_file_not_html(monkeypatch, tmp_path):
    extract_dir = tmp_path / 'extracted'
    extract_dir.mkdir()
    not_html = extract_dir / 'book.pdf'
    not_html.write_bytes(b'')

    monkeypatch.setattr('ao3downloader.update.mobi.extract',
                        lambda path: (str(extract_dir), str(not_html)))

    assert update.process_file('whatever.mobi', 'MOBI') is None
    assert not extract_dir.exists()

# endregion


# region AZW3

def test_process_file_azw3_incomplete_work_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '218676', 'current', 'incompleteWork.azw3')
    assert update.process_file(path, 'AZW3') == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('218676', '.azw3'),
                         ids=_ids(ebook_fixtures('218676', '.azw3')))
def test_process_file_azw3_incomplete_work_structural(path):
    result = update.process_file(path, 'AZW3')

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']
    assert result['chapters']


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.azw3'),
                         ids=_ids(ebook_fixtures('23009290', '.azw3')))
def test_process_file_azw3_complete_work_returns_none(path):
    assert update.process_file(path, 'AZW3') is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.azw3'),
                         ids=_ids(ebook_fixtures('23009290', '.azw3')))
def test_process_file_azw3_update_false_returns_link(path):
    result = update.process_file(path, 'AZW3', update=False)

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.azw3'),
                         ids=_ids(ebook_fixtures('334557', '.azw3')))
def test_process_file_azw3_work_in_series_returns_series(path):
    result = update.process_file(path, 'AZW3', update_series=True)

    assert result is not None
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


def test_process_file_azw3_delegates_to_epub_parser(monkeypatch, tmp_path):
    # fast offline check of the delegation + tempdir cleanup path using a
    # flat-layout epub fixture (content.opf at root). The OEBPS-layout fallback
    # is exercised end-to-end by the real-AZW3 parameterized tests above.
    extract_dir = tmp_path / 'extracted'
    extract_dir.mkdir()
    extracted_epub = extract_dir / 'book.epub'
    shutil.copyfile(os.path.join(EBOOK_DIR, '218676', 'current', 'incompleteWork.epub'),
                    extracted_epub)

    monkeypatch.setattr('ao3downloader.update.mobi.extract',
                        lambda path: (str(extract_dir), str(extracted_epub)))

    result = update.process_file('whatever.azw3', 'AZW3')

    assert result is not None
    assert 'link' in result
    assert not extract_dir.exists()


def test_process_file_azw3_returns_none_when_extracted_file_not_epub(monkeypatch, tmp_path):
    extract_dir = tmp_path / 'extracted'
    extract_dir.mkdir()
    not_epub = extract_dir / 'book.mobi'
    not_epub.write_bytes(b'')

    monkeypatch.setattr('ao3downloader.update.mobi.extract',
                        lambda path: (str(extract_dir), str(not_epub)))

    assert update.process_file('whatever.azw3', 'AZW3') is None
    assert not extract_dir.exists()

# endregion


# region PDF

def _minimal_pdf(text: str) -> bytes:
    """Build a minimal but fully valid one-page PDF containing `text`."""
    stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode()
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
        b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = b'%PDF-1.4\n'
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref_pos = len(out)
    out += f'xref\n0 {len(objects) + 1}\n'.encode()
    out += b'0000000000 65535 f \n'
    for offset in offsets:
        out += f'{offset:010d} 00000 n \n'.encode()
    out += (f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'
            f'startxref\n{xref_pos}\n%%EOF\n').encode()
    return out


def test_process_file_pdf_incomplete_work_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '218676', 'current', 'incompleteWork.pdf')
    assert update.process_file(path, 'PDF') == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('218676', '.pdf'),
                         ids=_ids(ebook_fixtures('218676', '.pdf')))
def test_process_file_pdf_incomplete_work_structural(path):
    result = update.process_file(path, 'PDF')

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']
    assert result['chapters']


def test_process_file_pdf_tag_wall_snapshot(snapshot):
    # the tag wall pushes the work text deep into the document; this pins that
    # the metadata is still found when only the first pages are searched
    path = os.path.join(EBOOK_DIR, '20907563', 'current', 'tagWall.pdf')
    assert update.process_file(path, 'PDF') == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('20907563', '.pdf'),
                         ids=_ids(ebook_fixtures('20907563', '.pdf')))
def test_process_file_pdf_tag_wall_structural(path):
    result = update.process_file(path, 'PDF')

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']
    assert result['chapters']


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.pdf'),
                         ids=_ids(ebook_fixtures('23009290', '.pdf')))
def test_process_file_pdf_complete_work_returns_none(path):
    assert update.process_file(path, 'PDF') is None


def test_process_file_pdf_update_false_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '23009290', 'current', 'pdfTest.pdf')
    assert update.process_file(path, 'PDF', update=False) == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.pdf'),
                         ids=_ids(ebook_fixtures('23009290', '.pdf')))
def test_process_file_pdf_update_false_returns_link(path):
    result = update.process_file(path, 'PDF', update=False)

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']


def test_process_file_pdf_work_in_series_snapshot(snapshot):
    path = os.path.join(EBOOK_DIR, '334557', 'current', 'workInSeries.pdf')
    assert update.process_file(path, 'PDF', update_series=True) == snapshot


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.pdf'),
                         ids=_ids(ebook_fixtures('334557', '.pdf')))
def test_process_file_pdf_work_in_series_returns_series(path):
    result = update.process_file(path, 'PDF', update_series=True)

    assert result is not None
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.pdf'),
                         ids=_ids(ebook_fixtures('23009290', '.pdf')))
def test_process_file_pdf_update_series_returns_none_for_solo_work(path):
    assert update.process_file(path, 'PDF', update_series=True) is None


def test_process_file_pdf_returns_none_for_non_ao3_pdf(tmp_path):
    # single-page pdf also exercises the fallback for documents shorter
    # than the number of pages the parser tries to load
    pdf_path = tmp_path / 'not_ao3.pdf'
    pdf_path.write_bytes(_minimal_pdf('A pdf that did not come from the archive.'))

    assert update.process_file(str(pdf_path), 'PDF') is None


def test_process_file_pdf_returns_none_on_parse_failure(monkeypatch):
    def raise_parse_error(pdf):
        raise exceptions.PdfParsingException(strings.ERROR_PDF_PARSE)

    monkeypatch.setattr('ao3downloader.update.parse_pdf.get_work_link_pdf', raise_parse_error)
    path = os.path.join(EBOOK_DIR, '23009290', 'current', 'pdfTest.pdf')

    assert update.process_file(path, 'PDF') is None

# endregion


# region invalid filetype

def test_process_file_invalid_filetype_raises_valueerror(tmp_path):
    with pytest.raises(ValueError):
        update.process_file(str(tmp_path / 'x'), 'RTF')

# endregion
