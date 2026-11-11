"""Chạy và chấm một cấu hình pipeline trên bộ câu hỏi nháp (RUNBOOK mục 7, phần A).

uv run python -m apps.cli.evaluate run [--config configs/pipeline/b3-qwen3-4b-awq.yaml]
    [--mode full|retrieval] [--gold FILE ...] [--run-id ID] [--retry-errors] [--asked-at YYYY-MM-DD]
    [--base-url URL] [--embedding-device cpu] [--cache-dir DIR] [--timeout-s 120] [--runs-dir DIR]
uv run python -m apps.cli.evaluate score <run_id> [--runs-dir artifacts/runs]

`run` ghi `manifest.json`, `records.jsonl`, `excluded.jsonl` vào `artifacts/runs/<run_id>/`; chế độ
`full` cần vLLM (`./scripts/serve-vllm.sh`), chế độ `retrieval` chỉ gọi retriever. Chạy lại cùng
`--run-id` thì làm tiếp câu chưa có kết quả, giữ `asked_at` cũ; `--retry-errors` chạy lại cả câu
lỗi.
`score` chấm lại kết quả đã ghi thành `report.json` và `report.md`, không gọi model.

Mọi số là số phát triển: bộ câu hỏi còn nháp, kho chỉ có các nguồn của cấu hình.
Mã thoát: 0 xong; 1 từ chối vì hash lệch hoặc lỗi chấm; 2 vLLM không chạy hoặc sai model;
130 bị dừng bằng Ctrl-C.
"""

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import openai

from qnuchat.adapters.generation.vllm_checks import (
    VllmMismatch,
    check_served_model,
    fetch_vllm_version,
)
from qnuchat.adapters.runtime import Runtime, build_runtime
from qnuchat.core.config import LoadedConfig, load_pipeline_config
from qnuchat.core.pipeline import assemble_pipeline
from qnuchat.eval.cases import EvalCase, StaleRunError, gold_digests, read_rows, select_cases
from qnuchat.eval.runner import (
    MANIFEST,
    RECORDS,
    answer_full,
    answer_retrieval,
    open_run,
    pending,
    read_records,
    run_cases,
)
from qnuchat.eval.score import ScoreError, score_run, write_report

DEFAULT_CONFIG = Path("configs/pipeline/b3-qwen3-4b-awq.yaml")
DEFAULT_GOLD = (
    Path("benchmarks/v2/core.draft.jsonl"),
    Path("benchmarks/v2/comparison.draft.jsonl"),
)
DEFAULT_RUNS_DIR = Path("artifacts/runs")
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
API_KEY = "EMPTY"  # vLLM chạy cục bộ không kiểm khoá
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_VLLM = 2
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="chạy một cấu hình, ghi kết quả thô")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run.add_argument("--mode", choices=("full", "retrieval"), default="full")
    run.add_argument(
        "--gold", type=Path, action="append", help="file bộ câu hỏi nháp; lặp lại cho nhiều file"
    )
    run.add_argument("--run-id", help="mặc định <YYYYMMDD-HHMM>-<cấu hình>-<chế độ>")
    run.add_argument("--retry-errors", action="store_true", help="chạy lại cả câu execution_error")
    run.add_argument(
        "--asked-at",
        type=date.fromisoformat,
        help="ngày hỏi của mọi câu; mặc định ngày của lượt cũ, hoặc hôm nay nếu lượt mới",
    )
    run.add_argument(
        "--base-url", default=os.environ.get("QNUCHAT_VLLM_BASE_URL", DEFAULT_BASE_URL)
    )
    run.add_argument("--embedding-device", default="cpu")
    run.add_argument("--cache-dir", type=Path, default=Path("artifacts/cache/embeddings"))
    run.add_argument("--timeout-s", type=float, default=120.0)
    run.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

    score = sub.add_parser("score", help="chấm lượt đã chạy thành report.json và report.md")
    score.add_argument("run_id")
    score.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    return parser


def make_runtime(loaded: LoadedConfig, args: argparse.Namespace) -> Runtime:
    """Dựng runtime thật (đọc PDF, BGE-M3, client vLLM); test thay bằng fake."""
    return build_runtime(
        loaded,
        base_url=args.base_url,
        api_key=API_KEY,
        timeout_s=args.timeout_s,
        embedding_device=args.embedding_device,
        cache_dir=args.cache_dir,
    )


def served_vllm_version(runtime: Runtime, loaded: LoadedConfig, base_url: str) -> str:
    """Kiểm vLLM đang phục vụ đúng model của cấu hình rồi trả phiên bản vLLM."""
    served = [model.id for model in runtime.api.models.list().data]
    check_served_model(served, loaded.config.generator.model)
    return fetch_vllm_version(base_url, API_KEY)


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _recorded_asked_at(run_dir: Path) -> date | None:
    """`asked_at` của lượt đã có, để chạy tiếp hôm sau vẫn hỏi cùng ngày."""
    path = run_dir / MANIFEST
    if not path.exists():
        return None
    return date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["asked_at"])


def _write_excluded(run_dir: Path, excluded: Sequence[dict]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in excluded)
    (run_dir / "excluded.jsonl").write_text(text, encoding="utf-8")


