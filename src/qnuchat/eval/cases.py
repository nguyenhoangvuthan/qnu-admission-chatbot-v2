"""Đọc bộ câu hỏi nháp và chọn câu theo nguồn có trong kho (spec phần A §3.1).

Mỗi dòng nháp là
`{"item": GoldItem, "task_type": ..., "gold_evidence": [[đường dẫn nguồn, trang], ...], ...}`.
Câu phải từ chối luôn giữ; câu trả lời được chỉ giữ khi mọi dẫn chứng thuộc nguồn trong kho.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from qnuchat.eval.metrics.retrieval import PageKey
from qnuchat.eval.schema import GoldItem


class StaleRunError(RuntimeError):
    """Dữ liệu hiện tại không khớp dữ liệu đã sinh ra lượt chạy."""


@dataclass(frozen=True)
class EvalCase:
    item: GoldItem
    task_type: str
    gold_evidence: tuple[PageKey, ...]


def read_rows(paths: Sequence[Path]) -> list[dict]:
    """Mọi dòng không rỗng của các file, theo thứ tự file; `id` trùng thì báo lỗi."""
    rows: list[dict] = []
    seen: dict[str, Path] = {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            case_id = row["item"]["id"]
            if case_id in seen:
                raise ValueError(f"id {case_id} trùng: có trong {seen[case_id]} và {path}")
            seen[case_id] = path
            rows.append(row)
    return rows


def select_cases(
    rows: Sequence[dict], sources: Mapping[str, str]
) -> tuple[list[EvalCase], list[dict]]:
    """Chọn câu chấm được với kho `sources` (đường dẫn nguồn → `source_id`).

    Trả về câu giữ và danh sách câu loại `{"id", "reason", "gold_evidence"}`.
    """
    known = {Path(p).as_posix(): source_id for p, source_id in sources.items()}
    cases: list[EvalCase] = []
    excluded: list[dict] = []
    for row in rows:
        item = GoldItem.model_validate(row["item"])
        evidence = row.get("gold_evidence") or []
        if item.must_abstain:
            cases.append(EvalCase(item=item, task_type=row["task_type"], gold_evidence=()))
            continue
        if not evidence:
            excluded.append(
                {"id": item.id, "reason": "no_gold_evidence", "gold_evidence": evidence}
            )
            continue
        paths = [Path(source).as_posix() for source, _ in evidence]
        if any(p not in known for p in paths):
            excluded.append(
                {"id": item.id, "reason": "source_not_in_corpus", "gold_evidence": evidence}
            )
            continue
        pages = tuple((known[p], int(page)) for p, (_, page) in zip(paths, evidence, strict=True))
        cases.append(EvalCase(item=item, task_type=row["task_type"], gold_evidence=pages))
    return cases, excluded


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def gold_digests(paths: Sequence[Path]) -> list[dict]:
    """SHA-256 của từng file bộ câu hỏi, để ghi vào manifest."""
    return [{"path": Path(p).as_posix(), "sha256": _sha256(Path(p))} for p in paths]


def check_gold_unchanged(recorded: Sequence[dict]) -> None:
    """Băm lại từng file đã ghi; lệch thì `StaleRunError` kèm hash cũ và mới."""
    for entry in recorded:
        current = _sha256(Path(entry["path"]))
        if current != entry["sha256"]:
            raise StaleRunError(
                f"bộ câu hỏi {entry['path']} đã đổi: "
                f"hash cũ {entry['sha256'][:12]}, hash mới {current[:12]}"
            )
