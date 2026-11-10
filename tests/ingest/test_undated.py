"""Trang không có ngày đăng (RUNBOOK 4.2): danh sách cho Kent duyệt và luật rút trong `prune`."""

import csv
from datetime import UTC, date, datetime

from apps.cli.crawl import main
from qnuchat.ingest import crawl_job as job
from qnuchat.ingest.config import CrawlConfig, Limits
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.undated import render_review, undated_pages
from tests.support.webstore import TS, W, WebStore, html_page, png_bytes

SEED = f"{TS}/vi/tong-hop-nganh-dao-tao"
MAJOR = f"{TS}/vi/tong-hop-nganh-dao-tao/nganh-luat"
OLD = f"{W}/vi/tin/thong-bao-tuyen-sinh"
DORM = f"{W}/vi/ky-tuc-xa"
CURRENT = f"{W}/vi/nganh-tuyen-sinh"
DATED = f"{W}/vi/tin/ke-hoach-nam-2025"
OLD_IMG = f"{W}/Temp/bang.png"
TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 2, 0, tzinfo=UTC)
CFG = CrawlConfig(
    seeds=[SEED],
    host_suffix=".qnu.edu.vn",
    tier_a=[SEED],
    pii_title_skip=[],
    min_year=2024,
    limits=Limits(rps_per_host=1000, hosts_parallel=2, max_file_mb=5, timeout_s=5, retries=0),
    user_agent="UA {contact}",
)


def make_store(tmp_path):
    web = WebStore(tmp_path)
    web.put(SEED, title="Tổng hợp ngành", tier="A")
    web.put(MAJOR, title="Ngành Luật",
            data=html_page("Ngành Luật", "Tuyển sinh đại học chính quy năm 2022."))
    web.put(OLD, title="Thông báo",
            data=html_page("Thông báo", "Thông báo tuyển sinh đại học chính quy năm 2022."))
    web.put(OLD_IMG, kind="image", page_url=OLD, data=png_bytes(), text_status="text")
    web.put(DORM, title="Ký túc xá",
            data=html_page("Ký túc xá", "Từ năm học 2020-2021, nhà trường trang bị camera."))
    web.put(CURRENT, title="Ngành tuyển sinh",
            data=html_page("Ngành tuyển sinh", "Các ngành đào tạo đại học năm 2025."))
    web.put(DATED, title="Kế hoạch năm 2025",
            data=html_page("Kế hoạch", "Tuyển sinh đại học chính quy năm 2022."))
    return web


def test_lists_every_undated_page_with_a_decision_including_exempt_ones(tmp_path):
    web = make_store(tmp_path)
    pages = undated_pages(web.current(), web.blobs, floor=2024, today=TODAY)
    rows = {r.entry.url: r for r in pages}
    assert set(rows) == {SEED, MAJOR, OLD, DORM, CURRENT}  # DATED có năm trong URL/tiêu đề
    assert (rows[OLD].dating.decision, rows[OLD].dating.year) == ("remove", 2022)
    assert rows[DORM].dating.decision == "review"
    assert (rows[CURRENT].dating.decision, rows[CURRENT].dating.year) == ("keep", 2025)


def prune(web):
    job.prune(
        data_dir=web.root,
        cfg=CFG,
        config_hash="c" * 64,
        today=TODAY,
        now=lambda: NOW,
        out=lambda _: None,
    )
    return Manifest(web.root / "manifest.jsonl", repair=False)


def test_prune_withdraws_pages_whose_text_is_current_only_before_the_floor(tmp_path):
    web = make_store(tmp_path)
    manifest = prune(web)
    current = manifest.current()
    assert OLD not in current and manifest.latest(OLD).reason == "out_of_range"
    assert OLD_IMG not in current  # ảnh đi theo trang chứa
    assert MAJOR not in current
    # Hạt giống được miễn; cần duyệt, hiện hành, hay đã có năm trong tiêu đề thì giữ.
    assert {SEED, DORM, CURRENT, DATED} <= set(current)