class UnexpectedStageError(Exception):
    """Stage ném lỗi ngoài dự kiến; core bọc nó thành `PipelineError(cause="error")`."""


def _printer(total: int) -> Callable[[dict], None]:
    done = 0

    def show(record: dict) -> None:
        nonlocal done
        done += 1
        seconds = record["elapsed_ms"] / 1000
        print(f"[{done}/{total}] {record['status']} {seconds:.1f}s {record['id']}", flush=True)
        # Spec §5: lỗi ngoài dự kiến dừng lượt. Timeout, JSON hỏng… có cause riêng và chạy tiếp.
        error = record.get("error")
        if error is not None and error["cause"] == "error":
            raise UnexpectedStageError(
                f"câu {record['id']}, stage {error['stage']}: {error['message']}"
            )

    return show


def _run(args: argparse.Namespace) -> int:
    now = datetime.now(TIMEZONE)
    loaded = load_pipeline_config(args.config)
    gold_paths = list(args.gold or DEFAULT_GOLD)
    sources = {Path(s.path).as_posix(): s.source_id for s in loaded.config.corpus.sources}
    cases, excluded = select_cases(read_rows(gold_paths), sources)

    run_id = args.run_id or f"{now:%Y%m%d-%H%M}-{loaded.name}-{args.mode}"
    run_dir = args.runs_dir / run_id
    asked_at = args.asked_at or _recorded_asked_at(run_dir) or now.date()

    print(f"Lượt {run_id}: {len(cases)} câu giữ, {len(excluded)} câu loại. Đang dựng runtime…")
    runtime = make_runtime(loaded, args)
    vllm_version: str | None = None
    if args.mode == "full":
        try:
            vllm_version = served_vllm_version(runtime, loaded, args.base_url)
        # ValueError: /version trả nội dung không phải JSON (vd. trang lỗi của proxy).
        except (VllmMismatch, openai.OpenAIError, httpx.HTTPError, ValueError) as exc:
            print(f"vLLM chưa sẵn sàng ({args.base_url}): {exc}", file=sys.stderr)
            return EXIT_VLLM

    cfg = loaded.config
    manifest = {
        "run_id": run_id,
        "mode": args.mode,
        "label": "phát triển",
        "asked_at": asked_at.isoformat(),
        "pipeline_config_name": loaded.name,
        "pipeline_config_hash": loaded.sha256,
        "snapshot": runtime.snapshot.model_dump(mode="json"),
        "gold_files": gold_digests(gold_paths),
        "sources": sources,
        "cases": {"kept": len(cases), "excluded": len(excluded)},
        "excluded": excluded,
        "generator": {"model": cfg.generator.model, "revision": cfg.generator.revision},
        "embedding": {
            "model": cfg.embedding.model,
            "revision": cfg.embedding.revision,
            **runtime.embedding,
        },
        "vllm_version": vllm_version,
        "git_commit": _git_commit(),
        "created_at": now.isoformat(timespec="seconds"),
    }
    try:
        open_run(run_dir, manifest)
    except StaleRunError as exc:
        print(f"Từ chối chạy tiếp: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    _write_excluded(run_dir, excluded)

    answer: Callable[[EvalCase], dict]
    if args.mode == "full":
        pipeline = assemble_pipeline(
            loaded,
            snapshot=runtime.snapshot,
            retriever=runtime.retriever,
            generator=runtime.generator,
            runtime_info={"vllm_version": vllm_version},
            notice_writer=runtime.notice_writer,
        )

        def answer(case: EvalCase) -> dict:
            return answer_full(pipeline, case, asked_at)
    else:

        def answer(case: EvalCase) -> dict:
            return answer_retrieval(runtime.retriever, case)

    todo = pending(cases, read_records(run_dir / RECORDS), retry_errors=args.retry_errors)
    print(f"Còn {len(todo)}/{len(cases)} câu phải chạy; asked_at {asked_at.isoformat()}.")
    try:
        run_cases(todo, run_dir, answer, on_record=_printer(len(todo)))
    except UnexpectedStageError as exc:
        print(
            f"Dừng vì lỗi ngoài dự kiến ({exc}). Sửa lỗi rồi chạy lại cùng --run-id với "
            "--retry-errors.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    print(f"Xong. Chấm bằng: uv run python -m apps.cli.evaluate score {run_id}")
    return EXIT_OK


def _score(args: argparse.Namespace) -> int:
    run_dir = args.runs_dir / args.run_id
    if not (run_dir / MANIFEST).exists():
        print(f"Không có lượt {args.run_id}: thiếu {run_dir / MANIFEST}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        report = score_run(run_dir)
    # ValueError: records hỏng, trùng id trong bộ câu hỏi; OSError: file bộ câu hỏi không còn ở
    # đường dẫn ghi trong manifest (đường dẫn tương đối: chạy score từ gốc repo).
    except (StaleRunError, ScoreError, ValueError, OSError) as exc:
        print(f"Từ chối chấm: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    write_report(run_dir, report)
    print(run_dir / "report.json")
    print(run_dir / "report.md")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "score":
        return _score(args)
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("Đã dừng; chạy lại cùng --run-id để làm tiếp.", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    raise SystemExit(main())
