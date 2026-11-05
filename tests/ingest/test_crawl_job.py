import dataclasses
import fcntl
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from qnuchat.ingest import crawl_job as job
from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.config import CrawlConfig, Limits, load_crawl_config
from qnuchat.ingest.crawl_job import FETCH_LOG_DAYS, restore, run_job
from qnuchat.ingest.fetch import Fetcher
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.urls import source_id_for
from tests.support.crawllog import InMemoryCrawlLog
from tests.support.qnu_site import LISTING, article_html, build_site

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 2, 0, tzinfo=UTC)
CFG = CrawlConfig(
    seeds=[LISTING],
    host_suffix=".qnu.edu.vn",
    tier_a=[LISTING],
    pii_title_skip=["danh sách (sinh viên|thí sinh|học viên)"],
    limits=Limits(rps_per_host=1000, hosts_parallel=2, max_file_mb=5, timeout_s=5, retries=0),
    user_agent="UA {contact}",
)


def factory(site):
    def make(on_fetch):
        return Fetcher(
            user_agent="UA",
            rps_per_host=1000,
            timeout_s=5,
            max_bytes=5_000_000,
            retries=0,
            transport=httpx.MockTransport(site.handler),
            on_fetch=on_fetch,
        )

    return make


def run(site, data_dir, log, lines):
    return run_job(
        trigger="cli",
        cfg=CFG,
        config_hash="h",
        data_dir=data_dir,
        sources_index={},
        log=log,
        make_fetcher=factory(site),
        today=TODAY,
        now=lambda: NOW,
        out=lines.append,
    )


def test_job_records_the_run_every_fetch_and_prunes_old_logs(tmp_path):
    site, log, lines = build_site(), InMemoryCrawlLog(), []
    assert run(site, tmp_path, log, lines) == 0
    (record,) = log.runs.values()
    assert record["status"] == "ok" and record["pages_new"] == 3 and record["trigger"] == "cli"
    # Fetcher tự theo chuyển hướng và chỉ báo một sự kiện cho mỗi yêu cầu logic, ghi URL đã yêu
    # cầu: đích redirect (/Login.aspx) là request thô nhưng không có sự kiện riêng; URL nguồn
    # redirect và robots.txt (một request logic) đều có.
    requested = {url for _, url in site.requests}
    hop_targets = {"https://www.qnu.edu.vn/Login.aspx"}
    logged = {event.url for _, event in log.fetches}
    assert logged == requested - hop_targets
    assert "https://www.qnu.edu.vn/vi/quan-tri" in logged
    assert "https://www.qnu.edu.vn/robots.txt" in logged
    assert len(log.fetches) == len(site.requests) - len(hop_targets & requested)
    assert log.pruned_before == [NOW - timedelta(days=FETCH_LOG_DAYS)]
    assert any("3 trang mới" in line for line in lines)
    assert (tmp_path / "manifest.jsonl").exists() and (tmp_path / "last_checked.json").exists()


def test_a_second_job_while_one_is_running_exits_3(tmp_path):
    lock = tmp_path / "crawl.lock"
    tmp_path.mkdir(exist_ok=True)
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log, lines = InMemoryCrawlLog(), []
        assert run(build_site(), tmp_path, log, lines) == 3
    assert log.runs == {} and "khác" in lines[-1]


def test_a_crash_marks_the_run_failed_with_partial_stats(tmp_path, monkeypatch):
    def boom(self):
        self.stats.pages_new = 1
        raise RuntimeError("đứt giữa chừng")

    monkeypatch.setattr(job.Crawler, "run", boom)
    log, lines = InMemoryCrawlLog(), []
    assert run(build_site(), tmp_path, log, lines) == 1
    (record,) = log.runs.values()
    assert record["status"] == "failed" and record["pages_new"] == 1
    assert "RuntimeError: đứt giữa chừng" in record["note"]


