import dataclasses
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.config import CrawlConfig, Limits, TopicGate
from qnuchat.ingest.crawl import Crawler
from qnuchat.ingest.fetch import Fetcher
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.state import CheckState
from tests.support.qnu_site import (
    LISTING,
    NEXT,
    article_html,
    build_site,
    card,
    listing_html,
    png,
    text_pdf,
)

TODAY = date(2026, 10, 12)
A1, A2, A3 = (f"{LISTING}/tb141-diem-chuan", f"{LISTING}/tb121-nguong", f"{LISTING}/tb112-chi-tieu")
SKIP = f"{LISTING}/danh-sach-thi-sinh-trung-tuyen"
PDF = "https://www.qnu.edu.vn/Resources/Docs/TB141.pdf"
IMG = "https://www.qnu.edu.vn/Resources/Images/bang1.png"
DRIVE = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view"
FOLDER = "https://drive.google.com/drive/folders/1FoLdErIdXyZ12345"
ADMIN = "https://www.qnu.edu.vn/vi/quan-tri"


# Chuyên mục trống thật vẫn có menu của site; trang không chữ, không link là trang lỗi mềm.
MENU = '<a href="/vi/gioi-thieu">Giới thiệu</a>'


def config(**overrides) -> CrawlConfig:
    base = {
        "seeds": [LISTING],
        "host_suffix": ".qnu.edu.vn",
        "tier_a": [LISTING],
        "pii_title_skip": ["danh sách (sinh viên|thí sinh|học viên)"],
        "limits": Limits(
            rps_per_host=1000, hosts_parallel=1, max_file_mb=5, timeout_s=5, retries=0
        ),
        "user_agent": "UA {contact}",
    }
    base.update(overrides)
    return CrawlConfig(**base)


def crawl(site, root, *, today=TODAY, cfg=None, run_id="run-1", state=None, on_progress=None):
    fetcher = Fetcher(
        user_agent="UA",
        rps_per_host=1000,
        timeout_s=5,
        max_bytes=5_000_000,
        retries=0,
        transport=httpx.MockTransport(site.handler),
    )
    manifest = Manifest(root / "manifest.jsonl")
    crawler = Crawler(
        cfg or config(),
        config_hash="h",
        run_id=run_id,
        fetcher=fetcher,
        manifest=manifest,
        blobs=BlobStore(root),
        state=state or CheckState(root / "last_checked.json"),
        sources_index={},
        today=today,
        now=lambda: datetime(today.year, today.month, today.day, 2, tzinfo=UTC),
        on_progress=on_progress,
    )
    try:
        stats = crawler.run()
    finally:
        fetcher.close()
    return stats, Manifest(root / "manifest.jsonl")


def status(manifest, url):
    entry = manifest.latest(url)
    return (entry.text_status, entry.reason) if entry else None


def test_first_crawl_stores_documents_and_skips_people_and_logins(tmp_path):
    site = build_site()
    stats, manifest = crawl(site, tmp_path)
    current = manifest.current()
    assert {LISTING, A1, A3, PDF} <= set(current)
    assert current[A1].tier == "A" and current[A1].published == "2026-08-09"
    assert current[A1].title == "TB141 - Điểm chuẩn"
    assert current[A3].published == "2025-03-01"
    assert current[PDF].kind == "file" and current[PDF].text_status == "text"
    assert current[PDF].page_url == A1 and current[PDF].tier == "A"
    assert status(manifest, IMG) == ("needs_ocr", None)
    assert status(manifest, DRIVE) == ("needs_ocr", None)
    assert status(manifest, A2) == ("skipped_pii", "header:ho_ten+ngay_sinh")
    assert status(manifest, SKIP)[0] == "skipped_pii" and status(manifest, SKIP)[1].startswith(
        "title:"
    )
    assert status(manifest, FOLDER) == ("auth_required", "drive_folder")
    assert status(manifest, ADMIN) == ("auth_required", "login_redirect")
    assert site.count("GET", SKIP) == 0
    assert manifest.latest("https://www.qnu.edu.vn/Resources/Images/icon.png") is None
    assert stats.pages_new == 3 and stats.files_new == 3
    assert stats.skipped_pii == 2 and stats.auth_required == 2 and stats.needs_ocr == 2
    assert stats.errors == 0 and stats.warnings == []


def test_blobs_land_in_tier_and_quarantine_and_people_lists_are_not_stored(tmp_path):
    site = build_site()
    _, manifest = crawl(site, tmp_path)
    blobs = BlobStore(tmp_path)
    assert blobs.path(manifest.latest(A1).sha256).parent == tmp_path / "blobs" / "A"
    assert blobs.path(manifest.latest(IMG).sha256).parent == tmp_path / "quarantine"
    assert manifest.latest(A2).sha256 is None
    stored = b"".join(p.read_bytes() for p in (tmp_path / "blobs").rglob("*") if p.is_file())
    assert "Nguyễn Văn A".encode() not in stored


def test_page_blob_is_the_main_content_not_the_whole_page(tmp_path):
    site = build_site()
    _, manifest = crawl(site, tmp_path)
    blob = BlobStore(tmp_path).path(manifest.latest(A1).sha256).read_bytes().decode()
    assert "Điểm chuẩn trúng tuyển" in blob and "tin-khac" not in blob and "__VIEWSTATE" not in blob


def test_favicon_is_taken_from_the_declared_icon(tmp_path):
    site = build_site()
    _, manifest = crawl(site, tmp_path)
    icon = manifest.favicon("www.qnu.edu.vn")
    assert icon is not None and icon.mime == "image/png"
    assert site.count("GET", "https://www.qnu.edu.vn/favicon.ico") == 0


