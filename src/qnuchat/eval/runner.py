"""Runner: chạy từng câu, ghi kết quả thô và chạy tiếp được (spec phần A §3.2).

Hai chế độ: `full` gọi cả pipeline (cần vLLM), `retrieval` chỉ gọi retriever. Mỗi câu xong là một
dòng trong `records.jsonl`, ghi ngay rồi `fsync`; dòng mới nhất của một `id` là kết quả hiện hành.
Chỉ `PipelineError` được ghi thành `execution_error`; lỗi khác làm dừng lượt, câu đã xong vẫn còn.
"""

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

from qnuchat.core.contracts import Query, Trace
from qnuchat.core.errors import PipelineError
from qnuchat.core.pipeline import QnuChatPipeline
from qnuchat.core.ports import Retriever
from qnuchat.eval.cases import EvalCase, StaleRunError

Mode = Literal["full", "retrieval"]

# Khoá xác định một lượt chạy: lệch một khoá thì không được chạy tiếp vào cùng thư mục.
IDENTITY_KEYS = ("mode", "asked_at", "pipeline_config_hash", "snapshot", "gold_files")

MANIFEST = "manifest.json"
RECORDS = "records.jsonl"


def open_run(run_dir: Path, manifest: dict) -> dict:
    """Mở lượt chạy: tạo mới thì ghi `manifest`; đã có thì kiểm identity và trả manifest cũ."""
    path = Path(run_dir) / MANIFEST
    fresh = json.loads(json.dumps(manifest, ensure_ascii=False))
    if path.exists():
        recorded = json.loads(path.read_text(encoding="utf-8"))
        for key in IDENTITY_KEYS:
            if recorded.get(key) != fresh.get(key):
                raise StaleRunError(
                    f"lượt {run_dir} không chạy tiếp được: {key} đã đổi, "
                    f"cũ {recorded.get(key)!r}, mới {fresh.get(key)!r}"
                )
        return recorded
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(fresh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return fresh


def read_records(path: Path) -> dict[str, dict]:
    """Dòng mới nhất của mỗi `id`.

    Dòng cuối thiếu `\\n` mà không parse được là dòng bị cắt dở (mất điện, kill -9): bỏ qua.
    Dòng hỏng khác thì `ValueError` nêu số dòng (đếm từ 1).
    """
    path = Path(path)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    records: dict[str, dict] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            if number == len(lines):  # chỉ dòng không có "\n" phía sau mới rơi vào đây
                break
            raise ValueError(f"{path}: dòng {number} không phải JSON hợp lệ ({exc})") from exc
        records[record["id"]] = record
    return records


def pending(
    cases: Sequence[EvalCase], records: Mapping[str, dict], *, retry_errors: bool
) -> list[EvalCase]:
    """Câu còn phải chạy: chưa có dòng, hoặc dòng là `execution_error` khi `retry_errors`."""
    todo: list[EvalCase] = []
    for case in cases:
        record = records.get(case.item.id)
        if record is None or (retry_errors and record["status"] == "execution_error"):
            todo.append(case)
    return todo


def answer_full(pipeline: QnuChatPipeline, case: EvalCase, asked_at: date) -> dict:
    """Chạy cả pipeline cho một câu; `passages` lấy từ stage `fusion` (thứ model thực sự thấy)."""
    query = Query(text=case.item.question, asked_at=asked_at)
    try:
        answer = pipeline.answer(query)
    except PipelineError as exc:
        return _record(case, "execution_error", None, _fusion_passages(exc.partial_trace), exc)
    return _record(case, "ok", answer.model_dump(mode="json"), _fusion_passages(answer.trace))


def answer_retrieval(retriever: Retriever, case: EvalCase) -> dict:
    """Chỉ gọi retriever; `passages` là kết quả gộp, không có `answer`."""
    try:
        result = retriever.retrieve(case.item.question)
    except PipelineError as exc:
        return _record(case, "execution_error", None, [], exc)
    passages = [
        {
            "chunk_id": hit.passage.chunk_id,
            "source_id": hit.passage.source_id,
            "page": hit.passage.page,
            "rank": rank,
        }
        for rank, hit in enumerate(result.fused, start=1)
    ]
    return _record(case, "ok", None, passages)


def run_cases(
    cases: Sequence[EvalCase],
    run_dir: Path,
    answer: Callable[[EvalCase], dict],
    on_record: Callable[[dict], None] | None = None,
) -> None:
    """Chạy lần lượt từng câu, ghi mỗi dòng ngay khi xong (`flush` + `fsync`)."""
    if not cases:
        return
    path = Path(run_dir) / RECORDS
    _cut_partial_tail(path)
    with path.open("a", encoding="utf-8") as handle:
        for case in cases:
            started = time.perf_counter()
            record = answer(case)
            record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            if on_record is not None:
                on_record(record)


def _record(
    case: EvalCase,
    status: str,
    answer: dict | None,
    passages: list[dict],
    error: PipelineError | None = None,
) -> dict[str, Any]:
    return {
        "id": case.item.id,
        "status": status,
        "answer": answer,
        "passages": passages,
        "error": (
            {"stage": error.stage, "cause": error.cause, "message": error.message}
            if error is not None
            else None
        ),
    }


def _fusion_passages(trace: Trace | None) -> list[dict]:
    """Passage của stage `fusion`, `rank` đếm từ 1.

    Stage chưa chạy (lỗi ở stage trước, hoặc câu hỏi lại) thì rỗng."""
    if trace is None:
        return []
    fusion = trace.stages["fusion"]
    if fusion.status != "executed":
        return []
    return [
        {"chunk_id": p["chunk_id"], "source_id": p["source_id"], "page": p["page"], "rank": rank}
        for rank, p in enumerate(fusion.data.get("passages", []), start=1)
    ]


def _cut_partial_tail(path: Path) -> None:
    """File không kết thúc bằng `\\n` thì cắt về ngay sau `\\n` cuối cùng (bỏ dòng ghi dở)."""
    if not path.exists():
        return
    with path.open("rb+") as handle:
        data = handle.read()
        if not data or data.endswith(b"\n"):
            return
        handle.truncate(data.rfind(b"\n") + 1)
        handle.flush()
        os.fsync(handle.fileno())
