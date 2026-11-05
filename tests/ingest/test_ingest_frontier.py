"""Hàng đợi quét lưu ra `frontier.jsonl`: dừng giữa chừng (Ctrl-C, SIGTERM) rồi chạy lại không
sót link đã thấy mà chưa tải, không quét lại từ đầu."""

import json
import logging
import os
import signal
import threading
from datetime import UTC, date, datetime

import httpx
import pytest

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.config import CrawlConfig, Limits
from qnuchat.ingest.crawl import Crawler
from qnuchat.ingest.fetch import Fetcher
from qnuchat.ingest.frontier import Frontier
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.state import CheckState
from tests.support.qnu_site import LISTING, article_html, build_site, card, listing_html, text_pdf

TODAY = date(2026, 10, 12)
ARTICLES = [f"{LISTING}/bai-{i}" for i in range(3)]
# Chỉ bài 0 (trang thường, không phải hub) link tới file này.
ATTACHMENT = "https://www.qnu.edu.vn/Resources/Docs/bai-0.pdf"


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


def three_article_site():
    site = build_site()
    cards = []
    for i, url in enumerate(ARTICLES):
        path = url.removeprefix("https://www.qnu.edu.vn")
        cards.append(card(path, f"Bài {i}", "01/09/2026"))
        extra = f'<a href="{ATTACHMENT}">Tệp đính kèm</a>' if i == 0 else ""
        site.html(url, article_html(f"Bài {i}", f"<p>Nội dung {i}.</p>{extra}"))
    site.html(LISTING, listing_html(cards, pager=False, nav=""))
    site.file(ATTACHMENT, text_pdf(), "application/pdf")
    return site


def make_crawler(handler, root, *, cfg=None, frontier=None, state=None):
    fetcher = Fetcher(
        user_agent="UA",
        rps_per_host=1000,
        timeout_s=5,
        max_bytes=5_000_000,
        retries=0,
        transport=httpx.MockTransport(handler),
    )
    crawler = Crawler(
        cfg or config(),
        config_hash="h",
        run_id="run-1",
        fetcher=fetcher,
        manifest=Manifest(root / "manifest.jsonl"),
        blobs=BlobStore(root),
        state=state or CheckState(root / "last_checked.json"),
        frontier=frontier if frontier is not None else Frontier(root / "frontier.jsonl"),
        sources_index={},
        today=TODAY,
        now=lambda: datetime(2026, 10, 12, 2, tzinfo=UTC),
    )
    return crawler, fetcher


class _InterruptAt:
    """Khi worker xin `url`: gửi SIGINT cho tiến trình (như Ctrl-C) rồi giữ request tới khi test
    cho đi tiếp — `url` đang tải dở đúng lúc lưu điểm dừng."""

    def __init__(self, site, url):
        self.site, self.url = site, url
        self.release = threading.Event()

    def handler(self, request):
        if str(request.url) == self.url and not self.release.is_set():
            os.kill(os.getpid(), signal.SIGINT)
            self.release.wait(5)
        return self.site.handler(request)


def frontier_urls(path) -> list[str]:
    return [json.loads(line)["url"] for line in path.read_text(encoding="utf-8").splitlines()]


def test_interrupt_saves_state_and_queue_and_the_next_run_resumes(tmp_path):
    site = three_article_site()
    stop = _InterruptAt(site, ARTICLES[1])
    crawler, fetcher = make_crawler(stop.handler, tmp_path)
    try:
        with pytest.raises(KeyboardInterrupt):
            crawler.run()
        # Điểm dừng đã ghi trước khi run() ném lại: bài đang tải dở, rồi hàng đợi theo thứ tự.
        assert frontier_urls(tmp_path / "frontier.jsonl") == [ARTICLES[1], ARTICLES[2], ATTACHMENT]
        state = CheckState(tmp_path / "last_checked.json")
        assert state.known(LISTING) and state.known(ARTICLES[0])
        assert not state.known(ARTICLES[1]) and not state.known(ARTICLES[2])
    finally:
        stop.release.set()
        crawler.join_workers()
        fetcher.close()

    crawler, fetcher = make_crawler(site.handler, tmp_path)
    try:
        crawler.run()
    finally:
        fetcher.close()
    assert site.count("GET", ARTICLES[0]) == 1  # đã xong ở lần trước: không tải lại
    # Bài 0 không được tải lại nên không ai tìm lại file của nó; chỉ hàng đợi đã lưu còn giữ.
    assert site.count("GET", ATTACHMENT) == 1
    entry = Manifest(tmp_path / "manifest.jsonl").latest(ATTACHMENT)
    assert entry is not None and entry.text_status == "text"
    assert not (tmp_path / "frontier.jsonl").exists()  # quét hết thì xoá điểm dừng