def test_listing_pagination_follows_postback_until_nothing_new(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    assert site.count("POST", LISTING) == 2  # trang 2 có bài mới; lần POST thứ hai không có gì mới


def test_second_run_same_day_refetches_only_the_listing(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    lines = len(Manifest(tmp_path / "manifest.jsonl").entries())
    site.requests.clear()
    stats, manifest = crawl(site, tmp_path, run_id="run-2")
    assert len(manifest.entries()) == lines
    assert site.count("GET", LISTING) == 1 and site.count("POST", LISTING) == 1
    assert site.count("GET", A1) == 0 and site.count("GET", PDF) == 0
    assert (stats.pages_new, stats.pages_changed, stats.files_new, stats.skipped_pii) == (
        0,
        0,
        0,
        0,
    )


def test_sidebar_change_does_not_create_a_new_version(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    lines = len(Manifest(tmp_path / "manifest.jsonl").entries())
    site.html(
        A1,
        article_html(
            "TB141 - Điểm chuẩn",
            (
                "<p>Điểm chuẩn trúng tuyển đại học chính quy năm 2026.</p>"
                '<p><a href="/Resources/Docs/TB141.pdf">Văn bản</a></p>'
                '<img src="/Resources/Images/bang1.png" /><img src="/Resources/Images/icon.png" />'
                '<p><a href="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view">'
                "Bản scan</a></p>"
                '<p><a href="https://drive.google.com/drive/folders/1FoLdErIdXyZ12345">'
                "Thư mục</a></p>"
            ),
            sidebar="<a href='/vi/khac'>Tin mới hôm nay</a>",
        ),
    )
    stats, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    assert site.count("GET", A1) == 2
    assert len(manifest.entries()) == lines and stats.pages_changed == 0


def test_changed_main_content_is_a_new_version(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    old = Manifest(tmp_path / "manifest.jsonl").latest(A3).sha256
    site.html(
        A3, article_html("TB112 - Chỉ tiêu", "<p>Chỉ tiêu tuyển sinh năm 2025 ĐÃ ĐIỀU CHỈNH.</p>")
    )
    stats, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    assert manifest.latest(A3).sha256 != old and stats.pages_changed == 1


def test_known_article_returning_404_is_gone(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    site.remove(A3)
    crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    manifest = Manifest(tmp_path / "manifest.jsonl")
    assert status(manifest, A3) == ("failed", "gone") and A3 not in manifest.current()


def test_soft_404_file_is_recorded_as_not_a_file(tmp_path):
    site = build_site()
    site.html(PDF, "﻿<!DOCTYPE html><html><head><title>Untitled Page</title></head></html>")
    _, manifest = crawl(site, tmp_path)
    assert status(manifest, PDF) == ("failed", "not_a_file") and PDF not in manifest.current()


def test_pager_that_always_returns_the_same_page_stops(tmp_path):
    site = build_site()
    site.post(
        LISTING,
        NEXT,
        listing_html(
            [
                card(
                    "/vi/dai-hoc-chinh-quy-1764/tb141-diem-chuan",
                    "TB141 - Điểm chuẩn",
                    "09/08/2026",
                )
            ]
        ),
    )
    crawl(site, tmp_path)
    assert site.count("POST", LISTING) == 1


def test_tier_a_category_without_children_is_a_warning(tmp_path):
    site = build_site()
    empty = "https://www.qnu.edu.vn/vi/trong"
    site.html(empty, listing_html([], pager=False, nav=MENU))
    stats, _ = crawl(site, tmp_path, cfg=config(seeds=[LISTING, empty], tier_a=[LISTING, empty]))
    assert stats.warnings == [f"tier_a_empty:{empty}"]


def test_transient_errors_are_counted_not_written_to_the_manifest(tmp_path):
    site = build_site()
    site.routes[A3] = (503, "text/html", b"")
    stats, manifest = crawl(site, tmp_path)
    assert manifest.latest(A3) is None and stats.errors == 1


@pytest.mark.parametrize("workers", [2, 4])
def test_parallel_hosts_give_the_same_result(tmp_path, workers):
    serial, _ = crawl(build_site(), tmp_path / "s")
    cfg = config(
        limits=Limits(
            rps_per_host=1000, hosts_parallel=workers, max_file_mb=5, timeout_s=5, retries=0
        )
    )
    parallel, manifest = crawl(build_site(), tmp_path / "p", cfg=cfg)
    assert parallel == serial
    assert set(manifest.current()) == set(Manifest(tmp_path / "s" / "manifest.jsonl").current())


def test_image_below_the_minimum_side_is_ignored(tmp_path):
    site = build_site()
    site.file("https://www.qnu.edu.vn/Resources/Images/bang1.png", png(199, 400), "image/png")
    _, manifest = crawl(site, tmp_path)
    assert manifest.latest(IMG) is None


def gated(**gate) -> CrawlConfig:
    return config(topic_gate=TopicGate(**{"include": ["diem-chuan"], **gate}))


def test_gate_follows_only_links_on_topic_and_keeps_an_off_topic_seed_out_of_the_store(tmp_path):
    site = build_site()
    _, manifest = crawl(site, tmp_path, cfg=gated())
    assert status(manifest, A1) == ("text", None)
    assert site.count("GET", A2) == 0
    assert manifest.latest(LISTING) is None
    assert site.count("POST", LISTING) == 0


def test_gate_exclude_beats_include(tmp_path):
    site = build_site()
    site.html(LISTING, listing_html([card(f"{LISTING}/tb9", "Điểm chuẩn thạc sĩ", "09/08/2026")]))
    crawl(site, tmp_path, cfg=gated(exclude=["thac-si"]))
    assert site.count("GET", f"{LISTING}/tb9") == 0


def test_gate_trusted_section_keeps_articles_whose_title_has_no_keyword(tmp_path):
    site = build_site()
    _, manifest = crawl(site, tmp_path, cfg=gated(include=["khong-khop"], trusted=[LISTING]))
    assert status(manifest, A3) == ("text", None)
    assert manifest.latest(LISTING) is not None


def test_gate_takes_attachments_of_the_article_body_but_not_of_its_sidebar(tmp_path):
    other = "https://www.qnu.edu.vn/Resources/Docs/khac.pdf"
    site = build_site()
    site.html(
        A1,
        article_html(
            "TB141 - Điểm chuẩn",
            '<p>Điểm chuẩn năm 2026.</p><a href="/Resources/Docs/TB141.pdf">Văn bản</a>',
            sidebar='<a href="/Resources/Docs/khac.pdf">Văn bản khác</a>',
        ),
    )
    site.file(other, text_pdf(), "application/pdf")
    _, manifest = crawl(site, tmp_path, cfg=gated())
    assert status(manifest, PDF) == ("text", None)
    assert site.count("GET", other) == 0


def test_gate_takes_images_of_an_article_but_not_listing_thumbnails(tmp_path):
    thumb = "https://www.qnu.edu.vn/Resources/Images/thumb.png"
    site = build_site()
    cards = [card(f"{LISTING}/tb141-diem-chuan", "TB141 - Điểm chuẩn", "09/08/2026")]
    site.html(LISTING, listing_html([*cards, '<img src="/Resources/Images/thumb.png" />']))
    site.file(thumb, png(), "image/png")
    _, manifest = crawl(site, tmp_path, cfg=gated(trusted=[LISTING]))
    assert site.count("GET", thumb) == 0
    assert status(manifest, IMG) == ("needs_ocr", None)


def test_gate_exclude_also_stops_an_image_of_an_article(tmp_path):
    site = build_site()
    _, manifest = crawl(site, tmp_path, cfg=gated(exclude=["bang1"]))
    assert site.count("GET", IMG) == 0
    assert status(manifest, A1) == ("text", None)


def test_page_redirecting_outside_the_scope_is_not_stored(tmp_path):
    site = build_site()
    ext, fb = "https://www.qnu.edu.vn/vi/mang-xa-hoi", "https://www.facebook.com/qnu"
    site.html(LISTING, listing_html([], pager=False, nav=f'<a href="{ext}">Facebook</a>'))
    site.redirect(ext, fb)
    site.html(fb, article_html("Facebook", "<p>không được lưu</p>"))
    stats, manifest = crawl(site, tmp_path)
    assert manifest.latest(ext) is None and manifest.latest(fb) is None
    assert stats.errors == 0


DS = "https://www.qnu.edu.vn/Resources/Docs/ds.pdf"
DS2 = "https://www.qnu.edu.vn/Resources/Docs/ds2.pdf"


def test_people_list_with_thumbnail_anchor_does_not_leak_its_attachments(tmp_path):
    from tests.support.qnu_site import scanned_pdf

    site = build_site()
    path = "/vi/dai-hoc-chinh-quy-1764/danh-sach-thi-sinh-trung-tuyen"
    thumb = f'<a href="{path}"><img src="/Temp/x.png"/></a>'
    cards = [
        card("/vi/dai-hoc-chinh-quy-1764/tb112-chi-tieu", "TB112 - Chỉ tiêu", "01/03/2025"),
        card(path, "Danh sách thí sinh trúng tuyển đợt 1", "01/08/2026").replace(
            '<h6 class="card-title">', f'<h6 class="card-title">{thumb}'
        ),
    ]
    site.html(LISTING, listing_html(cards, pager=False))
    site.html(SKIP, article_html("Danh sách", '<p><a href="/Resources/Docs/ds.pdf">DS</a></p>'))
    site.file(DS, scanned_pdf(), "application/pdf")
    _, manifest = crawl(site, tmp_path)
    assert site.count("GET", SKIP) == 0 and site.count("GET", DS) == 0
    assert manifest.latest(DS) is None
    assert status(manifest, SKIP)[0] == "skipped_pii"
    assert not list((tmp_path / "quarantine").rglob("*")) or all(
        p.is_dir() for p in (tmp_path / "quarantine").rglob("*")
    )


def test_people_table_article_does_not_enqueue_its_links(tmp_path):
    from tests.support.qnu_site import text_pdf

    site = build_site()
    body = (
        "<table><tr><th>STT</th><th>Họ và tên</th><th>Ngày sinh</th></tr>"
        "<tr><td>1</td><td>Nguyễn Văn A</td><td>01/02/2008</td></tr></table>"
        '<p><a href="/Resources/Docs/ds2.pdf">DS</a></p>'
    )
    site.html(A2, article_html("TB121 - Ngưỡng", body))
    site.file(DS2, text_pdf(), "application/pdf")
    _, manifest = crawl(site, tmp_path)
    assert status(manifest, A2)[0] == "skipped_pii"
    assert site.count("GET", DS2) == 0 and manifest.latest(DS2) is None


# ---------------------------------------------------------------- trang lỗi mềm của site

SOFT_404 = "﻿<!DOCTYPE html><html><head><title>Untitled Page</title></head></html>"
ERROR_PAGE = "https://www.qnu.edu.vn/GenericErrorPage.htm?aspxerrorpath=/vi/x"


def test_known_article_now_serving_the_bodyless_soft_404_is_gone(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    site.html(A3, SOFT_404)
    stats, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    assert status(manifest, A3) == ("failed", "gone") and A3 not in manifest.current()
    assert stats.errors == 0


def test_unknown_link_to_the_soft_404_is_skipped_silently(tmp_path):
    site = build_site()
    dead = "https://www.qnu.edu.vn/vi/khong-ton-tai"
    site.html(LISTING, listing_html([], pager=False, nav=f'<a href="{dead}">Mục cũ</a>'))
    site.html(dead, SOFT_404)
    stats, manifest = crawl(site, tmp_path)
    assert site.count("GET", dead) == 1
    assert manifest.latest(dead) is None and stats.errors == 0


def test_known_article_redirecting_to_the_generic_error_page_is_gone(tmp_path):
    site = build_site()
    cfg = config(blocklist_url_patterns=["/GenericErrorPage"])
    crawl(site, tmp_path, cfg=cfg)
    site.redirect(A3, ERROR_PAGE)
    site.html(ERROR_PAGE, article_html("Lỗi", "<p>Trang bạn tìm không tồn tại hoặc đã bị gỡ.</p>"))
    stats, manifest = crawl(
        site, tmp_path, cfg=cfg, today=TODAY + timedelta(days=31), run_id="run-2"
    )
    assert status(manifest, A3) == ("failed", "gone") and A3 not in manifest.current()
    assert manifest.latest(ERROR_PAGE) is None and stats.errors == 0


def test_stored_pdf_now_served_as_the_html_error_page_is_gone(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    site.html(PDF, SOFT_404)
    stats, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    assert status(manifest, PDF) == ("failed", "gone") and PDF not in manifest.current()
    assert stats.errors == 0


def test_relative_links_resolve_against_the_url_after_redirect(tmp_path):
    site = build_site()
    home, index = "https://www.qnu.edu.vn/vi/", "https://www.qnu.edu.vn/vi/trang-chu/index"
    site.redirect(home, index)
    site.html(index, article_html("Trang chủ", '<p><a href="gioi-thieu">Giới thiệu</a></p>'))
    child = "https://www.qnu.edu.vn/vi/trang-chu/gioi-thieu"
    site.html(child, article_html("Giới thiệu", "<p>Trường Đại học Quy Nhơn.</p>"))
    _, manifest = crawl(site, tmp_path, cfg=config(seeds=[LISTING, home]))
    assert site.count("GET", child) == 1
    assert site.count("GET", "https://www.qnu.edu.vn/vi/gioi-thieu") == 0
    assert manifest.latest(home) is not None and manifest.latest(index) is None


def test_pagination_of_a_redirected_listing_uses_the_final_url(tmp_path):
    site = build_site()
    old = "https://www.qnu.edu.vn/vi/dhcq"
    site.redirect(old, LISTING)
    crawl(site, tmp_path, cfg=config(seeds=[old], tier_a=[old]))
    # Bài ở trang 2 là con của URL sau chuyển hướng: lật tiếp như khi vào thẳng chuyên mục.
    assert site.count("POST", LISTING) == 2


def test_recrawl_recreates_a_missing_blob_without_a_new_manifest_line(tmp_path):
    site = build_site()
    _, manifest = crawl(site, tmp_path)
    lines = len(manifest.entries())
    blobs = BlobStore(tmp_path)
    listing, pdf, img = (manifest.latest(u).sha256 for u in (LISTING, PDF, IMG))
    for sha in (listing, pdf, img):
        blobs.path(sha).unlink()
    stats, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    assert len(manifest.entries()) == lines
    assert blobs.path(listing) == tmp_path / "blobs" / "A" / listing
    assert blobs.path(pdf) == tmp_path / "blobs" / "A" / pdf
    assert blobs.path(img) == tmp_path / "quarantine" / img
    assert (stats.pages_new, stats.pages_changed, stats.files_new, stats.files_changed) == (
        0,
        0,
        0,
        0,
    )


# ---------------------------------------------------------------- robots.txt (spec §6.2 bước 1)

ROBOTS = "https://www.qnu.edu.vn/robots.txt"
PRIVATE = "https://www.qnu.edu.vn/vi/private/ho-so"


def _listing_with(*hrefs: str) -> str:
    nav = "".join(f'<a href="{h}">Mục {i}</a>' for i, h in enumerate(hrefs))
    return listing_html([], pager=False, nav=nav)


def test_page_disallowed_by_robots_txt_is_never_fetched(tmp_path):
    site = build_site()
    site.file(ROBOTS, b"User-agent: *\nDisallow: /vi/private\n", "text/plain")
    site.html(LISTING, _listing_with(PRIVATE, A3))
    site.html(PRIVATE, article_html("Hồ sơ", "<p>không được tải</p>"))
    stats, manifest = crawl(site, tmp_path)
    assert site.count("GET", PRIVATE) == 0 and manifest.latest(PRIVATE) is None
    assert manifest.latest(A3) is not None and stats.errors == 0


def test_robots_rules_for_our_user_agent_cover_attachments(tmp_path):
    site = build_site()
    robots = b"User-agent: QNU-admission-chatbot\nDisallow: /Resources/Docs/\n"
    site.file(ROBOTS, robots, "text/plain")
    stats, manifest = crawl(site, tmp_path)
    assert site.count("GET", PDF) == 0 and manifest.latest(PDF) is None
    assert manifest.latest(A1) is not None and stats.errors == 0


def test_html_soft_404_robots_txt_allows_everything(tmp_path):
    site = build_site()
    site.html(ROBOTS, "<html><body>\nUser-agent: *\nDisallow: /\n</body></html>")
    _, manifest = crawl(site, tmp_path)
    assert {LISTING, A1, A3, PDF} <= set(manifest.current())


def test_robots_txt_is_fetched_once_per_host_in_scope(tmp_path):
    site = build_site()
    other = "https://tuyensinh.qnu.edu.vn/vi/gioi-thieu"
    site.html(LISTING, _listing_with(A1, A3, other, "https://tuyensinh.qnu.edu.vn/vi/khac"))
    site.html(other, article_html("Giới thiệu", "<p>Tuyển sinh.</p>"))
    cfg = config(
        limits=Limits(rps_per_host=1000, hosts_parallel=4, max_file_mb=5, timeout_s=5, retries=0)
    )
    crawl(site, tmp_path, cfg=cfg)
    assert site.count("GET", ROBOTS) == 1
    assert site.count("GET", "https://tuyensinh.qnu.edu.vn/robots.txt") == 1
    # Drive không thuộc site trường: file đính kèm trường đã link vẫn tải (spec §4.1).
    assert site.count("GET", "https://drive.google.com/robots.txt") == 0


def test_drive_links_differing_only_in_usp_are_one_document(tmp_path):
    site = build_site()
    links = (
        '<p><a href="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing">A</a></p>'
        '<p><a href="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=drive_link">'
        "B</a></p>"
    )
    site.html(A3, article_html("TB112 - Chỉ tiêu", f"<p>Chỉ tiêu tuyển sinh.</p>{links}"))
    _, manifest = crawl(site, tmp_path)
    drive_urls = {e.url for e in manifest.entries() if "drive.google.com/file" in e.url}
    assert drive_urls == {DRIVE}
    assert (
        site.count("GET", "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp") == 1
    )


# ---------------------------------------------------------------- đợt sửa lỗi nhỏ 3 (crawler)

LINKS = "https://www.qnu.edu.vn/vi/lien-ket"
FB_LINK, FB = "https://www.qnu.edu.vn/vi/mang-xa-hoi", "https://www.facebook.com/qnu"
DEAD = "https://www.qnu.edu.vn/vi/khong-con"
SMALL = "https://www.qnu.edu.vn/Resources/Images/nho.png"


def _links_seed(site, body: str) -> CrawlConfig:
    """Hạt giống thứ hai (luôn tải mỗi lần quét) chứa `body`."""
    site.html(LINKS, article_html("Liên kết", f"<p>Các liên kết của trường.</p>{body}"))
    return config(seeds=[LISTING, LINKS])


def test_dead_ends_are_fetched_once_per_recheck_window(tmp_path):
    site = build_site()
    cfg = _links_seed(
        site,
        f'<p><a href="{FB_LINK}">Facebook</a> <a href="{DEAD}">Mục cũ</a></p><img src="{SMALL}" />',
    )
    site.redirect(FB_LINK, FB)
    site.html(FB, article_html("Facebook", "<p>không được lưu</p>"))
    site.file(SMALL, png(32, 32), "image/png")
    stats, manifest = crawl(site, tmp_path, cfg=cfg)
    # Link 404 chưa từng lưu là link hỏng của site, không phải lỗi hạ tầng.
    assert stats.errors == 0
    assert all(manifest.latest(u) is None for u in (FB_LINK, DEAD, SMALL))
    crawl(site, tmp_path, cfg=cfg, run_id="run-2")
    assert site.count("GET", LINKS) == 2
    assert [site.count("GET", u) for u in (FB_LINK, DEAD, SMALL)] == [1, 1, 1]


def test_transient_error_is_not_marked_and_is_retried_next_run(tmp_path):
    site = build_site()
    site.routes[A3] = (503, "text/html", b"")
    crawl(site, tmp_path)
    stats, _ = crawl(site, tmp_path, run_id="run-2")
    assert site.count("GET", A3) == 2 and stats.errors == 1


def test_auth_required_attachment_is_not_refetched_before_the_recheck_window(tmp_path):
    site = build_site()
    site.routes[PDF] = (403, "text/html", b"")
    cfg = _links_seed(site, f'<p><a href="{PDF}">Văn bản</a></p>')
    crawl(site, tmp_path, cfg=cfg)
    _, manifest = crawl(site, tmp_path, cfg=cfg, run_id="run-2")
    assert status(manifest, PDF) == ("auth_required", "http_403")
    assert site.count("GET", LINKS) == 2 and site.count("GET", PDF) == 1


def test_pagination_does_not_stop_on_articles_another_page_enqueued(tmp_path):
    site = build_site()
    # Hạt giống xếp trước chuyên mục (cùng host, một hàng đợi): A3 vào _seen trước khi lật trang.
    first = "https://www.qnu.edu.vn/vi/a-tin-noi-bat"
    site.html(
        first, article_html("Tin nổi bật", f'<p>Tin nổi bật.</p><p><a href="{A3}">TB112</a></p>')
    )
    crawl(site, tmp_path, cfg=config(seeds=[LISTING, first]))
    assert site.count("POST", LISTING) == 2


@pytest.mark.parametrize(
    "login",
    ["https://www.qnu.edu.vn/Login.aspx", "https://accounts.google.com/o/oauth2/auth"],
)
def test_attachment_redirecting_to_a_login_page_is_auth_required(tmp_path, login):
    site = build_site()
    site.redirect(PDF, login)
    site.html(login, "<html><body><form><input type='password' name='p' /></form></body></html>")
    stats, manifest = crawl(site, tmp_path)
    assert status(manifest, PDF) == ("auth_required", "login_redirect")
    assert stats.errors == 0


def test_attachment_redirecting_outside_the_scope_is_not_stored(tmp_path):
    from tests.support.qnu_site import scanned_pdf, text_pdf

    site = build_site()
    cdn = "https://cdn.example.com/TB141.pdf"
    site.redirect(PDF, cdn)
    site.file(cdn, text_pdf(), "application/pdf")
    # Drive chuyển sang drive.usercontent.google.com vẫn là file Drive: vẫn lưu.
    uc = "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp"
    usercontent = "https://drive.usercontent.google.com/uc?id=1AbCdEfGhIjKlMnOp&export=download"
    site.redirect(uc, usercontent)
    site.file(usercontent, scanned_pdf(), "application/pdf")
    cfg = _links_seed(site, f'<p><a href="{PDF}">Văn bản</a></p>')
    stats, manifest = crawl(site, tmp_path, cfg=cfg)
    assert manifest.latest(PDF) is None and manifest.latest(cdn) is None
    assert status(manifest, DRIVE) == ("needs_ocr", None)
    assert stats.errors == 0
    crawl(site, tmp_path, cfg=cfg, run_id="run-2")
    assert site.count("GET", LINKS) == 2 and site.count("GET", PDF) == 1


def test_favicon_failure_does_not_lose_the_hub_flag(tmp_path, monkeypatch):
    import qnuchat.ingest.crawl as crawl_module

    def boom(*args, **kwargs):
        raise RuntimeError("favicon hỏng")

    monkeypatch.setattr(crawl_module.favicon, "candidates", boom)
    site = build_site()
    stats, _ = crawl(site, tmp_path)
    assert stats.errors == 1
    assert CheckState(tmp_path / "last_checked.json").is_hub(LISTING)


class _CountingState(CheckState):
    def __init__(self, path):
        super().__init__(path)
        self.marks = 0
        self.saved_at: list[int] = []

    def mark(self, url, today, *, hub=None):
        super().mark(url, today, hub=hub)
        self.marks += 1

    def save(self):
        self.saved_at.append(self.marks)
        super().save()


def test_check_state_is_saved_every_200_marks(tmp_path):
    site = build_site()
    cards = []
    for i in range(205):
        path = f"/vi/dai-hoc-chinh-quy-1764/bai-{i}"
        cards.append(card(path, f"Bài {i}", "01/09/2026"))
        site.html(
            f"https://www.qnu.edu.vn{path}", article_html(f"Bài {i}", f"<p>Nội dung {i}.</p>")
        )
    site.html(LISTING, listing_html(cards, pager=False, nav=""))
    state = _CountingState(tmp_path / "last_checked.json")
    crawl(site, tmp_path, state=state)
    assert state.marks > 200
    assert state.saved_at == [200, state.marks]


EMPTY = "https://www.qnu.edu.vn/vi/trong"


def test_tier_a_empty_warning_is_not_repeated_for_a_page_that_was_already_empty(tmp_path):
    site = build_site()
    site.html(EMPTY, listing_html([], pager=False, nav=MENU))
    cfg = config(seeds=[LISTING, EMPTY], tier_a=[LISTING, EMPTY])
    first, _ = crawl(site, tmp_path, cfg=cfg)
    second, _ = crawl(site, tmp_path, cfg=cfg, run_id="run-2")
    assert first.warnings == [f"tier_a_empty:{EMPTY}"]
    assert second.warnings == []


def test_tier_a_page_that_lost_its_children_warns_again(tmp_path):
    site = build_site()
    children = [card(f"/vi/trong/bai-{i}", f"Bài {i}", "01/09/2026") for i in range(3)]
    site.html(EMPTY, listing_html(children, pager=False, nav=""))
    cfg = config(seeds=[LISTING, EMPTY], tier_a=[LISTING, EMPTY])
    first, _ = crawl(site, tmp_path, cfg=cfg)
    site.html(EMPTY, listing_html([], pager=False, nav=MENU))
    second, _ = crawl(site, tmp_path, cfg=cfg, run_id="run-2")
    assert first.warnings == []
    assert second.warnings == [f"tier_a_empty:{EMPTY}"]


def test_page_redirecting_to_a_robots_disallowed_url_is_not_stored(tmp_path):
    site = build_site()
    old = "https://www.qnu.edu.vn/vi/ho-so-cu"
    site.file(ROBOTS, b"User-agent: *\nDisallow: /vi/private\n", "text/plain")
    cfg = _links_seed(site, f'<p><a href="{old}">Hồ sơ</a></p>')
    site.redirect(old, PRIVATE)
    site.html(PRIVATE, article_html("Hồ sơ", "<p>không được lưu</p>"))
    stats, manifest = crawl(site, tmp_path, cfg=cfg)
    assert manifest.latest(old) is None and manifest.latest(PRIVATE) is None
    assert stats.errors == 0


def test_attachment_redirecting_to_a_robots_disallowed_url_is_not_stored(tmp_path):
    from tests.support.qnu_site import text_pdf

    site = build_site()
    hidden = "https://www.qnu.edu.vn/private/TB141.pdf"
    site.file(ROBOTS, b"User-agent: *\nDisallow: /private\n", "text/plain")
    site.redirect(PDF, hidden)
    site.file(hidden, text_pdf(), "application/pdf")
    stats, manifest = crawl(site, tmp_path)
    assert manifest.latest(PDF) is None and stats.errors == 0


def test_stored_page_now_disallowed_by_robots_is_withdrawn(tmp_path):
    site = build_site()
    crawl(site, tmp_path)
    site.file(ROBOTS, b"User-agent: *\nDisallow: /vi/dai-hoc-chinh-quy-1764/tb112\n", "text/plain")
    stats, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    assert status(manifest, A3) == ("failed", "robots_disallowed")
    assert A3 not in manifest.current() and stats.errors == 0
    assert site.count("GET", A3) == 1


def test_stored_attachment_now_redirecting_to_a_disallowed_url_is_withdrawn(tmp_path):
    from tests.support.qnu_site import text_pdf

    site = build_site()
    crawl(site, tmp_path)
    hidden = "https://www.qnu.edu.vn/private/TB141.pdf"
    site.file(ROBOTS, b"User-agent: *\nDisallow: /private\n", "text/plain")
    site.redirect(PDF, hidden)
    site.file(hidden, text_pdf(), "application/pdf")
    _, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="run-2")
    assert status(manifest, PDF) == ("failed", "robots_disallowed")
    assert PDF not in manifest.current()


STABLE = "https://www.qnu.edu.vn/vi/gioi-thieu"


def _break_stable(site, how: str) -> None:
    if how == "soft_404":
        site.html(STABLE, SOFT_404)
    else:
        site.redirect(STABLE, ERROR_PAGE)
        site.html(ERROR_PAGE, article_html("Lỗi", "<p>Trang không tồn tại.</p>"))


def _stable_site():
    site = build_site()
    site.html(STABLE, article_html("Giới thiệu", "<p>Trường Đại học Quy Nhơn.</p>"))
    return site, config(seeds=[LISTING, STABLE])


@pytest.mark.parametrize("how", ["soft_404", "error_page"])
def test_always_fetched_page_is_gone_only_after_two_consecutive_soft_404s(tmp_path, how):
    site, cfg = _stable_site()
    crawl(site, tmp_path, cfg=cfg)
    _break_stable(site, how)
    day = timedelta(days=1)
    stats, manifest = crawl(site, tmp_path, cfg=cfg, today=TODAY + day, run_id="run-2")
    assert status(manifest, STABLE) == ("text", None) and STABLE in manifest.current()
    assert stats.errors == 0
    stats, manifest = crawl(site, tmp_path, cfg=cfg, today=TODAY + 2 * day, run_id="run-3")
    assert status(manifest, STABLE) == ("failed", "gone") and STABLE not in manifest.current()
    assert stats.errors == 0


def test_a_good_scan_between_soft_404s_resets_the_miss_count(tmp_path):
    site, cfg = _stable_site()
    good = site.routes[STABLE]
    crawl(site, tmp_path, cfg=cfg)
    for n, broken in enumerate([True, False, True], start=2):
        if broken:
            _break_stable(site, "soft_404")
        else:
            site.routes[STABLE] = good
        crawl(site, tmp_path, cfg=cfg, today=TODAY + timedelta(days=n), run_id=f"run-{n}")
    manifest = Manifest(tmp_path / "manifest.jsonl")
    assert status(manifest, STABLE) == ("text", None) and STABLE in manifest.current()


def test_always_fetched_page_returning_a_real_404_is_gone_at_once(tmp_path):
    site, cfg = _stable_site()
    crawl(site, tmp_path, cfg=cfg)
    site.remove(STABLE)
    _, manifest = crawl(site, tmp_path, cfg=cfg, today=TODAY + timedelta(days=1), run_id="run-2")
    assert status(manifest, STABLE) == ("failed", "gone")


def test_drive_attachment_served_from_googleusercontent_is_stored(tmp_path):
    from tests.support.qnu_site import scanned_pdf

    site = build_site()
    uc = "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp"
    served = "https://doc-0c-9k-docs.googleusercontent.com/docs/securesc/abc/file?e=download"
    site.redirect(uc, served)
    site.file(served, scanned_pdf(), "application/pdf")
    stats, manifest = crawl(site, tmp_path)
    assert status(manifest, DRIVE) == ("needs_ocr", None)
    assert stats.errors == 0


def test_leaving_the_scope_by_redirect_is_logged(tmp_path, caplog, monkeypatch):
    import logging

    site = build_site()
    cdn = "https://cdn.example.com/TB141.pdf"
    site.redirect(PDF, cdn)
    from tests.support.qnu_site import text_pdf

    site.file(cdn, text_pdf(), "application/pdf")
    # Test khác (cấu hình logging của web app) có thể đã tắt logger này.
    crawl_logger = logging.getLogger("qnuchat.ingest.crawl")
    monkeypatch.setattr(crawl_logger, "disabled", False)
    monkeypatch.setattr(crawl_logger, "propagate", True)
    with caplog.at_level(logging.INFO, logger="qnuchat.ingest.crawl"):
        crawl(site, tmp_path)
    assert f"redirect_out_of_scope {PDF} -> {cdn}" in caplog.text


def test_real_attachment_with_a_login_word_in_its_final_url_is_stored(tmp_path):
    from tests.support.qnu_site import text_pdf

    site = build_site()
    final = "https://www.qnu.edu.vn/Resources/Docs/huong-dan-dang-nhap-xet-tuyen.pdf"
    site.redirect(PDF, final)
    site.file(final, text_pdf(), "application/pdf")
    stats, manifest = crawl(site, tmp_path)
    assert status(manifest, PDF) == ("text", None)
    assert stats.errors == 0


def test_tier_a_page_serving_the_soft_404_does_not_warn_empty(tmp_path):
    site, cfg = _stable_site()
    crawl(site, tmp_path, cfg=cfg)
    site.html(LISTING, SOFT_404)
    stats, _ = crawl(site, tmp_path, cfg=cfg, today=TODAY + timedelta(days=1), run_id="run-2")
    assert stats.warnings == []


def test_check_state_save_fsyncs_before_replace(tmp_path, monkeypatch):
    import os

    calls = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(
        os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[1]
    )
    state = CheckState(tmp_path / "last_checked.json")
    state.mark("https://www.qnu.edu.vn/a", TODAY)
    state.save()
    assert calls == ["fsync", "replace"]


def test_read_only_manifest_refuses_to_append(tmp_path):
    from dataclasses import replace

    _, written = crawl(build_site(), tmp_path)
    entry = written.latest(PDF)
    reader = Manifest(tmp_path / "manifest.jsonl", repair=False)
    with pytest.raises(RuntimeError, match="chỉ đọc"):
        reader.append(replace(entry, url="https://www.qnu.edu.vn/x"))


HUB = "https://www.qnu.edu.vn/vi/muc-con"


def test_non_seed_hub_is_refetched_without_waiting_and_gone_on_the_second_soft_404(tmp_path):
    site = build_site()
    cards = [card(f"/vi/muc-con/bai-{i}", f"Bài {i}", "01/09/2026") for i in range(3)]
    site.html(HUB, listing_html(cards, pager=False, nav=""))
    cfg = _links_seed(site, f'<p><a href="{HUB}">Mục con</a></p>')
    assert HUB not in cfg.seeds and HUB not in cfg.tier_a
    _, manifest = crawl(site, tmp_path, cfg=cfg)
    assert status(manifest, HUB) == ("text", None)
    site.html(HUB, SOFT_404)
    day = timedelta(days=1)
    before = site.count("GET", HUB)
    _, manifest = crawl(site, tmp_path, cfg=cfg, today=TODAY + day, run_id="run-2")
    assert site.count("GET", HUB) == before + 1  # hub không chờ recheck_days
    assert status(manifest, HUB) == ("text", None) and HUB in manifest.current()
    _, manifest = crawl(site, tmp_path, cfg=cfg, today=TODAY + 2 * day, run_id="run-3")
    assert status(manifest, HUB) == ("failed", "gone") and HUB not in manifest.current()


def _many_hosts_site(names: list[str], pages: int = 3):
    """Mỗi host một hạt giống có `pages` bài con; trả (site, danh sách hạt giống)."""
    site = build_site()
    seeds = []
    for name in names:
        root = f"https://{name}.qnu.edu.vn/vi/goc"
        kids = [f"https://{name}.qnu.edu.vn/vi/bai-{i}" for i in range(pages)]
        site.html(root, _listing_with(*kids))
        for i, kid in enumerate(kids):
            site.html(kid, article_html(f"Bài {name} {i}", f"<p>Nội dung {name} {i}.</p>"))
        seeds.append(root)
    return site, seeds


def _page_hosts(site) -> list[str]:
    """Host của các request trang /vi/ theo thứ tự (bỏ robots.txt, favicon)."""
    return [u.split("/")[2].split(".")[0] for _, u in site.requests if "/vi/" in u]


def test_scheduler_rotates_hosts_and_serves_tier_a_first(tmp_path):
    names = ["cea", "danguy", "doanthanhnien", "fba", "khoa", "zeta"]
    site, seeds = _many_hosts_site(names)
    cfg = config(
        seeds=seeds,
        tier_a=[seeds[-1]],  # zeta: cuối bảng chữ cái
        limits=Limits(rps_per_host=1000, hosts_parallel=2, max_file_mb=5, timeout_s=5, retries=0),
    )
    crawl(site, tmp_path, cfg=cfg)
    order = _page_hosts(site)
    # (a) không host nào bị bỏ đói; chừa độ lệch ghi log của các luồng đang chạy dở
    assert set(order[: len(names) + 2]) == set(names)
    assert "zeta" in order[:2]  # (b) hạt giống tầng A có sớm nhất


# ---------------------------------------------------------------- mốc năm (min_year, 13/10/2026)

NEW_POST = f"{LISTING}/tb200-diem-chuan"
OLD_POST = f"{LISTING}/tb090-chi-tieu"
OLDER = [f"{LISTING}/tb05{i}-cu" for i in range(2)]
UNDATED = f"{LISTING}/bai-khong-ngay"


def _dated_site():
    """Trang 1: bài 2025, bài 2019, bài không ngày. Trang 2 (postback): toàn bài 2018."""
    site = build_site()
    site.html(
        LISTING,
        listing_html(
            [
                card("/vi/dai-hoc-chinh-quy-1764/tb200-diem-chuan", "TB200", "09/08/2025"),
                card("/vi/dai-hoc-chinh-quy-1764/tb090-chi-tieu", "TB090", "10/08/2019"),
                card("/vi/dai-hoc-chinh-quy-1764/bai-khong-ngay", "Bài không ngày", ""),
            ],
            nav="",
        ),
    )
    site.post(
        LISTING,
        NEXT,
        listing_html(
            [card(u.removeprefix("https://www.qnu.edu.vn"), "Cũ", "01/07/2018") for u in OLDER],
            nav="",
        ),
    )
    for url in (NEW_POST, OLD_POST, *OLDER):
        site.html(url, article_html("Bài", "<p>Nội dung bài.</p>"))
    site.html(
        UNDATED,
        article_html(
            "Bài không ngày",
            '<p>Đính kèm: <a href="/Resources/Docs/ke-hoach-nam-2019.pdf">kế hoạch cũ</a>,'
            ' <a href="/Resources/Docs/ke-hoach-nam-2024.pdf">kế hoạch mới</a>.</p>',
        ),
    )
    for year in (2019, 2024):
        site.file(
            f"https://www.qnu.edu.vn/Resources/Docs/ke-hoach-nam-{year}.pdf",
            text_pdf(f"Ke hoach nam {year} cua Truong Dai hoc Quy Nhon, noi dung day du."),
            "application/pdf",
        )
    return site


def test_min_year_skips_old_cards_and_stops_paging_at_an_all_old_page(tmp_path):
    site = _dated_site()
    crawl(site, tmp_path, cfg=config(min_year=2023))
    assert site.count("GET", NEW_POST) == 1 and site.count("GET", UNDATED) == 1
    assert site.count("GET", OLD_POST) == 0
    assert all(site.count("GET", url) == 0 for url in OLDER)
    assert site.count("POST", LISTING) == 1  # trang 2 toàn bài 2018: không lật tiếp


def test_without_min_year_old_posts_are_still_crawled(tmp_path):
    site = _dated_site()
    crawl(site, tmp_path)
    assert site.count("GET", OLD_POST) == 1


def test_attachment_year_comes_from_its_name_when_the_page_has_no_date(tmp_path):
    site = _dated_site()
    _, manifest = crawl(site, tmp_path, cfg=config(min_year=2023))
    old_pdf = "https://www.qnu.edu.vn/Resources/Docs/ke-hoach-nam-2019.pdf"
    new_pdf = "https://www.qnu.edu.vn/Resources/Docs/ke-hoach-nam-2024.pdf"
    assert site.count("GET", old_pdf) == 0 and manifest.latest(old_pdf) is None
    assert site.count("GET", new_pdf) == 1 and new_pdf in manifest.current()


def test_stored_page_found_old_on_recheck_is_withdrawn(tmp_path):
    site = _dated_site()
    crawl(site, tmp_path)  # chưa đặt mốc: lưu cả bài không ngày
    assert status(Manifest(tmp_path / "manifest.jsonl"), UNDATED) == ("text", None)
    # Lần kiểm lại sau 30 ngày, CMS nay cho thấy ngày đăng 2019 ở ô ngày đầu bài.
    site.html(
        UNDATED,
        article_html("Bài không ngày", "<p>Nội dung bài.</p>").replace(
            "<body>", '<body><div class="date fa fa-clock-o">05/03/2019</div>'
        ),
    )
    _, manifest = crawl(
        site, tmp_path, cfg=config(min_year=2023), today=TODAY + timedelta(days=31), run_id="r2"
    )
    assert status(manifest, UNDATED) == ("failed", "out_of_range")
    assert UNDATED not in manifest.current()
    assert NEW_POST in manifest.current()


def test_seed_page_is_never_dropped_for_its_year(tmp_path):
    site = _dated_site()
    seed = f"{LISTING}/tuyen-sinh-nam-2019"
    site.html(seed, article_html("Tuyển sinh 2019", "<p>Trang hạt giống.</p>"))
    _, manifest = crawl(site, tmp_path, cfg=config(min_year=2023, seeds=[LISTING, seed]))
    assert status(manifest, seed) == ("text", None)


@pytest.mark.parametrize("reason", ["off_topic", "people_photo", "operator_removed"])
def test_off_topic_items_are_not_refetched_on_recheck(tmp_path, reason):
    # Bộ lọc chủ đề (prune, spec knowledge base §5) hay lọc ảnh người (prune-people) đã rút: lần
    # kiểm lại không tải về lưu lại.
    site = build_site()
    _, manifest = crawl(site, tmp_path)
    for url in (A3, IMG):
        manifest.append(
            dataclasses.replace(
                manifest.latest(url),
                sha256=None,
                mime=None,
                bytes=None,
                text_status="failed",
                reason=reason,
                crawl_run="prune",
            )
        )
    _, manifest = crawl(site, tmp_path, today=TODAY + timedelta(days=31), run_id="r2")
    assert site.count("GET", A3) == 1 and site.count("GET", IMG) == 1
    assert status(manifest, A3) == ("failed", reason)
    assert A3 not in manifest.current() and IMG not in manifest.current()


def test_progress_is_reported_after_every_item(tmp_path):
    seen = []
    stats, _ = crawl(build_site(), tmp_path, on_progress=seen.append)
    assert [p.done for p in seen] == list(range(1, len(seen) + 1))
    assert seen[-1].queued == 0
    assert seen[-1].pages_new == stats.pages_new
    assert seen[-1].files_new == stats.files_new
    assert seen[-1].errors == stats.errors
