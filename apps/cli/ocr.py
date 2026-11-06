"""OCR file chờ trong kho web bằng cấu hình `cur_rotgate`.

uv run python -m apps.cli.ocr verify     # OCR lại trang chuẩn, phải giống data/ocr-data từng dòng
uv run python -m apps.cli.ocr run        # OCR file trong quarantine/, chỉ ghi checkpoint
uv run python -m apps.cli.ocr status     # còn bao nhiêu trang
uv run python -m apps.cli.ocr review     # xem file nào giữ, file nào là danh sách người
uv run python -m apps.cli.ocr apply      # áp kết quả vào kho (xoá file danh sách người)
uv run python -m apps.cli.ocr remove <sha256>...  # xoá hẳn file, lần quét sau không tải lại

Dừng bằng Ctrl-C hay SIGTERM: worker làm xong ảnh đang dở rồi thoát, chạy lại thì làm tiếp. Mã thoát
`run`, `verify`: 0 xong, 1 không đạt, 2 chưa đủ điều kiện, 3 môi trường lệch, 4 không nạp được
engine, 5 không có GPU, 130 bị dừng.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apps.cli.progress import Progress, say, setup_logging
from qnuchat.ingest.ocr import job, worker

DATA_DIR = Path("data/web")
CORPUS = Path("data/ocr-data/corpus.json")
DATA_ROOT = Path("data")
VERIFY_DIR = Path("artifacts/ocr/verify")
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
EXIT_FAILED = 1
EXIT_NOT_READY = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="OCR lại trang chuẩn và so từng dòng")
    verify.add_argument("--limit", type=int, help="chỉ kiểm N trang đầu; không mở khoá `run`")
    run = sub.add_parser("run", help="OCR file trong quarantine/")
    run.add_argument("--retry-errors", action="store_true", help="chạy lại trang bị lỗi")
    sub.add_parser("status", help="tiến độ OCR")
    sub.add_parser("review", help="kết quả từng file, chưa đổi gì trong kho")
    sub.add_parser("apply", help="áp kết quả vào kho")
    remove = sub.add_parser("remove", help="xoá hẳn file theo sha256")
    remove.add_argument("sha256", nargs="+")
    return parser


def _gpu_ready() -> bool:
    used = job.gpu_used_mib()
    if used < job.GPU_BUSY_MIB:
        return True
    print(
        f"GPU đang dùng {used} MiB, cần dưới {job.GPU_BUSY_MIB} MiB: tắt vLLM rồi chạy lại.",
        file=sys.stderr,
    )
    return False


def _progress(desc: str) -> tuple[Progress, Callable[[dict], None]]:
    bar = Progress(desc)
    errors = 0

    def show(event: dict) -> None:
        nonlocal errors
        if event["event"] == "image":
            errors += not event["ok"]
            bar.update(note=f"lỗi {errors}")
        elif event["event"] == "fatal":
            say(f"LỖI {event['kind']}: {event['message']}")

    return bar, show


def _verify(limit: int | None) -> int:
    bar, show = _progress("Kiểm tương đương")
    try:
        code, result = job.run_verify(
            CORPUS,
            DATA_ROOT,
            VERIFY_DIR,
            limit=limit,
            on_event=show,
            on_plan=lambda total: bar.update(0, total=total),
        )
    finally:
        bar.close()
    if result is None:
        return code
    print(f"Giống từng dòng: {result.identical}/{result.compared} trang")
    for name in result.render_mismatches:
        print(f"  ảnh đầu vào khác: {name}")
    for line in result.differences:
        print(f"  khác: {line}")
    if not result.passed:
        print("Không đạt: `run` vẫn bị khoá, không dùng worker này.", file=sys.stderr)
        return EXIT_FAILED
    if limit is not None:
        print("Đạt trên mẫu; chạy `verify` không có --limit để mở khoá `run`.")
    return worker.EXIT_OK


def _run(retry_errors: bool) -> int:
    if not job.is_verified(VERIFY_DIR / "passed.json"):
        print(
            "Worker hoặc environments/ocr đã đổi từ lần kiểm gần nhất: chạy `verify` trước.",
            file=sys.stderr,
        )
        return EXIT_NOT_READY
    bar, show = _progress("OCR")

    def planned(plan: job.Plan, total: int) -> None:
        bar.update(0, total=total)
        say(f"{len(plan.documents)} file, {total} trang; {len(plan.waiting_label)} ảnh chờ nhãn")

    try:
        return job.run_ocr(DATA_DIR, retry_errors=retry_errors, on_event=show, on_plan=planned)
    finally:
        bar.close()


def _status() -> int:
    plan = job.build_plan(DATA_DIR)
    pages = [(d, p) for d in plan.documents for p in d.pages]
    outputs = [
        worker.read_output(job.pages_dir(DATA_DIR) / f"{job.page_id(d.sha256, p)}.json")
        for d, p in pages
    ]
    failed = sum(1 for rec in outputs if rec is not None and "error" in rec)
    done = sum(1 for rec in outputs if rec is not None) - failed
    print(
        f"{len(plan.documents)} file, {len(pages)} trang: {done} xong, {failed} lỗi, "
        f"{len(pages) - done - failed} chưa làm; {len(plan.waiting_label)} ảnh chờ nhãn"
    )
    for sha in plan.missing:
        print(f"Mất file trong quarantine/: {sha}; dùng `remove` nếu cố ý xoá")
    print("Đã kiểm tương đương" if job.is_verified(VERIFY_DIR / "passed.json") else "Chưa kiểm")
    return worker.EXIT_OK


def _review(today: date) -> int:
    plan, results = job.review(DATA_DIR, today=today)
    labels = {
        "text": "giữ",
        "pii": "XOÁ (danh sách người)",
        "empty": "không có chữ",
        "error": "lỗi",
        "missing": "chưa OCR",
    }
    for result in sorted(results, key=lambda r: r.outcome):
        doc = result.document
        detail = f" [{result.detail}]" if result.detail else ""
        print(f"{labels[result.outcome]}{detail}: {doc.title[:90]} ({doc.entries[0].url})")
    for entry in plan.waiting_label:
        print(f"chờ nhãn ảnh người: {entry.url}")
    for sha in plan.missing:
        print(f"mất file trong quarantine/: {sha}")
    return worker.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging("ocr")
    now = datetime.now(TIMEZONE)
    try:
        if args.command == "verify":
            return _verify(args.limit) if _gpu_ready() else EXIT_NOT_READY
        if args.command == "run":
            return _run(args.retry_errors) if _gpu_ready() else EXIT_NOT_READY
        if args.command == "status":
            return _status()
        if args.command == "review":
            return _review(now.date())
        if args.command == "remove":
            print(f"Đã rút {job.remove_files(DATA_DIR, args.sha256, now=now)} URL khỏi kho.")
            return worker.EXIT_OK
        counts = job.apply_results(DATA_DIR, today=now.date(), now=now)
    except job.OcrBusy as exc:
        print(f"{exc}; chờ xong rồi chạy lại.", file=sys.stderr)
        return EXIT_NOT_READY
    print(
        f"Giữ {counts['text']} file, xoá {counts['pii']} file danh sách người; ở lại quarantine: "
        f"{counts['empty']} không có chữ, {counts['error']} lỗi, {counts['missing']} chưa OCR."
    )
    return worker.EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