def test_a_finished_run_leaves_no_frontier(tmp_path):
    site = three_article_site()
    crawler, fetcher = make_crawler(site.handler, tmp_path)
    try:
        crawler.run()
    finally:
        fetcher.close()
    assert not (tmp_path / "frontier.jsonl").exists()


def test_frontier_round_trips_pages_and_assets(tmp_path):
    rows = [
        {"type": "page", "url": ARTICLES[0], "published": "2026-09-01"},
        {
            "type": "asset",
            "url": "https://www.qnu.edu.vn/Resources/Docs/TB141.pdf",
            "kind": "file",
            "page_url": ARTICLES[0],
            "tier": "A",
            "title": "TB141",
            "published": None,
        },
    ]
    frontier = Frontier(tmp_path / "frontier.jsonl")
    frontier.save(rows)
    assert Frontier(tmp_path / "frontier.jsonl").load() == rows
    frontier.clear()
    assert frontier.load() == []
    frontier.clear()  # xoá khi không có file: không lỗi


def test_broken_lines_and_items_now_out_of_scope_are_dropped(tmp_path, caplog, monkeypatch):
    site = three_article_site()
    orphan = f"{LISTING}/bai-mo-coi"  # không trang nào link tới: chỉ có trong điểm dừng
    blocked = f"{LISTING}/bai-bi-chan"
    site.html(orphan, article_html("Mồ côi", "<p>Chỉ có trong hàng đợi.</p>"))
    site.html(blocked, article_html("Bị chặn", "<p>Cấu hình mới chặn.</p>"))
    lines = [
        json.dumps({"type": "page", "url": orphan, "published": None}),
        "{hỏng",
        json.dumps({"type": "page", "url": blocked, "published": None}),
        json.dumps({"type": "lạ", "url": orphan}),
    ]
    (tmp_path / "frontier.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cfg = config(blocklist_url_patterns=["bai-bi-chan"])
    crawler, fetcher = make_crawler(site.handler, tmp_path, cfg=cfg)
    # Test khác (cấu hình logging của web app) có thể đã tắt các logger này.
    for name in ("qnuchat.ingest.crawl", "qnuchat.ingest.frontier"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)
        monkeypatch.setattr(logging.getLogger(name), "propagate", True)
    try:
        with caplog.at_level(logging.WARNING, logger="qnuchat.ingest"):
            crawler.run()
    finally:
        fetcher.close()
    assert site.count("GET", orphan) == 1
    assert site.count("GET", blocked) == 0
    assert "frontier_line_dropped" in caplog.text


class _RecordingFrontier(Frontier):
    def __init__(self, path):
        super().__init__(path)
        self.saves: list[list[dict]] = []

    def save(self, rows):
        self.saves.append(list(rows))
        super().save(rows)


def test_queue_is_saved_together_with_the_state_every_200_marks(tmp_path):
    site = build_site()
    cards = []
    for i in range(205):
        path = f"/vi/dai-hoc-chinh-quy-1764/bai-{i}"
        cards.append(card(path, f"Bài {i}", "01/09/2026"))
        site.html(
            f"https://www.qnu.edu.vn{path}", article_html(f"Bài {i}", f"<p>Nội dung {i}.</p>")
        )
    site.html(LISTING, listing_html(cards, pager=False, nav=""))
    frontier = _RecordingFrontier(tmp_path / "frontier.jsonl")
    crawler, fetcher = make_crawler(site.handler, tmp_path, frontier=frontier)
    try:
        crawler.run()
    finally:
        fetcher.close()
    (saved,) = frontier.saves  # đúng một lần lưu định kỳ (mốc 200), lần cuối là xoá
    assert {row["url"] for row in saved} >= {
        f"https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/bai-{i}" for i in range(201, 205)
    }
    assert not (tmp_path / "frontier.jsonl").exists()
