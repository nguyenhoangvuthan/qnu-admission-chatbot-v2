"""Một lần chạy job quét: khoá → ghi run 'running' → Crawler → đóng run → xoá fetch log cũ.

Job chỉ quét và ghi kho; OCR và dựng snapshot là bước sau.
"""

import dataclasses
import fcntl
import hashlib
import logging
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from qnuchat.ingest import favicon
from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.config import CrawlConfig
from qnuchat.ingest.crawl import Crawler, CrawlProgress, CrawlStats
from qnuchat.ingest.crawl_log import CrawlLog
from qnuchat.ingest.dating import date_from_body, infer_year, is_before
from qnuchat.ingest.drive import fetch_file
from qnuchat.ingest.fetch import Fetcher, FetchError, FetchEvent
from qnuchat.ingest.frontier import Frontier
from qnuchat.ingest.html_page import parse_page
from qnuchat.ingest.manifest import Manifest, ManifestEntry
from qnuchat.ingest.state import CheckState
from qnuchat.ingest.topic_filter.ledger import TopicPolicy
from qnuchat.ingest.undated import page_text
from qnuchat.ingest.urls import canonicalize, drive_file_id, in_scope

logger = logging.getLogger(__name__)

FETCH_LOG_DAYS = 90
FRONTIER_FILE = "frontier.jsonl"  # hàng đợi của lần quét bị dừng, nạp lại ở lần sau


