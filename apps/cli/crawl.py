"""Quét web trường vào `data/web/`.

uv run python -m apps.cli.crawl run --trigger cli   # quét một lần
uv run python -m apps.cli.crawl status              # 10 lần quét gần nhất
uv run python -m apps.cli.crawl restore             # tải lại blob còn thiếu theo manifest
uv run python -m apps.cli.crawl prune               # rút mục trước min_year hoặc ngoài phạm vi

Dừng `run` bằng Ctrl-C hay SIGTERM (`systemctl stop`): state và hàng đợi được lưu
(`last_checked.json`, `frontier.jsonl`), lần chạy sau tiếp tục, không quét lại từ đầu. Mã thoát 130.
"""

import argparse
import signal
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.cli.progress import Progress, say, setup_logging
from qnuchat.ingest.config import load_crawl_config
from qnuchat.ingest.crawl import CrawlProgress
from qnuchat.ingest.crawl_job import FRONTIER_FILE, prune, restore, run_job
from qnuchat.ingest.crawl_log import FileCrawlLog
from qnuchat.ingest.fetch import Fetcher
from qnuchat.ingest.manifest import load_sources_index

EXIT_INTERRUPTED = 130


class CrawlerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QNUCHAT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # `run`/`restore` cần (gửi trong User-Agent); `prune`/`status` không gọi mạng.
    crawl_contact_email: str | None = Field(
        default=None, min_length=3
    )  # thông tin cá nhân: chỉ ở môi trường, không commit
    crawl_config: Path = Path("configs/crawl/qnu.yaml")
    crawl_data_dir: Path = Path("data/web")
    sources_yaml: Path = Path("data/sources.yaml")
    timezone: str = "Asia/Ho_Chi_Minh"


_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def _stop_once(signum, frame):
    """systemd dừng unit bằng SIGTERM; mặc định Python chết ngay, không lưu gì và để run kẹt
    'running'. Đổi thành Ctrl-C để đi cùng đường dừng. Tín hiệu sau bị bỏ qua: `systemctl stop`
    (KillMode=control-group) gửi SIGTERM cho cả uv lẫn python, uv lại chuyển tiếp, nên python
    nhận hai lần — lần thứ hai từng cắt ngang việc lưu điểm dừng. Muốn giết ngay: `kill -9`."""
    for sig in _STOP_SIGNALS:
        signal.signal(sig, signal.SIG_IGN)
    raise KeyboardInterrupt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="quét một lần")
    run.add_argument("--trigger", choices=("schedule", "cli"), default="cli")
    sub.add_parser("status", help="các lần quét gần nhất")
    sub.add_parser("restore", help="tải lại blob còn thiếu theo manifest")
    sub.add_parser("prune", help="rút mục trước min_year hoặc ngoài phạm vi, xoá blob của chúng")
    return parser


def _print_status(log: FileCrawlLog) -> None:
    for run in log.recent_runs():
        print(
            f"{run['started_at'].astimezone():%d/%m/%Y %H:%M} {run['trigger']:<8} "
            f"{run['status']:<8} trang mới {run['pages_new']}, file mới {run['files_new']}, "
            f"lỗi {run['errors']}, tải {run['n_bytes'] / 1024 / 1024:.1f} MB "
            f"{run['note'] or ''}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging("crawler")
    settings = CrawlerSettings()
    cfg, config_hash = load_crawl_config(settings.crawl_config)
    tz = ZoneInfo(settings.timezone)

    if args.command in ("run", "restore") and settings.crawl_contact_email is None:
        print(
            f"Lệnh `{args.command}` cần QNUCHAT_CRAWL_CONTACT_EMAIL (biến môi trường hoặc .env): "
            "site trường cần biết ai đang quét.",
            file=sys.stderr,
        )
        return 2

    def make_fetcher(on_fetch=None) -> Fetcher:
        return Fetcher(
            user_agent=cfg.user_agent_for(settings.crawl_contact_email or ""),
            rps_per_host=cfg.limits.rps_per_host,
            timeout_s=cfg.limits.timeout_s,
            max_bytes=cfg.limits.max_file_mb * 1024 * 1024,
            retries=cfg.limits.retries,
            on_fetch=on_fetch,
        )

    if args.command == "restore":
        fetcher = make_fetcher()
        try:
            return restore(data_dir=settings.crawl_data_dir, fetcher=fetcher)
        finally:
            fetcher.close()

    if args.command == "prune":
        now = datetime.now(tz)
        return prune(
            data_dir=settings.crawl_data_dir,
            cfg=cfg,
            config_hash=config_hash,
            today=now.date(),
            now=lambda: datetime.now(tz),
        )

    log = FileCrawlLog(settings.crawl_data_dir)
    if args.command == "status":
        _print_status(log)
        return 0

    previous = {sig: signal.signal(sig, _stop_once) for sig in _STOP_SIGNALS}
    bar = Progress("Quét web")

    def show(p: CrawlProgress) -> None:
        note = f"trang mới {p.pages_new}, file mới {p.files_new}, lỗi {p.errors}"
        bar.update(total=p.done + p.queued, note=note)

    try:
        return run_job(
            trigger=args.trigger,
            cfg=cfg,
            config_hash=config_hash,
            data_dir=settings.crawl_data_dir,
            sources_index=load_sources_index(settings.sources_yaml),
            log=log,
            make_fetcher=make_fetcher,
            today=datetime.now(tz).date(),
            now=lambda: datetime.now(tz),
            out=say,
            on_progress=show,
        )
    except KeyboardInterrupt:
        print(
            f"Đã dừng lần quét; hàng đợi lưu ở {settings.crawl_data_dir / FRONTIER_FILE}, "
            "chạy lại `run` để tiếp tục.",
            file=sys.stderr,
        )
        return EXIT_INTERRUPTED
    finally:
        bar.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