def test_warnings_make_the_run_a_warning(tmp_path):
    site = build_site()
    empty = "https://www.qnu.edu.vn/vi/trong"
    site.html(empty, "<html><body><p>trống</p></body></html>")
    cfg = CFG.model_copy(update={"seeds": [LISTING, empty], "tier_a": [LISTING, empty]})
    log = InMemoryCrawlLog()
    code = run_job(
        trigger="schedule",
        cfg=cfg,
        config_hash="h",
        data_dir=tmp_path,
        sources_index={},
        log=log,
        make_fetcher=factory(site),
        today=TODAY,
        now=lambda: NOW,
        out=lambda _: None,
    )
    (record,) = log.runs.values()
    assert code == 0 and record["status"] == "warning" and record["note"] == f"tier_a_empty:{empty}"


def test_restore_refetches_missing_tier_b_blobs_and_reports_changed_ones(tmp_path):
    site = build_site()
    cfg = CFG.model_copy(
        update={"tier_a": ["https://www.qnu.edu.vn/vi/khong-co"]}
    )  # mọi thứ thành tầng B
    run_job(
        trigger="cli",
        cfg=cfg,
        config_hash="h",
        data_dir=tmp_path,
        sources_index={},
        log=InMemoryCrawlLog(),
        make_fetcher=factory(site),
        today=TODAY,
        now=lambda: NOW,
        out=lambda _: None,
    )
    manifest, blobs = Manifest(tmp_path / "manifest.jsonl"), BlobStore(tmp_path)
    pdf = manifest.current()["https://www.qnu.edu.vn/Resources/Docs/TB141.pdf"]
    blobs.path(pdf.sha256).unlink()
    a3 = manifest.current()[f"{LISTING}/tb112-chi-tieu"]
    blobs.path(a3.sha256).unlink()
    site.html(
        f"{LISTING}/tb112-chi-tieu",
        "<html><body><div class='chitietbaiviet'>đã đổi</div></body></html>",
    )
    lines: list[str] = []
    fetcher = factory(site)(lambda _: None)
    assert restore(data_dir=tmp_path, fetcher=fetcher, out=lines.append) == 1
    assert blobs.path(pdf.sha256) is not None and blobs.path(a3.sha256) is None
    assert any("tb112-chi-tieu" in line and "đã đổi nội dung" in line for line in lines)


def test_cli_parser_knows_the_three_commands():
    from apps.cli.crawl import build_parser

    parser = build_parser()
    assert parser.parse_args(["run", "--trigger", "schedule"]).trigger == "schedule"
    assert parser.parse_args(["status"]).command == "status"
    assert parser.parse_args(["restore"]).command == "restore"
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--trigger", "cron"])


IMG = "https://www.qnu.edu.vn/Resources/Images/bang1.png"
DRIVE = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view"
PDF = "https://www.qnu.edu.vn/Resources/Docs/TB141.pdf"


def test_restore_brings_back_tier_a_blobs_lost_from_quarantine(tmp_path):
    site = build_site()
    assert run(site, tmp_path, InMemoryCrawlLog(), []) == 0
    manifest, blobs = Manifest(tmp_path / "manifest.jsonl"), BlobStore(tmp_path)
    img, scan = manifest.current()[IMG], manifest.current()[DRIVE]
    assert img.tier == scan.tier == "A"
    shutil.rmtree(tmp_path / "quarantine")
    lines: list[str] = []
    assert restore(data_dir=tmp_path, fetcher=factory(site)(lambda _: None), out=lines.append) == 0
    assert blobs.path(img.sha256) == tmp_path / "quarantine" / img.sha256
    assert blobs.path(scan.sha256) == tmp_path / "quarantine" / scan.sha256
    assert lines == []