@contextmanager
def _crawl_lock(data_dir: Path) -> Iterator[bool]:
    """Khoá `crawl.lock` dùng chung cho job quét và `restore`: True nếu giữ được khoá."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "crawl.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def _close_failed(log: CrawlLog, run_id: UUID, crawler: Crawler | None, note: str) -> None:
    """Đóng run 'failed' với số đếm dở dang. Flush log lỗi thì chỉ ghi log: việc đóng run quan
    trọng hơn dòng fetch_log còn lại."""
    try:
        log.flush()
    except Exception:
        logger.exception("flush_failed_while_closing_run %s", run_id)
    try:
        log.finish_run(
            run_id, status="failed", stats=crawler.stats if crawler else CrawlStats(), note=note
        )
    except Exception:
        # Không để lỗi đóng run che lỗi gốc đang được xử lý/ném lại.
        logger.exception("finish_run_failed_while_closing_run %s", run_id)


def run_job(
    *,
    trigger: str,
    cfg: CrawlConfig,
    config_hash: str,
    data_dir: Path,
    sources_index: Mapping[str, str],
    log: CrawlLog,
    make_fetcher: Callable[[Callable[[FetchEvent], None]], Fetcher],
    today: date,
    now: Callable[[], datetime],
    out: Callable[[str], None] = print,
    on_progress: Callable[[CrawlProgress], None] | None = None,
) -> int:
    with _crawl_lock(data_dir) as held:
        if not held:
            out("Đang có một lần quét khác chạy: bỏ qua lần này.")
            return 3
        run_id = log.start_run(trigger=trigger, config_hash=config_hash)
        logger.info("crawl_start run=%s trigger=%s", run_id, trigger)
        fetcher: Fetcher | None = None
        crawler: Crawler | None = None
        try:
            # Mọi bước sau start_run (kể cả dựng đối tượng, flush log) nằm trong try để run luôn
            # được đóng, không kẹt 'running'.
            fetcher = make_fetcher(lambda event: log.log_fetch(run_id, event))
            crawler = Crawler(
                cfg,
                config_hash=config_hash,
                run_id=str(run_id),
                fetcher=fetcher,
                manifest=Manifest(data_dir / "manifest.jsonl"),
                blobs=BlobStore(data_dir),
                state=CheckState(data_dir / "last_checked.json"),
                frontier=Frontier(data_dir / FRONTIER_FILE),
                sources_index=sources_index,
                today=today,
                now=now,
                on_progress=on_progress,
            )
            stats = crawler.run()
            log.flush()
            if (left := log.pending()) > 0:
                stats.warnings.append(f"fetch_log_unflushed:{left}")
        except Exception as exc:  # noqa: BLE001 - mọi lỗi giữa chừng đều phải đóng run 'failed'
            _close_failed(log, run_id, crawler, f"{type(exc).__name__}: {exc}")
            out(f"Lần quét {run_id} hỏng: {type(exc).__name__}: {exc}")
            return 1
        except BaseException:
            _close_failed(log, run_id, crawler, "interrupted")
            raise
        finally:
            if fetcher is not None:
                fetcher.close()
        status = "warning" if stats.warnings else "ok"
        log.finish_run(run_id, status=status, stats=stats, note="; ".join(stats.warnings) or None)
        pruned = log.prune_fetch_log(now() - timedelta(days=FETCH_LOG_DAYS))
        out(
            f"Lần quét {run_id} ({status}): {stats.pages_new} trang mới, "
            f"{stats.pages_changed} trang đổi, {stats.files_new} file mới, "
            f"{stats.files_changed} file đổi, {stats.skipped_pii} bỏ vì danh sách người, "
            f"{stats.auth_required} cần đăng nhập, {stats.needs_ocr} chờ OCR, "
            f"{stats.errors} lỗi; "
            f"xoá {pruned} dòng fetch_log cũ."
        )
        return 0


def restore(*, data_dir: Path, fetcher: Fetcher, out: Callable[[str], None] = print) -> int:
    """Tải lại mọi blob còn thiếu theo manifest (tầng B không commit; `quarantine/` của mọi
    tầng cũng không commit), đặt đúng chỗ: thư mục tầng, hoặc `quarantine/` khi chờ OCR.

    URL đã đổi nội dung thì báo, không thay và không ghi gì (spec §6.4). Giữ `crawl.lock` như
    job quét để không chạy chồng. Mã thoát: 0 đủ, 1 có URL hỏng/đổi, 3 đang có lần quét khác.
    """
    with _crawl_lock(data_dir) as held:
        if not held:
            out("Đang có một lần quét khác chạy: chạy restore sau.")
            return 3
        manifest, blobs = Manifest(data_dir / "manifest.jsonl"), BlobStore(data_dir)
        failed = 0
        for url, entry in sorted(manifest.current().items()):
            if blobs.path(entry.sha256) is not None:
                continue
            try:
                file_id = drive_file_id(url)
                response = fetch_file(fetcher, file_id) if file_id else fetcher.get(url)
                data: bytes | None = response.content
                if entry.kind == "page":
                    data = parse_page(data, response.final_url).main_html.encode("utf-8")
                elif entry.kind == "favicon":
                    data = favicon.to_png(data)
                if data is None or hashlib.sha256(data).hexdigest() != entry.sha256:
                    # Không ghi bytes lệch: blob trùng của URL khác (tầng A…) phải còn nguyên.
                    failed += 1
                    out(
                        f"{url}: đã đổi nội dung so với manifest (chạy lại job quét để lấy bản mới)"
                    )
                    continue
                blobs.put(data, tier=entry.tier, quarantine=entry.text_status == "needs_ocr")
            except FetchError as exc:
                failed += 1
                out(f"{url}: không tải được ({exc.cause})")
            except Exception as exc:  # noqa: BLE001 - một entry hỏng không dừng cả restore
                failed += 1
                out(f"{url}: lỗi khi khôi phục ({type(exc).__name__}: {exc})")
        return 1 if failed else 0


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _withdrawal(
    entry: ManifestEntry, reason: str, *, now: Callable[[], datetime], config_hash: str
) -> ManifestEntry:
    """Dòng rút mục khỏi kho: `failed` + lý do, không sha; dòng cũ giữ nguyên."""
    return dataclasses.replace(
        entry,
        sha256=None,
        mime=None,
        bytes=None,
        text_status="failed",
        reason=reason,
        retrieved_at=now().isoformat(timespec="seconds"),
        crawl_run="prune",
        config_hash=config_hash,
        sources_yaml_ref=None,
    )


def prune_exempt(cfg: CrawlConfig) -> set[str]:
    """Hạt giống và tầng A: `prune` không rút theo năm hay chủ đề."""
    aliases = cfg.host_aliases
    return {u for u in (canonicalize(x, aliases=aliases) for x in [*cfg.seeds, *cfg.tier_a]) if u}


def topic_withdrawals(
    current: dict[str, ManifestEntry],
    topic: TopicPolicy,
    *,
    exempt: set[str],
    state: CheckState,
) -> list[ManifestEntry]:
    """Mục bộ lọc chủ đề rút: mục gán `loai` được áp, và ảnh đi theo trang bị rút trừ khi chính ảnh
    được gán `giu`. Trang xét trước để ảnh biết trang chứa nó đã bị rút chưa."""
    chosen: list[ManifestEntry] = []
    off_pages: set[str] = set()
    for url, entry in sorted(current.items(), key=lambda item: item[1].kind != "page"):
        if entry.kind == "favicon" or entry.tier == "A" or url in exempt or state.is_hub(url):
            continue
        if topic.withdraws(url, entry.sha256):
            chosen.append(entry)
            if entry.kind == "page":
                off_pages.add(url)
        elif (
            entry.kind == "image"
            and entry.page_url in off_pages
            and not topic.keeps(url, entry.sha256)
        ):
            chosen.append(entry)
    return chosen


def prune(
    *,
    data_dir: Path,
    cfg: CrawlConfig,
    config_hash: str,
    today: date,
    now: Callable[[], datetime],
    topic: TopicPolicy | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Áp phạm vi và mốc năm hiện hành lên kho đã có (spec §6.5):

    1. Mục thuộc site trường nay ngoài phạm vi (blocklist) → rút, lý do `out_of_scope`.
    2. Mục biết chắc năm < `min_year` → rút, `out_of_range`. Hạt giống, tầng A và trang hub
       giữ. Ảnh/file không có năm riêng đi theo trang chứa nó khi trang đã bị rút vì năm.
    3. Có `topic`: mục bộ lọc chủ đề gán `loai` (của Kent, hoặc của phiên bản đã đo đạt) → rút,
       `off_topic`, xem `topic_withdrawals`.
    4. Xoá blob và chữ OCR của mục đã rút (mọi phiên bản), trừ blob còn được mục đang dùng.
    5. Trang thường chưa suy được năm: bỏ lịch kiểm để lần quét sau tải lại, đọc ngày đăng.

    Manifest chỉ ghi thêm: rút là thêm dòng `failed`, không xoá dòng cũ. Giữ `crawl.lock`.
    Chạy lại không đổi gì thêm. Mã thoát: 0 xong, 3 đang có lần quét khác."""
    with _crawl_lock(data_dir) as held:
        if not held:
            out("Đang có một lần quét khác chạy: chạy prune sau.")
            return 3
        manifest, blobs = Manifest(data_dir / "manifest.jsonl"), BlobStore(data_dir)
        state = CheckState(data_dir / "last_checked.json")
        exempt = prune_exempt(cfg)
        bare = cfg.host_suffix.lstrip(".")
        counts: Counter[str] = Counter()

        def withdraw(entry: ManifestEntry, reason: str) -> None:
            manifest.append(_withdrawal(entry, reason, now=now, config_hash=config_hash))
            counts[reason] += 1

        def removed_for_age(url: str | None) -> bool:
            latest = manifest.latest(url) if url else None
            return latest is not None and latest.reason == "out_of_range"

        current = manifest.current()
        for url, entry in current.items():
            if (entry.host == bare or entry.host.endswith(cfg.host_suffix)) and not in_scope(
                url, cfg
            ):
                withdraw(entry, "out_of_scope")
        if cfg.min_year is not None:
            current = manifest.current()
            # Trang trước, để ảnh/file biết trang chứa nó đã bị rút chưa.
            ordered = sorted(current.items(), key=lambda item: item[1].kind != "page")
            for url, entry in ordered:
                if entry.kind == "favicon" or url in exempt or state.is_hub(url):
                    continue
                # Chỉ lấy năm theo trang chứa khi đó là bài: trang chủ/hub hay mang tiêu đề của
                # bài nổi bật (cũ), ảnh trên đó không thuộc năm ấy.
                parent_url = (
                    entry.page_url
                    if entry.page_url
                    and entry.page_url != url
                    and entry.page_url not in exempt
                    and not state.is_hub(entry.page_url)
                    else None
                )
                parent = current.get(parent_url) if parent_url else None
                year = infer_year(
                    url=url,
                    title=entry.title,
                    published=_day(entry.published),
                    today=today,
                    parent_published=_day(parent.published) if parent else None,
                    parent_url=parent_url,
                    parent_title=parent.title if parent else None,
                )
                follows_page = (
                    entry.kind != "page"
                    and year is None
                    and entry.page_url != url
                    and removed_for_age(entry.page_url)
                )
                # Trang không suy được năm: chữ trong trang chỉ hiện hành trước mốc (RUNBOOK 4.2).
                stale_text = (
                    entry.kind == "page"
                    and year is None
                    and date_from_body(page_text(entry, blobs), floor=cfg.min_year, today=today)
                    .decision
                    == "remove"
                )
                if is_before(year, cfg.min_year) or follows_page or stale_text:
                    withdraw(entry, "out_of_range")
        if topic is not None:
            for entry in topic_withdrawals(manifest.current(), topic, exempt=exempt, state=state):
                withdraw(entry, "off_topic")
        keep = {entry.sha256 for entry in manifest.current().values()}
        deleted, freed = set(), 0
        for entry in manifest.entries():
            sha = entry.sha256
            latest = manifest.latest(entry.url)
            if not sha or sha in keep or sha in deleted or latest is None:
                continue
            if latest.reason not in ("out_of_range", "out_of_scope", "off_topic"):
                continue
            path = blobs.path(sha)
            if path is not None:
                freed += path.stat().st_size
                blobs.delete(sha)
            for ocr_file in (data_dir / "ocr").glob(f"*/{sha}*.json"):
                ocr_file.unlink()
            deleted.add(sha)
        recheck = 0
        if cfg.min_year is not None:
            for url, entry in manifest.current().items():
                if (
                    entry.kind == "page"
                    and url not in exempt
                    and state.known(url)
                    and not state.is_hub(url)
                    and infer_year(
                        url=url, title=entry.title, published=_day(entry.published), today=today
                    )
                    is None
                ):
                    state.forget(url)
                    recheck += 1
            state.save()
        out(
            f"prune: rút {counts['out_of_range']} mục trước năm {cfg.min_year} (out_of_range), "
            f"{counts['out_of_scope']} mục ngoài phạm vi (out_of_scope), "
            f"{counts['off_topic']} mục ngoài chủ đề (off_topic); xoá {len(deleted)} blob "
            f"({freed / 1024 / 1024:.1f} MB); {recheck} trang chưa rõ năm chờ lần quét sau."
        )
        return 0
