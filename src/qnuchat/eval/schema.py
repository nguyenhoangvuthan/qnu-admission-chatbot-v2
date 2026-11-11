"""Kiểu dữ liệu của gold và câu trả lời đem chấm. Core không được biết các kiểu này."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from qnuchat.core.contracts import Claim

Origin = Literal["curated", "challenge", "noisy"]
Risk = Literal["high", "normal"]


class ExpectedSlot(BaseModel):
    subject: str
    predicate: str
    value: str
    unit: str | None = None
    admission_year: int | None = None
    # T1 khớp subject/predicate CHÍNH XÁC sau chuẩn hoá (eval/metrics/slots.py).
    # Hai danh sách này là chỗ khai báo biến thể diễn đạt hợp lệ của cùng một đối
    # tượng/loại thông tin ("điểm trúng tuyển" ~ "điểm chuẩn"), song song với
    # `condition_synonyms`. Không khai ở đây thì không được tính là khớp.
    subject_synonyms: list[str] = Field(default_factory=list)
    predicate_synonyms: list[str] = Field(default_factory=list)
    value_synonyms: list[str] = Field(default_factory=list)
    unit_synonyms: list[str] = Field(default_factory=list)


class GoldItem(BaseModel):
    id: str
    question: str
    origin: Origin
    risk: Risk
    admission_year: int
    must_abstain: bool
    gold_page_ids: list[int]
    expected_slots: list[ExpectedSlot]
    required_conditions: list[str]
    forbidden_claims: list[str]
    source_family: str
    reviewer: str
    requires_aggregation: bool = False
    condition_synonyms: dict[str, list[str]] = Field(default_factory=dict)


@dataclass(frozen=True)
class ScoredAnswer:
    """Phần của câu trả lời mà metric đọc; runner dựng từ kết quả của pipeline."""

    abstain: bool
    claims: list[Claim]
    confidence: float
    text: str = ""  # câu trả lời chữ; `correct` chấm trên nó (spec phần A §4.1)


def load_gold(path: str | Path) -> list[GoldItem]:
    """Đọc gold từ JSONL — mỗi dòng không rỗng là một `GoldItem`."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [GoldItem.model_validate(json.loads(line)) for line in lines if line.strip()]