def test_restore_never_deletes_a_blob_shared_with_another_entry(tmp_path):
    site = build_site()
    assert run(site, tmp_path, InMemoryCrawlLog(), []) == 0
    manifest = Manifest(tmp_path / "manifest.jsonl")
    pdf = manifest.current()[PDF]
    other = "https://www.qnu.edu.vn/Resources/Docs/ban-sao.pdf"
    # Tầng B, blob không còn trên đĩa; nay URL trả đúng bytes của PDF tầng A ở URL khác.
    manifest.append(
        dataclasses.replace(
            pdf, url=other, source_id=source_id_for(other), tier="B", sha256="0" * 64
        )
    )
    site.file(other, site.routes[PDF][2], "application/pdf")
    lines: list[str] = []
    assert restore(data_dir=tmp_path, fetcher=factory(site)(lambda _: None), out=lines.append) == 1
    assert BlobStore(tmp_path).path(pdf.sha256) == tmp_path / "blobs" / "A" / pdf.sha256
    assert any("ban-sao.pdf" in line and "đã đổi nội dung" in line for line in lines)


def test_restore_while_a_crawl_holds_the_lock_exits_3_and_touches_nothing(tmp_path):
    site = build_site()
    assert run(site, tmp_path, InMemoryCrawlLog(), []) == 0
    pdf = Manifest(tmp_path / "manifest.jsonl").current()[PDF]
    BlobStore(tmp_path).path(pdf.sha256).unlink()
    site.requests.clear()
    lines: list[str] = []
    with (tmp_path / "crawl.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code = restore(data_dir=tmp_path, fetcher=factory(site)(lambda _: None), out=lines.append)
    assert code == 3 and site.requests == [] and "khác" in lines[-1]
    assert BlobStore(tmp_path).path(pdf.sha256) is None


def test_in_memory_log_recent_runs_counts_fetches(tmp_path):
    log = InMemoryCrawlLog()
    assert run(build_site(), tmp_path, log, []) == 0
    (row,) = log.recent_runs()
    assert row["n_fetch"] == len(log.fetches) > 0
    assert row["n_fetch_errors"] == sum(1 for _, e in log.fetches if e.error_cause)


def test_a_failure_building_the_crawler_closes_the_run_failed(tmp_path):
    (tmp_path / "manifest.jsonl").write_text("không phải json\n", encoding="utf-8")
    log, lines = InMemoryCrawlLog(), []
    assert run(build_site(), tmp_path, log, lines) == 1
    (record,) = log.runs.values()
    assert record["status"] == "failed" and "ValueError" in record["note"]


def test_a_failing_final_flush_closes_the_run_failed(tmp_path):
    class FlushBoom(InMemoryCrawlLog):
        def flush(self):
            raise RuntimeError("DB đứt khi flush")

    log, lines = FlushBoom(), []
    assert run(build_site(), tmp_path, log, lines) == 1
    (record,) = log.runs.values()
    assert record["status"] == "failed" and "DB đứt khi flush" in record["note"]


def test_keyboard_interrupt_closes_the_run_failed_then_propagates(tmp_path, monkeypatch):
    def interrupted(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(job.Crawler, "run", interrupted)
    log = InMemoryCrawlLog()
    with pytest.raises(KeyboardInterrupt):
        run(build_site(), tmp_path, log, [])
    (record,) = log.runs.values()
    assert record["status"] == "failed" and record["note"] == "interrupted"


def test_restore_counts_a_broken_entry_as_failed_and_continues(tmp_path, monkeypatch):
    site = build_site()
    cfg = CFG.model_copy(update={"tier_a": ["https://www.qnu.edu.vn/vi/khong-co"]})
    run_job(
        trigger="cli",
        cfg=cfg,
        config_hash="h",
        data_dir=tmp_path,
        sources_index={},
        log=InMemoryCrawlLog(),
        make_fetcher=factory(site),
        today=TODAY,
        now=lambda: NOW,
        out=lambda _: None,
    )
    manifest, blobs = Manifest(tmp_path / "manifest.jsonl"), BlobStore(tmp_path)
    pdf = manifest.current()[PDF]
    page = manifest.current()[f"{LISTING}/tb112-chi-tieu"]
    blobs.path(pdf.sha256).unlink()
    blobs.path(page.sha256).unlink()

    def broken(data, url, **_):
        raise ValueError("HTML hỏng")

    monkeypatch.setattr(job, "parse_page", broken)
    lines: list[str] = []
    assert restore(data_dir=tmp_path, fetcher=factory(site)(lambda _: None), out=lines.append) == 1
    assert blobs.path(pdf.sha256) is not None  # entry sau vẫn được khôi phục
    assert blobs.path(page.sha256) is None
    assert any("tb112-chi-tieu" in line and "HTML hỏng" in line for line in lines)


@pytest.fixture
def crawler_env(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.chdir(tmp_path)  # không đọc .env của repo
    monkeypatch.setenv("QNUCHAT_CRAWL_CONTACT_EMAIL", "a@example.org")
    monkeypatch.setenv("QNUCHAT_CRAWL_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setenv(
        "QNUCHAT_CRAWL_CONFIG", str(Path(__file__).parents[2] / "configs/crawl/qnu.yaml")
    )


def test_status_reads_the_run_log_without_a_database(crawler_env, capsys):
    from apps.cli.crawl import main

    assert main(["status"]) == 0
    assert capsys.readouterr().err == ""


def test_restore_with_an_empty_store_exits_0(crawler_env):
    from apps.cli.crawl import main

    assert main(["restore"]) == 0


@pytest.mark.parametrize("command", [["prune"], ["status"]])
def test_offline_commands_need_no_contact_email(crawler_env, monkeypatch, command):
    from apps.cli.crawl import main

    monkeypatch.delenv("QNUCHAT_CRAWL_CONTACT_EMAIL")
    assert main(command) == 0


@pytest.mark.parametrize("command", [["run"], ["restore"]])
def test_fetching_commands_say_clearly_when_contact_email_is_missing(
    crawler_env, monkeypatch, capsys, command
):
    from apps.cli.crawl import main

    monkeypatch.delenv("QNUCHAT_CRAWL_CONTACT_EMAIL")
    assert main(command) == 2
    assert "QNUCHAT_CRAWL_CONTACT_EMAIL" in capsys.readouterr().err


def test_a_failing_finish_run_never_replaces_the_original_exception(tmp_path, monkeypatch):
    class CloseBoom(InMemoryCrawlLog):
        def finish_run(self, *a, **kw):
            raise RuntimeError("không đóng được run")

    def interrupted(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(job.Crawler, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(build_site(), tmp_path, CloseBoom(), [])


def test_unflushed_fetch_log_rows_make_the_run_a_warning(tmp_path):
    class Stuck(InMemoryCrawlLog):
        def pending(self):
            return 5

    log = Stuck()
    assert run(build_site(), tmp_path, log, []) == 0
    (record,) = log.runs.values()
    assert record["status"] == "warning" and "fetch_log_unflushed:5" in record["note"]


def test_job_resumes_the_saved_queue_and_clears_it_when_done(tmp_path):
    site = build_site()
    orphan = f"{LISTING}/bai-mo-coi"  # không trang nào link tới: chỉ có trong hàng đợi đã lưu
    site.html(orphan, article_html("Mồ côi", "<p>Chỉ có trong hàng đợi.</p>"))
    frontier = tmp_path / "frontier.jsonl"
    frontier.write_text(
        json.dumps({"type": "page", "url": orphan, "published": None}) + "\n", encoding="utf-8"
    )
    assert run(site, tmp_path, InMemoryCrawlLog(), []) == 0
    assert site.count("GET", orphan) == 1
    assert not frontier.exists()


def test_sigterm_stops_the_run_like_ctrl_c_and_exits_130(crawler_env, monkeypatch, capsys):
    import os
    import signal
    import time

    from apps.cli import crawl as cli

    def slow_job(**kwargs):
        os.kill(os.getpid(), signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:  # chờ handler chạy ở luồng chính
            time.sleep(0.01)
        raise AssertionError("SIGTERM không thành KeyboardInterrupt")

    monkeypatch.setattr(cli, "load_sources_index", lambda path: {})
    monkeypatch.setattr(cli, "run_job", slow_job)
    before = signal.getsignal(signal.SIGTERM)
    assert cli.main(["run"]) == 130
    assert "frontier.jsonl" in capsys.readouterr().err
    assert signal.getsignal(signal.SIGTERM) is before  # trả lại handler cũ


def test_a_second_signal_does_not_cut_the_checkpoint_short(crawler_env, monkeypatch, capsys):
    """systemctl stop (KillMode=control-group) gửi SIGTERM cho cả uv lẫn python, uv lại chuyển
    tiếp: python nhận hai lần. Lần thứ hai không được cắt ngang việc lưu điểm dừng."""
    import os
    import signal
    import time

    from apps.cli import crawl as cli

    finished: list[bool] = []

    def job_saving_on_interrupt(**kwargs):
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                time.sleep(0.01)
            raise AssertionError("SIGTERM không thành KeyboardInterrupt")
        except KeyboardInterrupt:
            os.kill(os.getpid(), signal.SIGTERM)  # bản uv chuyển tiếp
            os.kill(os.getpid(), signal.SIGINT)
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:  # "đang lưu điểm dừng"
                time.sleep(0.01)
            finished.append(True)
            raise

    monkeypatch.setattr(cli, "load_sources_index", lambda path: {})
    monkeypatch.setattr(cli, "run_job", job_saving_on_interrupt)
    before = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))
    assert cli.main(["run"]) == 130
    assert finished == [True]
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before


# ---------------------------------------------------------------- prune (mốc năm, 13/10/2026)

PRUNE_CFG = CrawlConfig(
    **{**CFG.model_dump(), "min_year": 2023, "blocklist_hosts": ["qes.qnu.edu.vn"]}
)
W = "https://www.qnu.edu.vn"


def _put(
    manifest, blobs, url, *, kind="page", published=None, page_url=None, title=None, data=None
):
    from qnuchat.ingest.manifest import ManifestEntry

    data = data if data is not None else url.encode()
    sha = blobs.put(data, tier="B")
    manifest.append(
        ManifestEntry(
            url=url,
            source_id=source_id_for(url),
            page_url=page_url,
            kind=kind,
            title=title,
            published=published,
            retrieved_at="2026-10-13T08:00:00+07:00",
            sha256=sha,
            mime="text/html" if kind == "page" else "image/png",
            bytes=len(data),
            host=url.split("/")[2],
            tier="B",
            text_status="text" if kind == "page" else "needs_ocr",
            reason=None,
            crawl_run="r1",
            config_hash="h",
            sources_yaml_ref=None,
        )
    )
    return sha


def _prune(data_dir, lines, cfg=PRUNE_CFG):
    return job.prune(
        data_dir=data_dir,
        cfg=cfg,
        config_hash="h2",
        today=date(2026, 10, 13),
        now=lambda: NOW,
        out=lines.append,
    )


@pytest.mark.parametrize("kind", ["page", "file", "image"])
@pytest.mark.parametrize(
    ("published", "removed"),
    [("2022-12-31", True), ("2023-12-31", True), ("2024-01-01", False), (None, False)],
)
def test_qnu_prune_removes_through_2023_and_keeps_2024_or_undated(
    tmp_path, kind, published, removed
):
    """Cấu hình thật phải loại cả năm 2023, giữ mốc 2024 và mục chưa rõ năm."""
    cfg, _ = load_crawl_config(Path(__file__).resolve().parents[2] / "configs/crawl/qnu.yaml")
    manifest, blobs = Manifest(tmp_path / "manifest.jsonl"), BlobStore(tmp_path)
    url = f"{W}/vi/tin/tai-lieu-kiem-tra"
    sha = _put(manifest, blobs, url, kind=kind, published=published)

    assert _prune(tmp_path, [], cfg) == 0

    manifest = Manifest(tmp_path / "manifest.jsonl")
    assert (url not in manifest.current()) is removed
    assert (blobs.path(sha) is None) is removed
    assert manifest.latest(url).reason == ("out_of_range" if removed else None)


@pytest.fixture
def pruned_store(tmp_path):
    from qnuchat.ingest.state import CheckState

    manifest, blobs = Manifest(tmp_path / "manifest.jsonl"), BlobStore(tmp_path)
    state = CheckState(tmp_path / "last_checked.json")
    shas = {
        "old": _put(manifest, blobs, f"{W}/vi/tin/hoi-thao", published="2019-05-01"),
        "new": _put(manifest, blobs, f"{W}/vi/tin/tuyen-sinh", published="2025-06-01"),
        "url_year": _put(manifest, blobs, f"{W}/vi/tin/ban-tin-nam-2020-so-1"),
        "old_img": _put(
            manifest,
            blobs,
            f"{W}/Temp/ArticleImage/a.jpg",
            kind="image",
            page_url=f"{W}/vi/tin/hoi-thao",
        ),
        "new_img": _put(
            manifest,
            blobs,
            f"{W}/Temp/ArticleImage/b.jpg",
            kind="image",
            page_url=f"{W}/vi/tin/tuyen-sinh",
        ),
        # File cũ trùng nội dung với file của bài mới: blob dùng chung, không được xoá.
        "shared": _put(
            manifest,
            blobs,
            f"{W}/Resources/Docs/ke-hoach-nam-2018.pdf",
            kind="file",
            page_url=f"{W}/vi/gioi-thieu",
            data=b"cung-noi-dung",
        ),
        "qes": _put(manifest, blobs, "https://qes.qnu.edu.vn/calendar/view.php?time=1"),
        "undated": _put(manifest, blobs, f"{W}/vi/gioi-thieu"),
        "hub": _put(manifest, blobs, f"{W}/vi/tin"),
        "seed": _put(manifest, blobs, f"{LISTING}/tuyen-sinh-nam-2019"),
    }
    # Trang chủ/hub mang tiêu đề của bài nổi bật cũ: ảnh trên đó không lấy năm theo hub.
    _put(manifest, blobs, f"{W}/vi/tin", title="Tuyển sinh thạc sĩ đợt 2 năm 2019")
    shas["hub_img"] = _put(
        manifest, blobs, f"{W}/Temp/ArticleImage/c.jpg", kind="image", page_url=f"{W}/vi/tin"
    )
    _put(
        manifest,
        blobs,
        f"{W}/Resources/Docs/ke-hoach-2025.pdf",
        kind="file",
        page_url=f"{W}/vi/tin/tuyen-sinh",
        data=b"cung-noi-dung",
    )
    for url in (f"{W}/vi/gioi-thieu", f"{W}/vi/tin/tuyen-sinh"):
        state.mark(url, date(2026, 10, 13))
    state.mark(f"{W}/vi/tin", date(2026, 10, 13), hub=True)
    state.save()
    cfg = CrawlConfig(
        **{**PRUNE_CFG.model_dump(), "seeds": [LISTING, f"{LISTING}/tuyen-sinh-nam-2019"]}
    )
    return tmp_path, shas, cfg


def test_prune_withdraws_old_and_out_of_scope_entries_and_deletes_their_blobs(pruned_store):
    data_dir, shas, cfg = pruned_store
    lines: list[str] = []
    assert _prune(data_dir, lines, cfg) == 0
    manifest, blobs = Manifest(data_dir / "manifest.jsonl"), BlobStore(data_dir)
    reasons = {
        url: (e.text_status, e.reason)
        for url, e in ((u, manifest.latest(u)) for u in {e.url for e in manifest.entries()})
    }
    assert reasons[f"{W}/vi/tin/hoi-thao"] == ("failed", "out_of_range")
    assert reasons[f"{W}/vi/tin/ban-tin-nam-2020-so-1"] == ("failed", "out_of_range")
    # Ảnh không có năm riêng của bài cũ đi theo bài.
    assert reasons[f"{W}/Temp/ArticleImage/a.jpg"] == ("failed", "out_of_range")
    assert reasons[f"{W}/Resources/Docs/ke-hoach-nam-2018.pdf"] == ("failed", "out_of_range")
    assert reasons["https://qes.qnu.edu.vn/calendar/view.php?time=1"] == ("failed", "out_of_scope")
    current = manifest.current()
    for url in (
        f"{W}/vi/tin/tuyen-sinh",
        f"{W}/Temp/ArticleImage/b.jpg",
        f"{W}/vi/gioi-thieu",
        f"{W}/vi/tin",
        f"{LISTING}/tuyen-sinh-nam-2019",
    ):
        assert url in current
    for key in ("old", "url_year", "old_img", "qes"):
        assert blobs.path(shas[key]) is None
    assert f"{W}/Temp/ArticleImage/c.jpg" in current
    for key in ("new", "new_img", "shared", "undated", "seed", "hub_img"):
        assert blobs.path(shas[key]) is not None
    assert any("out_of_range" in line and "out_of_scope" in line for line in lines)


def test_prune_makes_undated_non_hub_pages_due_for_a_recheck(pruned_store):
    from qnuchat.ingest.state import CheckState

    data_dir, _, cfg = pruned_store
    _prune(data_dir, [], cfg)
    state = CheckState(data_dir / "last_checked.json")
    assert not state.known(f"{W}/vi/gioi-thieu")  # chưa rõ năm: lần quét sau tải lại để suy ngày
    assert state.known(f"{W}/vi/tin/tuyen-sinh")  # đã có ngày đăng
    assert state.is_hub(f"{W}/vi/tin")


def test_prune_twice_changes_nothing_the_second_time(pruned_store):
    data_dir, _, cfg = pruned_store
    _prune(data_dir, [], cfg)
    lines_before = (data_dir / "manifest.jsonl").read_text(encoding="utf-8")
    _prune(data_dir, [], cfg)
    assert (data_dir / "manifest.jsonl").read_text(encoding="utf-8") == lines_before


def test_prune_without_min_year_only_removes_out_of_scope(pruned_store):
    data_dir, _, cfg = pruned_store
    no_floor = CrawlConfig(**{**cfg.model_dump(), "min_year": None})
    _prune(data_dir, [], no_floor)
    manifest = Manifest(data_dir / "manifest.jsonl")
    assert f"{W}/vi/tin/hoi-thao" in manifest.current()
    assert "https://qes.qnu.edu.vn/calendar/view.php?time=1" not in manifest.current()


def test_prune_while_a_crawl_holds_the_lock_exits_3(pruned_store):
    data_dir, _, cfg = pruned_store
    before = (data_dir / "manifest.jsonl").read_text(encoding="utf-8")
    with (data_dir / "crawl.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert _prune(data_dir, [], cfg) == 3
    assert (data_dir / "manifest.jsonl").read_text(encoding="utf-8") == before


def test_cli_run_writes_the_run_log_that_status_reads(crawler_env, monkeypatch, tmp_path, capsys):
    """Đường thật của `quet-web.sh`: `run` ghi log file, `status` đọc lại; không có database."""
    from apps.cli import crawl as cli

    site = build_site()
    monkeypatch.setattr(cli, "load_crawl_config", lambda path: (CFG, "h"))
    monkeypatch.setattr(cli, "load_sources_index", lambda path: {})
    monkeypatch.setattr(
        cli,
        "Fetcher",
        lambda **kw: Fetcher(**kw, transport=httpx.MockTransport(site.handler)),
    )

    assert cli.main(["run"]) == 0
    assert (tmp_path / "web" / "manifest.jsonl").exists()
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    line = capsys.readouterr().out
    assert "ok" in line and "MB" in line
