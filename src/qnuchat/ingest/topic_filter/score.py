"""Đo bộ lọc chủ đề trên nhãn của Kent (spec knowledge base §5.4).

Ngưỡng xoá: trong các mục Kent gán `giu`, model gán `loai` không quá 1% và cận trên Wilson 95%
không quá 5%; mục model gán `khong_chac` không quá 15% mẫu. Mục mẫu chưa có nhãn model hoặc chỉ
có dòng lỗi làm phép đo không đạt.
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from qnuchat.ingest.topic_filter.ledger import TopicDecision, TopicLedger

MAX_LOAI_RATE = 0.01
MAX_LOAI_UPPER = 0.05
MAX_KHONG_CHAC_RATE = 0.15
CSV_COLUMNS = ["item_id", "url", "sha256", "label", "reviewer", "at"]
KENT_LABELS = ("giu", "loai")


def wilson_upper(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return min(1.0, c + h)


@dataclass(frozen=True)
class ScoreReport:
    n: int
    kent_giu: int
    model_loai_in_giu: int
    loai_rate: float
    loai_upper: float
    khong_chac: int
    khong_chac_rate: float
    errors: int
    missing: int
    passed: bool
    filter_id: str
    prompt_hash: str
    model_revision: str
    reasons: list[str]


def load_labels(path: Path, sample: list[dict]) -> list[dict]:
    """Nhãn Kent xuất từ form. Từ chối CSV thiếu mục, nhãn lạ, mục ngoài mẫu, trùng, thiếu tên."""
    by_id = {r["item_id"]: r for r in sample}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != CSV_COLUMNS:
            raise ValueError(f"{path}: cột phải là {','.join(CSV_COLUMNS)}")
        rows, seen = [], set()
        for line, row in enumerate(reader, start=2):
            item = by_id.get(row["item_id"])
            if item is None:
                raise ValueError(f"{path} dòng {line}: {row['item_id']} không thuộc mẫu")
            if row["item_id"] in seen:
                raise ValueError(f"{path} dòng {line}: {row['item_id']} bị trùng")
            if row["sha256"] != item["sha256"] or row["url"] != item["url"]:
                raise ValueError(f"{path} dòng {line}: url/sha256 không khớp mẫu")
            if row["label"] not in KENT_LABELS:
                raise ValueError(f"{path} dòng {line}: nhãn {row['label']!r} ngoài giu/loai")
            if not row["reviewer"].strip():
                raise ValueError(f"{path} dòng {line}: thiếu tên người duyệt")
            seen.add(row["item_id"])
            rows.append(row)
    missing = [i for i in by_id if i not in seen]
    if missing:
        raise ValueError(f"{path}: thiếu nhãn cho {len(missing)} mục: {', '.join(missing[:10])}")
    return rows


def kent_decisions(labels: list[dict], *, at: str) -> list[TopicDecision]:
    """Nhãn của Kent thành dòng sổ `decided_by: kent`. `prune` áp thẳng các dòng này, không qua
    ngưỡng đo: khi mẫu đã là cả kho thì không còn gì để suy từ mẫu ra."""
    return [
        TopicDecision(
            url=row["url"],
            sha256=row["sha256"],
            pass_=1,
            label=row["label"],
            group=None,
            reason=None,
            note=f"nhãn của {row['reviewer']}",
            prompt_hash="",
            filter_id="kent",
            model="",
            model_revision="",
            error_cause=None,
            decided_by="kent",
            at=at,
        )
        for row in labels
    ]


def _model_decisions(
    ledger: TopicLedger, filter_id: str
) -> tuple[dict[tuple[str, str], TopicDecision], dict[str, TopicDecision]]:
    """Quyết định model mới nhất của đúng phiên bản bộ lọc, theo (url, sha256) và theo url."""
    by_version: dict[tuple[str, str], TopicDecision] = {}
    by_url: dict[str, TopicDecision] = {}
    for d in ledger.entries():
        if d.decided_by == "model" and d.filter_id == filter_id:
            by_version[(d.url, d.sha256)] = d
            by_url[d.url] = d
    return by_version, by_url


def score(
    sample: list[dict],
    labels: list[dict],
    ledger: TopicLedger,
    *,
    filter_id: str,
    prompt_hash: str,
    model_revision: str,
) -> ScoreReport:
    kent_by_id = {row["item_id"]: row["label"] for row in labels}
    model, model_by_url = _model_decisions(ledger, filter_id)
    kent_giu = loai_in_giu = khong_chac = errors = missing = 0
    for row in sample:
        decision = model.get((row["url"], row["sha256"]))
        label = decision.label if decision else None
        if decision is None:
            # Ảnh trên trang model đã loại không được gọi model mà đi theo trang (§5.2): tính
            # là `loai` để phép đo thấy cả lỗi của luật đi theo trang.
            page = model_by_url.get(row.get("page_url") or "")
            if row["kind"] == "image" and page is not None and page.label == "loai":
                label = "loai"
            else:
                missing += 1
                continue
        if label is None:
            errors += 1
            continue
        khong_chac += label == "khong_chac"
        if kent_by_id.get(row["item_id"]) == "giu":
            kent_giu += 1
            loai_in_giu += label == "loai"
    n = len(sample)
    loai_rate = loai_in_giu / kent_giu if kent_giu else 0.0
    loai_upper = wilson_upper(loai_in_giu, kent_giu)
    khong_chac_rate = khong_chac / n if n else 0.0
    reasons = []
    if missing or errors:
        reasons.append(
            f"{missing} mục chưa có nhãn model, {errors} mục chỉ có lỗi: chạy classify cho hết mẫu"
        )
    if kent_giu == 0:
        reasons.append("không có mục nào Kent gán giu")
    if loai_rate > MAX_LOAI_RATE:
        reasons.append(f"model loại nhầm {loai_in_giu}/{kent_giu} mục giu, vượt 1%")
    if loai_upper > MAX_LOAI_UPPER:
        reasons.append(
            f"cận trên Wilson 95% {loai_upper:.2%} vượt 5% "
            f"({kent_giu} mục giu; không sai mục nào cũng cần ít nhất 73 mục giu)"
        )
    if khong_chac_rate > MAX_KHONG_CHAC_RATE:
        reasons.append(f"khong_chac {khong_chac}/{n} = {khong_chac_rate:.1%}, vượt 15%")
    return ScoreReport(
        n=n,
        kent_giu=kent_giu,
        model_loai_in_giu=loai_in_giu,
        loai_rate=loai_rate,
        loai_upper=loai_upper,
        khong_chac=khong_chac,
        khong_chac_rate=khong_chac_rate,
        errors=errors,
        missing=missing,
        passed=not reasons,
        filter_id=filter_id,
        prompt_hash=prompt_hash,
        model_revision=model_revision,
        reasons=reasons,
    )
