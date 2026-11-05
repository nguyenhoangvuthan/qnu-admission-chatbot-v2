"""Danh mục thật khớp corpus (spec §11 "Danh mục"). Cần PDF từ Git LFS; thiếu thì bỏ qua."""

import re
from pathlib import Path

import pytest

from qnuchat.core.catalog import load_catalog
from qnuchat.core.text import fold

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "configs/catalog/qnu-2025.yaml"
PDF = ROOT / "data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf"
EXCLUDED = frozenset({1, 2, 3, 107, 108})  # = corpus.excluded_pages của cấu hình B3


@pytest.fixture(scope="module")
def corpus_pages():
    if not PDF.exists() or PDF.stat().st_size < 10_000:  # con trỏ LFS chưa kéo
        pytest.skip("PDF corpus chưa có (git lfs pull)")
    from qnuchat.ingest.pdf import load_pdf_pages

    return {p.page: fold(p.text) for p in load_pdf_pages(str(PDF), EXCLUDED)}


def test_every_major_name_appears_in_the_corpus_and_on_its_own_pages(corpus_pages):
    catalog, _ = load_catalog(CATALOG)
    missing = []
    for major in catalog.majors:
        pattern = re.compile(r"\b" + re.escape(fold(major.name)) + r"\b")
        if not any(pattern.search(corpus_pages.get(page, "")) for page in major.pages):
            missing.append(major.id)
    assert missing == []


def test_pages_are_inside_the_corpus(corpus_pages):
    catalog, _ = load_catalog(CATALOG)
    outside = {m.id: p for m in catalog.majors for p in m.pages if p not in corpus_pages}
    assert outside == {}


def test_real_catalog_shape():
    catalog, _ = load_catalog(CATALOG)
    assert catalog.years == [2025]
    assert len(catalog.majors) > 3  # thiếu ngành thì hỏi (M4)
    assert 1 <= len(catalog.suggested) <= 6
    assert all(values == [] for values in catalog.slots.model_dump().values())
