"""FileCrawlLog: log lần quét trong kho web, thay bảng crawl_runs và fetch_log của repo cũ."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qnuchat.ingest.crawl import CrawlStats
from qnuchat.ingest.crawl_log import MAX_BUFFER, FileCrawlLog
from qnuchat.ingest.fetch import FetchEvent

NOW = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)


def event(url="https://www.qnu.edu.vn/a", *, cause=None, size=1000):
    return FetchEvent(
        url=url,
        method="GET",
        source="site",
        http_status=None if cause else 200,
        error_cause=cause,
        duration_ms=5,
        sha256=None,
        bytes=size,
        at=NOW,
    )


def test_a_closed_run_keeps_its_counters_and_fetch_totals(tmp_path):
    log = FileCrawlLog(tmp_path)
    run_id = log.start_run(trigger="cli", config_hash="h1")
    log.log_fetch(run_id, event(size=1500))
    log.log_fetch(run_id, event(cause="timeout", size=None))
    log.flush()
    log.finish_run(run_id, status="ok", stats=CrawlStats(pages_new=3, files_new=1), note="n")

    (row,) = FileCrawlLog(tmp_path).recent_runs()  # đọc lại từ file, không từ bộ nhớ
    assert (row["status"], row["trigger"], row["config_hash"]) == ("ok", "cli", "h1")
    assert (row["pages_new"], row["files_new"], row["errors"]) == (3, 1, 0)
    assert (row["n_fetch"], row["n_fetch_errors"], row["n_bytes"]) == (2, 1, 1500)
    assert row["note"] == "n" and row["finished_at"] is not None


def test_a_run_never_closed_stays_running_with_zero_counters(tmp_path):
    log = FileCrawlLog(tmp_path)
    log.start_run(trigger="cli", config_hash="h1")
    (row,) = log.recent_runs()
    assert row["status"] == "running" and row["pages_new"] == 0 and row["finished_at"] is None


def test_recent_runs_are_newest_first_and_limited(tmp_path):
    runs = tmp_path / "crawl_runs.jsonl"
    rows = [
        {"id": str(i), "trigger": "cli", "status": "ok", "started_at": f"2026-11-0{i}T00:00:00"}
        for i in (1, 3, 2)
    ]
    runs.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert [r["id"] for r in FileCrawlLog(tmp_path).recent_runs(limit=2)] == ["3", "2"]


def test_a_half_written_last_line_is_ignored(tmp_path):
    log = FileCrawlLog(tmp_path)
    log.start_run(trigger="cli", config_hash="h1")
    with (tmp_path / "crawl_runs.jsonl").open("a", encoding="utf-8") as file:
        file.write('{"id": "dở')
    assert len(log.recent_runs()) == 1


def test_finish_run_refuses_an_unknown_run(tmp_path):
    with pytest.raises(RuntimeError, match="không có run"):
        FileCrawlLog(tmp_path).finish_run(uuid4(), status="ok", stats=CrawlStats())


def test_fetches_are_written_in_batches(tmp_path):
    log = FileCrawlLog(tmp_path, batch=2)
    run_id = log.start_run(trigger="cli", config_hash="h1")
    log.log_fetch(run_id, event())
    assert log.pending() == 1
    log.log_fetch(run_id, event())
    assert log.pending() == 0
    assert len((tmp_path / "fetch_log" / f"{run_id}.jsonl").read_text().splitlines()) == 2


def test_a_write_failure_keeps_rows_and_never_reaches_the_crawler(tmp_path):
    log = FileCrawlLog(tmp_path, batch=1)
    run_id = log.start_run(trigger="cli", config_hash="h1")
    (tmp_path / "fetch_log").write_text("không phải thư mục")
    log.log_fetch(run_id, event())
    assert log.pending() == 1  # job đọc số này để đánh dấu run `warning`

    (tmp_path / "fetch_log").unlink()
    log.flush()
    assert log.pending() == 0


def test_the_buffer_drops_oldest_rows_past_the_limit(tmp_path):
    log = FileCrawlLog(tmp_path, batch=MAX_BUFFER + 10)
    run_id = log.start_run(trigger="cli", config_hash="h1")
    (tmp_path / "fetch_log").write_text("không phải thư mục")
    for _ in range(MAX_BUFFER + 5):
        log.log_fetch(run_id, event())
    log.flush()
    assert log.pending() == MAX_BUFFER


def test_prune_removes_only_old_fetch_logs_and_counts_their_rows(tmp_path):
    log = FileCrawlLog(tmp_path)
    old, new = uuid4(), uuid4()
    for run_id in (old, new):
        log.log_fetch(run_id, event())
    log.flush()
    stale = (NOW - timedelta(days=100)).timestamp()
    os.utime(tmp_path / "fetch_log" / f"{old}.jsonl", (stale, stale))
    # `new` sửa lúc chạy test, sau `NOW - 90 ngày`.

    assert log.prune_fetch_log(NOW - timedelta(days=90)) == 1
    assert [p.stem for p in (tmp_path / "fetch_log").iterdir()] == [str(new)]
