from pathlib import Path

import pymupdf
import pytest

from qnuchat.ingest.pdf import load_pdf_pages

CAM_NANG = Path("data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf")
EXCLUDED = frozenset({1, 2, 3, 107, 108})


def write_pdf(path: Path, texts: list[str]) -> Path:
    doc = pymupdf.open()
    for text in texts:
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def test_pages_are_one_indexed(tmp_path):
    pages = load_pdf_pages(write_pdf(tmp_path / "a.pdf", ["mot", "hai"]))
    assert [p.page for p in pages] == [1, 2]
    assert "hai" in pages[1].text


def test_no_page_is_excluded_unless_configured(tmp_path):
    assert len(load_pdf_pages(write_pdf(tmp_path / "a.pdf", ["a", "b", "c"]))) == 3


def test_excluded_pages_are_dropped_and_numbering_is_kept(tmp_path):
    pages = load_pdf_pages(write_pdf(tmp_path / "a.pdf", ["a", "b", "c"]), frozenset({2}))
    assert [p.page for p in pages] == [1, 3]


@pytest.mark.skipif(not CAM_NANG.exists(), reason="PDF corpus chưa có")
def test_cam_nang_2025_has_103_usable_pages():
    pages = load_pdf_pages(CAM_NANG, EXCLUDED)
    assert len(pages) == 103
    assert (pages[0].page, pages[-1].page) == (4, 106)