def test_prune_never_withdraws_an_exempt_page_by_its_text(tmp_path):
    web = make_store(tmp_path)
    web.put(SEED, title="Tổng hợp ngành", tier="A",
            data=html_page("Tổng hợp ngành", "Tuyển sinh đại học chính quy năm 2020."))
    assert SEED in prune(web).current()


def test_cli_writes_the_review_list(tmp_path, monkeypatch):
    web = make_store(tmp_path)
    out = tmp_path / "undated.csv"
    config = tmp_path / "crawl.yaml"
    config.write_text(
        "seeds: [" + SEED + "]\nhost_suffix: .qnu.edu.vn\ntier_a: [" + SEED + "]\n"
        "pii_title_skip: []\nmin_year: 2024\n"
        "limits: {rps_per_host: 1, hosts_parallel: 1, max_file_mb: 5, timeout_s: 5, retries: 0}\n"
        "user_agent: 'UA {contact}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QNUCHAT_CRAWL_CONFIG", str(config))
    monkeypatch.setenv("QNUCHAT_CRAWL_DATA_DIR", str(web.root))
    assert main(["undated", "--out", str(out)]) == 0
    rows = {r["url"]: r for r in csv.DictReader(out.open(encoding="utf-8"))}
    assert set(rows) == {SEED, MAJOR, OLD, DORM, CURRENT}
    assert rows[SEED]["exempt"] == "yes" and rows[MAJOR]["exempt"] == "no"
    assert rows[MAJOR]["decision"] == "remove" and rows[MAJOR]["year"] == "2022"
    assert rows[DORM]["decision"] == "review" and "năm học 2020-2021" in rows[DORM]["evidence"]
    assert rows[CURRENT]["year"] == "2025"
    page = out.with_suffix(".html").read_text(encoding="utf-8")
    assert all(url in page for url in rows)


def section(page, url):
    start = page.index(f'data-url="{url}"')
    return page[start : page.index("</section>", start)]


def test_review_page_shows_each_page_text_evidence_and_both_choices(tmp_path):
    web = make_store(tmp_path)
    web.put(f"{W}/vi/the", title="<b>Thẻ</b>", data=html_page("Thẻ", "Chữ &lt;script&gt;x thường."))
    pages = undated_pages(web.current(), web.blobs, floor=2024, today=TODAY)
    page = render_review(pages, web.blobs, exempt=lambda url: url == SEED)

    dorm = section(page, DORM)
    assert 'data-decision="review"' in dorm and 'data-exempt="no"' in dorm
    assert f'data-sha="{web.current()[DORM].sha256}"' in dorm
    assert "<mark>Từ năm học 2020-2021</mark>, nhà trường trang bị camera." in dorm
    assert 'value="vao"' in dorm and 'value="khong"' in dorm
    assert 'data-exempt="yes"' in section(page, SEED)
    # Chữ trang và tiêu đề là dữ liệu, không phải HTML.
    other = section(page, f"{W}/vi/the")
    assert "<script>x" not in other and "&lt;script&gt;x" in other
    assert "&lt;b&gt;Thẻ&lt;/b&gt;" in other


def test_review_page_drops_template_junk_and_folds_menu_runs():
    from qnuchat.ingest.undated import display_text

    menu = "\n".join(f"Mục {i}" for i in range(10))
    junk = "{1}\n##LOC[OK]##\n##LOC[Cancel]##"
    text = f"{junk}\n{menu}\n\nNăm học 2025-2026 khoa tuyển 80 chỉ tiêu ngành."
    out = display_text(text, "năm học 2025-2026")
    assert "{1}" not in out and "##LOC" not in out
    assert "<details" in out and "10 dòng ngắn" in out and "Mục 9" in out
    body = out[out.index("</details>") :]
    assert "<mark>Năm học 2025-2026</mark> khoa tuyển 80 chỉ tiêu ngành." in body
