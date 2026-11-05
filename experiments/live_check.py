"""Thực nghiệm live với vLLM: generator v2 trên server thật, và ID dài có hại cho trích dẫn không.

Mỗi câu chạy hai arm trên cùng kết quả truy hồi; chỉ khác dạng chunk_id trong prompt:
`dai` = `cam-nang-2025:p074` (v2), `ngan` = `p074` (pilot). Gold còn là bản nháp nên số ở đây là
số phát triển, không dùng để báo cáo.

Chạy qua `scripts/thuc-nghiem-live.sh`, script đó lo khởi động và dừng vLLM.
"""

import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from qnuchat.adapters.generation.vllm_checks import check_served_model, fetch_vllm_version
from qnuchat.adapters.runtime import build_runtime
from qnuchat.core.config import load_pipeline_config
from qnuchat.core.contracts import Query
from qnuchat.core.errors import PipelineError
from qnuchat.core.pipeline import QnuChatPipeline, assemble_pipeline
from qnuchat.core.ports import Hit, RetrievalResult, Retriever

ROOT = Path(__file__).resolve().parents[1]
CORPUS_FILE = "Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf"
GOLD_FILES = ("benchmarks/v2/core.draft.jsonl", "benchmarks/v2/comparison.draft.jsonl")
ARMS = ("dai", "ngan")
ABSTAIN_SHARE = 0.2


def short_id(chunk_id: str) -> str:
    return chunk_id.rsplit(":", 1)[-1]


class ShortIdRetriever:
    """Bọc retriever thật, đổi chunk_id về dạng pilot; nội dung và thứ hạng giữ nguyên."""

    def __init__(self, inner: Retriever):
        self._inner = inner

    @staticmethod
    def _short(hit: Hit) -> Hit:
        return replace(hit, passage=replace(hit.passage, chunk_id=short_id(hit.passage.chunk_id)))

    def retrieve(self, query: str) -> RetrievalResult:
        result = self._inner.retrieve(query)
        return replace(
            result,
            fused=[self._short(h) for h in result.fused],
            branches={k: [self._short(h) for h in v] for k, v in result.branches.items()},
        )


def _gold_pages(record: dict) -> list[int]:
    return sorted({page for _, page in record.get("gold_evidence") or []})


def _in_corpus(record: dict) -> bool:
    evidence = record.get("gold_evidence") or []
    return bool(evidence) and all(path.endswith(CORPUS_FILE) for path, _ in evidence)


def _stable_order(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: hashlib.sha256(r["item"]["id"].encode()).hexdigest())


def select_items(records: list[dict], limit: int) -> list[dict]:
    """Câu kho hiện tại trả lời được, cộng một phần câu phải từ chối; thứ tự tất định theo id."""
    abstain = _stable_order([r for r in records if r["item"]["must_abstain"]])
    answerable = _stable_order(
        [r for r in records if not r["item"]["must_abstain"] and _in_corpus(r)]
    )
    n_abstain = min(len(abstain), round(limit * ABSTAIN_SHARE))
    return [*answerable[: limit - n_abstain], *abstain[:n_abstain]]


def load_records() -> list[dict]:
    records: list[dict] = []
    for name in GOLD_FILES:
        lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
        records += [json.loads(line) for line in lines if line.strip()]
    return records


def run_question(pipeline: QnuChatPipeline, record: dict, arm: str) -> dict[str, Any]:
    item = record["item"]
    row: dict[str, Any] = {
        "arm": arm,
        "id": item["id"],
        "question": item["question"],
        "must_abstain": item["must_abstain"],
        "gold_pages": _gold_pages(record),
        "status": "answered",
        "cause": None,
        "answer": None,
        "citation_ids": [],
        "unknown_citations": [],
        "cited_pages": [],
        "claims": [],
        "raw_response": None,
        "prompt_tokens": None,
        "completion_tokens": None,
    }
    started = time.perf_counter()
    try:
        answer = pipeline.answer(Query(text=item["question"], asked_at=date.today()))
    except PipelineError as exc:
        # Execution error là một loại kết quả riêng, không bao giờ tính thành từ chối.
        row.update(status="error", cause=exc.cause, answer=exc.message)
    else:
        stages = answer.trace.stages
        generation = stages["generation"].data
        pages = {p["chunk_id"]: p["page"] for p in stages["fusion"].data["passages"]}
        row.update(
            status="abstained" if answer.abstain else "answered",
            answer=answer.answer,
            citation_ids=answer.citation_ids,
            unknown_citations=generation["unknown_citations"],
            cited_pages=sorted({pages[c] for c in answer.citation_ids if c in pages}),
            claims=[claim.model_dump() for claim in answer.claims],
            raw_response=generation["raw_response"],
            prompt_tokens=generation["prompt_tokens"],
            completion_tokens=generation["completion_tokens"],
        )
    row["seconds"] = round(time.perf_counter() - started, 2)
    return row


def is_blank(answer: str | None) -> bool:
    """Không có chữ hay số nào, như `""` hoặc `":[{"`: người đọc không nhận được gì."""
    return not any(char.isalnum() for char in answer or "")


