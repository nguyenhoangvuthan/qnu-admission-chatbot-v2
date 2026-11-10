"""Lọc chủ đề kho web bằng model (spec knowledge base §5).

uv run python -m apps.cli.knowledge_base topic-sample [--seed S] [--top-up N]  # mẫu + form gán nhãn
uv run python -m apps.cli.knowledge_base classify [--limit N]              # gán nhãn, cần vLLM
uv run python -m apps.cli.knowledge_base topic-score --sample DIR --labels CSV   # đo theo §5.4
uv run python -m apps.cli.knowledge_base topic-labels --sample DIR --labels CSV  # áp nhãn của Kent
uv run python -m apps.cli.knowledge_base topic-pending   # mục `prune` sẽ rút, chưa đổi gì

Dừng `classify` bằng Ctrl-C: sổ `data/web/topic.jsonl` đã ghi giữ nguyên, chạy lại thì làm tiếp.
"""

import argparse
import dataclasses
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import OpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.cli.progress import say, setup_logging, track
from qnuchat.adapters.generation.vllm_checks import check_served_model
from qnuchat.core.config import load_pipeline_config
from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.config import load_crawl_config
from qnuchat.ingest.crawl_job import prune_exempt, topic_withdrawals
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.state import CheckState
from qnuchat.ingest.topic_filter.classifier import VllmTopicClassifier
from qnuchat.ingest.topic_filter.classify import PASS, run_classify
from qnuchat.ingest.topic_filter.inputs import candidates, seed_urls
from qnuchat.ingest.topic_filter.ledger import (
    TopicLedger,
    filter_id,
    load_topic_config,
    load_topic_policy,
    prompt_hash,
)
from qnuchat.ingest.topic_filter.sample import make_sample, read_rounds
from qnuchat.ingest.topic_filter.score import kent_decisions, load_labels, score

EXIT_INTERRUPTED = 130
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


class KnowledgeBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QNUCHAT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    vllm_base_url: str | None = None  # chỉ `classify` cần
    request_timeout_s: float = 120
    crawl_config: Path = Path("configs/crawl/qnu.yaml")
    crawl_data_dir: Path = Path("data/web")
    pipeline_config: Path = Path("configs/pipeline/b3-qwen3-4b-awq.yaml")
    topic_config: Path = Path("configs/knowledge_base/topic_filter.yaml")
    topic_prompt: Path = Path("configs/knowledge_base/topic_prompt.md")
    topic_filter_dir: Path = Path("artifacts/knowledge_base/topic-filter")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    classify = sub.add_parser("classify", help="lọc chủ đề kho web bằng model")
    classify.add_argument("--limit", type=int, default=None, help="dừng sau N lần gọi model")
    sample = sub.add_parser("topic-sample", help="bốc mẫu và dựng form gán nhãn offline")
    sample.add_argument("--seed", type=int, default=None, help="mặc định sample_seed của cấu hình")
    sample.add_argument("--top-up", type=int, default=None, help="bốc thêm N mục (tuyensinh, khoa)")
    for name, text in (
        ("topic-score", "đo bộ lọc trên nhãn của Kent"),
        ("topic-labels", "ghi nhãn của Kent vào sổ, `prune` áp thẳng"),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("--sample", type=Path, required=True, help="thư mục sample-<seed>")
        command.add_argument("--labels", type=Path, required=True, help="labels.csv xuất từ form")
    sub.add_parser("topic-pending", help="mục `prune` sẽ rút theo chủ đề")
    return parser


def current_filter(settings: KnowledgeBaseSettings):
    """(filter_id, prompt_hash, generator) của bộ lọc theo cấu hình hiện hành."""
    generator = load_pipeline_config(settings.pipeline_config).config.generator
    topic = load_topic_config(settings.topic_config)
    p_hash = prompt_hash(settings.topic_prompt)
    fid = filter_id(
        prompt_hash=p_hash,
        model=generator.model,
        model_revision=generator.revision,
        max_chars=topic.max_chars,
        max_tokens=topic.max_tokens,
        pass_=PASS,
    )
    return fid, p_hash, generator


def _web(settings: KnowledgeBaseSettings):
    crawl, _ = load_crawl_config(settings.crawl_config)
    data_dir = settings.crawl_data_dir
    current = Manifest(data_dir / "manifest.jsonl", repair=False).current()
    state = CheckState(data_dir / "last_checked.json")
    return current, candidates(current, seeds=seed_urls(crawl), state=state), BlobStore(data_dir)


def _ocr_documents(settings: KnowledgeBaseSettings) -> Path:
    return settings.crawl_data_dir / "ocr" / "documents"


def _classify(args, settings: KnowledgeBaseSettings) -> int:
    if settings.vllm_base_url is None:
        print(
            "Lệnh `classify` cần QNUCHAT_VLLM_BASE_URL (biến môi trường hoặc .env).",
            file=sys.stderr,
        )
        return 2
    fid, p_hash, generator = current_filter(settings)
    topic = load_topic_config(settings.topic_config)
    current, chosen, blobs = _web(settings)
    api = OpenAI(
        base_url=settings.vllm_base_url,
        api_key="EMPTY",
        timeout=settings.request_timeout_s,
        max_retries=0,
    )
    check_served_model([m.id for m in api.models.list().data], generator.model)
    classifier = VllmTopicClassifier(
        api,
        model=generator.model,
        seed=generator.seed,
        max_tokens=topic.max_tokens,
        chat_template_kwargs=generator.chat_template_kwargs,
        prompt=settings.topic_prompt.read_text(encoding="utf-8"),
    )
    try:
        run_classify(
            current=current,
            candidates=chosen,
            classifier=classifier,
            ledger=TopicLedger(settings.crawl_data_dir / "topic.jsonl", repair=True),
            blobs=blobs,
            prompt_hash=p_hash,
            filter_id=fid,
            model=generator.model,
            model_revision=generator.revision,
            max_chars=topic.max_chars,
            now=lambda: datetime.now(TIMEZONE),
            limit=args.limit,
            ocr_documents=_ocr_documents(settings),
            out=say,
            track=lambda items: track(items, "Lọc chủ đề"),
        )
    except KeyboardInterrupt:
        print("Đã dừng; sổ topic.jsonl giữ nguyên, chạy lại để làm tiếp.", file=sys.stderr)
        return EXIT_INTERRUPTED
    return 0


def _topic_sample(args, settings: KnowledgeBaseSettings) -> int:
    cfg = load_topic_config(settings.topic_config)
    seed = cfg.sample_seed if args.seed is None else args.seed
    current, chosen, blobs = _web(settings)
    return make_sample(
        settings.topic_filter_dir / f"sample-{seed}",
        chosen,
        current=current,
        blobs=blobs,
        cfg=cfg,
        seed=seed,
        top_up=args.top_up,
        ocr_documents=_ocr_documents(settings),
    )


def _read_labels(args) -> tuple[list[dict], list[dict]] | None:
    sample = read_rounds(args.sample)
    if not sample:
        print(f"{args.sample}: không có round-*.jsonl", file=sys.stderr)
        return None
    try:
        return sample, load_labels(args.labels, sample)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return None


def _topic_score(args, settings: KnowledgeBaseSettings) -> int:
    loaded = _read_labels(args)
    if loaded is None:
        return 2
    sample, labels = loaded
    fid, p_hash, generator = current_filter(settings)
    report = score(
        sample,
        labels,
        TopicLedger(settings.crawl_data_dir / "topic.jsonl"),
        filter_id=fid,
        prompt_hash=p_hash,
        model_revision=generator.revision,
    )
    out = settings.topic_filter_dir / fid[:12]
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.labels, out / "labels.csv")
    result = {
        **dataclasses.asdict(report),
        "sample": str(args.sample),
        "labels": str(args.labels),
        "labels_sha256": hashlib.sha256(args.labels.read_bytes()).hexdigest(),
    }
    (out / "score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"giu {report.kent_giu}, loại nhầm {report.model_loai_in_giu} "
        f"(cận trên {report.loai_upper:.2%}), khong_chac {report.khong_chac_rate:.1%}"
    )
    print("ĐẠT" if report.passed else "KHÔNG ĐẠT: " + "; ".join(report.reasons))
    return 0 if report.passed else 1


