"""Lần lọc 1 trên kho web (spec knowledge base §5.3 bước 2).

Sổ quyết định là checkpoint: chạy lại thì bỏ mục đã có quyết định không lỗi cho đúng phiên bản nội
dung và phiên bản bộ lọc, gọi lại mục chỉ có dòng lỗi.
"""

from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.manifest import ManifestEntry
from qnuchat.ingest.topic_filter.classifier import TopicExecutionError
from qnuchat.ingest.topic_filter.inputs import BlobMissing, build_input
from qnuchat.ingest.topic_filter.ledger import TopicDecision, TopicLedger

PASS = 1
PROGRESS_EVERY = 100


def _summary(counts: Counter[str]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))


def _page_is_loai(entry: ManifestEntry, current, ledger: TopicLedger) -> bool:
    parent = current.get(entry.page_url) if entry.page_url else None
    if parent is None or parent.sha256 is None:
        return False
    decision = ledger.current(parent.url, parent.sha256)
    return decision is not None and decision.label == "loai"


def run_classify(
    *,
    current: dict[str, ManifestEntry],
    candidates: list[ManifestEntry],
    classifier,
    ledger: TopicLedger,
    blobs: BlobStore,
    prompt_hash: str,
    filter_id: str,
    model: str,
    model_revision: str,
    max_chars: int,
    now: Callable[[], datetime],
    limit: int | None = None,
    ocr_documents: Path | None = None,
    out: Callable[[str], None] = print,
    track: Callable[[list[ManifestEntry]], Iterable[ManifestEntry]] = iter,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    calls = 0

    def record(entry: ManifestEntry, *, label=None, group=None, reason=None, note="", error=None):
        ledger.append(
            TopicDecision(
                url=entry.url,
                sha256=entry.sha256,
                pass_=PASS,
                label=label,
                group=group,
                reason=reason,
                note=note,
                prompt_hash=prompt_hash,
                filter_id=filter_id,
                model=model,
                model_revision=model_revision,
                error_cause=error,
                decided_by="model",
                at=now().isoformat(timespec="seconds"),
            )
        )
        counts["error" if error else label] += 1

    for entry in track(candidates):
        if ledger.done(entry.url, entry.sha256, filter_id=filter_id):
            counts["skipped_done"] += 1
            continue
        # Dòng mới nhất là quyết định hiện hành, nên model không được ghi đè nhãn của Kent.
        decided = ledger.current(entry.url, entry.sha256)
        if decided is not None and decided.decided_by == "kent":
            counts["skipped_kent"] += 1
            continue
        # Ảnh trên trang đã bị loại đi theo trang chứa, không gọi model (§5.2); `prune` rút theo.
        if entry.kind == "image" and _page_is_loai(entry, current, ledger):
            counts["follows_page"] += 1
            continue
        if limit is not None and calls >= limit:
            break
        try:
            inp = build_input(
                entry,
                current=current,
                blobs=blobs,
                max_chars=max_chars,
                ocr_documents=ocr_documents,
            )
        except BlobMissing:
            record(entry, error="blob_missing")
            continue
        calls += 1
        try:
            verdict = classifier.classify(inp)
        except TopicExecutionError as exc:
            record(entry, error=exc.cause)
        else:
            record(
                entry,
                label=verdict.label,
                group=verdict.group,
                reason=verdict.reason,
                note=verdict.note,
            )
        if calls % PROGRESS_EVERY == 0:
            out(f"{calls} lần gọi model — {_summary(counts)}")
    out(f"Xong: {_summary(counts)}")
    return counts