def summarize(rows: list[dict]) -> dict[str, Any]:
    answered = [r for r in rows if r["status"] == "answered"]
    real = [r for r in answered if not is_blank(r["answer"])]
    return {
        "n": len(rows),
        "answered": len(answered),
        "answered_with_content": len(real),
        "answered_blank": len(answered) - len(real),
        "abstained": sum(r["status"] == "abstained" for r in rows),
        "errors": dict(Counter(r["cause"] for r in rows if r["status"] == "error")),
        "answered_with_citation": sum(bool(r["citation_ids"]) for r in real),
        "answered_with_unknown_citation": sum(bool(r["unknown_citations"]) for r in real),
        "cited_gold_page": sum(bool(set(r["cited_pages"]) & set(r["gold_pages"])) for r in real),
        "correct_abstention": sum(r["status"] == "abstained" and r["must_abstain"] for r in rows),
        "must_abstain": sum(r["must_abstain"] for r in rows),
        "mean_seconds": round(mean(r["seconds"] for r in rows), 1) if rows else 0.0,
    }


def _outcome(row: dict) -> tuple:
    blank = row["status"] == "answered" and is_blank(row["answer"])
    return (row["status"], blank, bool(row["unknown_citations"]), tuple(row["cited_pages"]))


def write_report(rows: list[dict], path: Path, info: dict[str, Any]) -> str:
    summaries = {arm: summarize([r for r in rows if r["arm"] == arm]) for arm in ARMS}
    labels = [
        ("Số lượt", "n"),
        ("Trả lời có nội dung", "answered_with_content"),
        ("**Trả lời rỗng hoặc rác**", "answered_blank"),
        ("Từ chối", "abstained"),
        ("Từ chối đúng / phải từ chối", None),
        ("Execution error", None),
        ("Có nội dung và có trích dẫn", "answered_with_citation"),
        ("Có nội dung nhưng ID không tồn tại", "answered_with_unknown_citation"),
        ("Có nội dung và trích đúng trang gold", "cited_gold_page"),
        ("Thời gian trung bình (giây)", "mean_seconds"),
    ]

    def cell(arm: str, label: str, key: str | None) -> str:
        s = summaries[arm]
        if key is not None:
            return str(s[key])
        if label.startswith("Từ chối đúng"):
            return f"{s['correct_abstention']} / {s['must_abstain']}"
        return ", ".join(f"{k}: {v}" for k, v in s["errors"].items()) or "0"

    by_arm = {arm: {r["id"]: r for r in rows if r["arm"] == arm} for arm in ARMS}
    shared = [i for i in by_arm["dai"] if i in by_arm["ngan"]]
    changed = [i for i in shared if _outcome(by_arm["dai"][i]) != _outcome(by_arm["ngan"][i])]
    lines = [
        "# Thực nghiệm live: ID dài so với ID ngắn",
        "",
        "Gold còn là bản nháp: đây là số phát triển, không dùng để báo cáo.",
        "",
        *[f"- {key}: {value}" for key, value in info.items()],
        "",
        "| Chỉ số | ID dài (v2) | ID ngắn (pilot) |",
        "|---|---:|---:|",
        *[f"| {t} | {cell('dai', t, k)} | {cell('ngan', t, k)} |" for t, k in labels],
        "",
        f"Khác nhau giữa hai arm: {len(changed)}/{len(shared)} câu.",
    ]
    for item_id in changed:
        long_row, short_row = by_arm["dai"][item_id], by_arm["ngan"][item_id]
        lines.append(
            f"- `{item_id}` {long_row['question']} — dài: {_outcome(long_row)}; "
            f"ngắn: {_outcome(short_row)}"
        )
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--config", default="configs/pipeline/b3-qwen3-4b-awq.yaml")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--embedding-device", default="cpu")
    parser.add_argument("--cache-dir", default="artifacts/cache/embeddings")
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    loaded = load_pipeline_config(args.config)
    print("Đang dựng index (lần đầu BGE-M3 trên CPU mất vài phút)…", flush=True)
    runtime = build_runtime(
        loaded,
        base_url=args.base_url,
        api_key="EMPTY",
        timeout_s=args.timeout_s,
        embedding_device=args.embedding_device,
        cache_dir=args.cache_dir,
    )
    check_served_model(
        [m.id for m in runtime.api.models.list().data], loaded.config.generator.model
    )
    version = fetch_vllm_version(args.base_url, "EMPTY")

    def pipeline(retriever: Retriever) -> QnuChatPipeline:
        return assemble_pipeline(
            loaded,
            snapshot=runtime.snapshot,
            retriever=retriever,
            generator=runtime.generator,
            runtime_info={"vllm_version": version},
            notice_writer=runtime.notice_writer,
        )

    pipelines = {
        "dai": pipeline(runtime.retriever),
        "ngan": pipeline(ShortIdRetriever(runtime.retriever)),
    }
    items = select_items(load_records(), args.limit)
    info = {
        "vLLM": version,
        "Cấu hình": f"{loaded.name} ({loaded.sha256[:12]})",
        "Snapshot": runtime.snapshot.id,
        "Embedding": runtime.embedding["device"],
    }
    rows: list[dict] = []
    with (args.out / "rows.jsonl").open("w", encoding="utf-8") as handle:
        try:
            for index, record in enumerate(items, start=1):
                for arm in ARMS:  # xen kẽ để dừng giữa chừng vẫn còn cặp so sánh được
                    row = run_question(pipelines[arm], record, arm)
                    rows.append(row)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    print(
                        f"[{index}/{len(items)}] {arm:4} {row['status']:9} {row['seconds']:6.1f}s "
                        f"{row['id']}",
                        flush=True,
                    )
        except KeyboardInterrupt:
            print("Dừng theo yêu cầu; báo cáo phần đã chạy.", flush=True)
    print("\n" + write_report(rows, args.out / "report.md", info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