def _topic_labels(args, settings: KnowledgeBaseSettings) -> int:
    loaded = _read_labels(args)
    if loaded is None:
        return 2
    _, labels = loaded
    ledger = TopicLedger(settings.crawl_data_dir / "topic.jsonl", repair=True)
    at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    decisions = kent_decisions(labels, at=at)
    for decision in decisions:
        ledger.append(decision)
    dropped = sum(d.label == "loai" for d in decisions)
    print(f"Đã ghi {len(decisions)} nhãn của Kent: {dropped} loai, {len(decisions) - dropped} giu.")
    return 0


def _topic_pending(settings: KnowledgeBaseSettings) -> int:
    policy = load_topic_policy(settings.crawl_data_dir / "topic.jsonl", settings.topic_filter_dir)
    if policy is None:
        print("Chưa có data/web/topic.jsonl: `prune` chưa rút mục nào theo chủ đề.")
        return 0
    crawl, _ = load_crawl_config(settings.crawl_config)
    data_dir = settings.crawl_data_dir
    current = Manifest(data_dir / "manifest.jsonl", repair=False).current()
    state = CheckState(data_dir / "last_checked.json")
    chosen = topic_withdrawals(current, policy, exempt=prune_exempt(crawl), state=state)
    for entry in chosen:
        print(f"  {entry.kind:<5} {(entry.title or '')[:60]:<60} {entry.url}")
    print(f"{len(chosen)} mục sẽ bị rút và xoá blob, trong {len(current)} mục của kho.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging("knowledge_base")
    settings = KnowledgeBaseSettings()
    if args.command == "classify":
        return _classify(args, settings)
    if args.command == "topic-sample":
        return _topic_sample(args, settings)
    if args.command == "topic-score":
        return _topic_score(args, settings)
    if args.command == "topic-labels":
        return _topic_labels(args, settings)
    return _topic_pending(settings)


if __name__ == "__main__":
    raise SystemExit(main())
