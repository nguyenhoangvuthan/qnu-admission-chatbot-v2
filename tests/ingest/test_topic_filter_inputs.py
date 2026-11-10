import json
from datetime import date

import pytest

from qnuchat.ingest.state import CheckState
from qnuchat.ingest.topic_filter.inputs import (
    BlobMissing,
    build_input,
    candidates,
    exempt,
)
from tests.support.webstore import TS, W, WebStore, docx_bytes, html_page, png_bytes

NEWS = f"{W}/vi/tin/hoi-thao-khoa-hoc"
FEES = f"{W}/vi/hoc-phi-quy-dinh/thong-bao"
PDF_URL = f"{W}/Resources/Docs/Th%C3%B4ng%20b%C3%A1o%20h%E1%BB%8Dc%20ph%C3%AD%202026.pdf"
DOCX_URL = f"{W}/Resources/Docs/de-an.docx"
IMG = f"{W}/Temp/ArticleImage/anh.jpg"
TIER_A = f"{TS}/vi/tong-hop-nganh-dao-tao"
SEED = f"{TS}/"
HUB = f"{W}/vi/tin"
FAVICON = f"{W}/favicon.ico"


@pytest.fixture
def store(tmp_path):
    web = WebStore(tmp_path)
    web.put(NEWS, title="Hội thảo khoa học", data=html_page("Hội thảo", "tuyển sinh " * 400))
    web.put(FEES, title="Học phí – Quy định")
    web.put(PDF_URL, kind="file", page_url=FEES, title="Thông báo học phí 2026", data=b"%PDF-scan")
    web.put(
        DOCX_URL,
        kind="file",
        page_url=FEES,
        title="Đề án",
        data=docx_bytes("Đề án tuyển sinh đại học chính quy năm 2026"),
        text_status="text",
    )
    web.put(IMG, kind="image", page_url=NEWS, data=png_bytes(), quarantine=True)
    web.put(TIER_A, tier="A", title="Tổng hợp ngành")
    web.put(SEED, title="Tuyển sinh")
    web.put(HUB, title="Tin tức")
    web.put(FAVICON, kind="favicon", data=b"icon", text_status="text")
    state = CheckState(tmp_path / "last_checked.json")
    state.mark(HUB, date(2026, 10, 13), hub=True)
    return web, state


def test_page_input_has_title_host_and_first_1500_chars_of_main_text(store):
    web, _ = store
    current = web.current()
    inp = build_input(current[NEWS], current=current, blobs=web.blobs, max_chars=1500)
    assert (inp.url, inp.kind, inp.host, inp.title) == (
        NEWS,
        "page",
        "www.qnu.edu.vn",
        "Hội thảo khoa học",
    )
    assert len(inp.text) == 1500 and inp.text.startswith("Hội thảo")
    assert "Menu trang chủ" not in inp.text  # chỉ phần <main>
    assert inp.file_name is None and inp.link_text is None


def test_file_without_text_layer_has_name_page_title_and_link_text_only(store):
    web, _ = store
    current = web.current()
    inp = build_input(current[PDF_URL], current=current, blobs=web.blobs, max_chars=1500)
    assert inp.text is None and inp.file_name == "Thông báo học phí 2026.pdf"
    assert inp.page_title == "Học phí – Quy định" and inp.page_url == FEES
    assert inp.link_text == "Thông báo học phí 2026"


def test_file_with_text_layer_has_its_first_chars(store):
    web, _ = store
    current = web.current()
    inp = build_input(current[DOCX_URL], current=current, blobs=web.blobs, max_chars=1500)
    assert inp.text.startswith("Đề án tuyển sinh đại học chính quy năm 2026")


def test_image_input_has_no_content(store):
    web, _ = store
    current = web.current()
    inp = build_input(current[IMG], current=current, blobs=web.blobs, max_chars=1500)
    assert inp.text is None and inp.file_name == "anh.jpg"
    assert inp.page_title == "Hội thảo khoa học"


def test_tier_a_seeds_hubs_and_favicons_are_exempt(store):
    web, state = store
    current = web.current()
    seeds = {SEED}
    assert all(exempt(current[u], seeds=seeds, state=state) for u in (TIER_A, SEED, HUB, FAVICON))
    assert not any(exempt(current[u], seeds=seeds, state=state) for u in (NEWS, PDF_URL, IMG))


def test_candidates_order_pages_then_files_then_images(store):
    web, state = store
    urls = [e.url for e in candidates(web.current(), seeds={SEED}, state=state)]
    assert urls == sorted([FEES, NEWS]) + sorted([DOCX_URL, PDF_URL]) + [IMG]


def test_missing_blob_raises_blob_missing(store):
    web, _ = store
    current = web.current()
    web.blobs.delete(current[NEWS].sha256)
    with pytest.raises(BlobMissing):
        build_input(current[NEWS], current=current, blobs=web.blobs, max_chars=1500)


def _ocr_document(tmp_path, sha, *texts):
    documents = tmp_path / "documents"
    documents.mkdir(exist_ok=True)
    pages = [{"page": i, "text": text} for i, text in enumerate(texts, start=1)]
    (documents / f"{sha}.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    return documents


def test_image_with_ocr_text_gets_that_text_as_content(tmp_path):
    web = WebStore(tmp_path)
    sha = web.put(f"{W}/a.png", kind="image", data=png_bytes(), text_status="text")
    documents = _ocr_document(tmp_path, sha, "Học phí 2026", "", "trang ba")
    entry = web.current()[f"{W}/a.png"]
    inp = build_input(
        entry, current=web.current(), blobs=web.blobs, max_chars=9, ocr_documents=documents
    )
    assert inp.text == "Học phí 2"


def test_image_without_ocr_text_has_no_content(tmp_path):
    web = WebStore(tmp_path)
    web.put(f"{W}/a.png", kind="image", data=png_bytes(), text_status="text")
    entry = web.current()[f"{W}/a.png"]
    inp = build_input(
        entry,
        current=web.current(),
        blobs=web.blobs,
        max_chars=100,
        ocr_documents=tmp_path / "khong-co",
    )
    assert inp.text is None
