"""`attachments_always_from`: PDF CTĐT trong thân trang ngành tuyensinh luôn tải (Kent 10/11/2026).

PDF CTĐT 2022–2023 bị chặn ở bốn chỗ: mẫu URL trong blocklist, `min_year`, `topic_gate.exclude` và
`prune`. File trong phần nội dung chính của trang con thuộc URL khai báo được bỏ qua cả bốn; robots,
host, tiêu đề danh sách người và nội dung chứa thông tin người vẫn chặn.
"""

from datetime import UTC, datetime

from qnuchat.ingest import crawl as crawl_module
from qnuchat.ingest import crawl_job as job
from qnuchat.ingest.config import TopicGate
from qnuchat.ingest.manifest import Manifest
from tests.ingest.test_ingest_crawl import TODAY, config, crawl, status
from tests.support.qnu_site import FakeSite, article_html, text_pdf

PARENT = "https://www.qnu.edu.vn/vi/tong-hop-nganh-dao-tao"
NGANH = f"{PARENT}/20-kinh-te"
CTDT = "https://www.qnu.edu.vn/Resources/Docs/CONG%20KHAI%20CTDT%202022-2023/DH/CTDT%20KINH%20TE.pdf"
BLOCK_CTDT_2022 = r"/CONG(?:%20| |\+)KHAI(?:%20| |\+)CTDT(?:%20| |\+)20(?:0\d|1\d|2[0-3])"
CTDT_LINK = "/Resources/Docs/CONG%20KHAI%20CTDT%202022-2023/DH/CTDT%20KINH%20TE.pdf"


def site_with(body: str, sidebar: str = "") -> FakeSite:
    site = FakeSite()
    site.html(NGANH, article_html("Kinh tế", body, sidebar=sidebar))
    site.file(CTDT, text_pdf(), "application/pdf")
    return site


def cfg(always=(PARENT,)):
    return config(
        seeds=[NGANH],
        tier_a=[NGANH],
        min_year=2024,
        blocklist_url_patterns=[BLOCK_CTDT_2022],
        topic_gate=TopicGate(include=["nganh"], exclude=["ctdt", "chuong-trinh-dao-tao"]),
        attachments_always_from=list(always),
    )


BODY = f'<p>Thời gian đào tạo 4 năm.</p><a href="{CTDT_LINK}">XEM CHƯƠNG TRÌNH ĐÀO TẠO</a>'


def test_ctdt_pdf_in_the_body_of_a_major_page_is_stored_despite_year_blocklist_and_gate(tmp_path):
    site = site_with(BODY)
    _, manifest = crawl(site, tmp_path, cfg=cfg())
    assert status(manifest, CTDT) == ("text", None)
    assert manifest.latest(CTDT).page_url == NGANH


def test_without_the_parent_listed_the_ctdt_pdf_stays_blocked(tmp_path):
    site = site_with(BODY)
    crawl(site, tmp_path, cfg=cfg(always=["https://tuyensinh.qnu.edu.vn/vi/tong-hop-nganh-dao-tao"]))
    assert site.count("GET", CTDT) == 0


def test_ctdt_pdf_in_the_sidebar_stays_blocked(tmp_path):
    site = site_with("<p>Thời gian đào tạo 4 năm.</p>", sidebar=f'<a href="{CTDT_LINK}">CTĐT</a>')
    crawl(site, tmp_path, cfg=cfg())
    assert site.count("GET", CTDT) == 0


def test_people_list_title_still_skips_the_file(tmp_path):
    site = site_with(f'<a href="{CTDT_LINK}">Danh sách sinh viên khoá 46</a>')
    _, manifest = crawl(site, tmp_path, cfg=cfg())
    assert status(manifest, CTDT)[0] == "skipped_pii"


def test_prune_keeps_the_ctdt_pdf(tmp_path):
    site = site_with(BODY)
    crawl(site, tmp_path, cfg=cfg())
    job.prune(
        data_dir=tmp_path,
        cfg=cfg(),
        config_hash="c" * 64,
        today=TODAY,
        now=lambda: datetime(2026, 10, 12, 3, tzinfo=UTC),
        out=lambda _: None,
    )
    assert CTDT in Manifest(tmp_path / "manifest.jsonl", repair=False).current()


def test_a_queued_always_attachment_survives_the_frontier_round_trip():
    item = crawl_module._Asset(CTDT, "file", NGANH, "A", "CTĐT", None, always=True)
    assert crawl_module._item_from_row(crawl_module._item_to_row(item)) == item
