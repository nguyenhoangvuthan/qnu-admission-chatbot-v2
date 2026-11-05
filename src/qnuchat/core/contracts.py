"""Contract của core: Query → Answer + Trace."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Thứ tự cố định của các stage trong Trace. Chỉ liệt kê stage đã có; stage mới thêm khi triển khai.
STAGE_NAMES: tuple[str, ...] = ("query_rewrite", "retrieval", "fusion", "generation")

StageStatus = Literal["disabled", "not_applicable", "executed", "error"]
AbstainSource = Literal["model"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Clarification(_Contract):
    """Hệ thống hỏi lại thay vì đoán.

    Không phải abstention, không phải lỗi.
    """

    slot: str  # tập mở: "major", "year", sau này "admission_method"…
    prompt: str = Field(min_length=1)  # "Bạn muốn hỏi học phí của ngành nào?"
    options: list[str] = Field(default_factory=list, max_length=6)  # tên chuẩn từ danh mục


class Turn(_Contract):
    """Một lượt hội thoại trước đó: chỉ phần chữ, không kèm trace."""

    question: str
    answer: str
    abstain: bool
    # Lượt cũ là câu hỏi lại → stage biết câu nào đang "treo".
    clarification: Clarification | None = None


class Query(_Contract):
    text: str = Field(min_length=1, max_length=1000)
    asked_at: date  # core KHÔNG lấy date.today() ngầm, để replay được
    # Luôn được gửi lên. Khi query_rewrite tắt, core bỏ qua nó (chat một lượt).
    history: list[Turn] = Field(default_factory=list)

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class Claim(_Contract):
    subject: str
    predicate: str
    value: str
    unit: str | None = None
    admission_year: int | None = None


class Confidence(_Contract):
    """Con số model tự khai. Hai trường sau bắt buộc để không ai đọc nó như xác suất đúng."""

    value: float = Field(ge=0.0, le=1.0)
    source: Literal["model_self_report"] = "model_self_report"
    calibrated: Literal[False] = False


class StageTrace(_Contract):
    status: StageStatus
    data: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0  # bị loại khỏi phép so replay


class Snapshot(_Contract):
    id: str
    content_hash: str
    vector_hash: str


class Trace(_Contract):
    pipeline_config_name: str
    pipeline_config_hash: str
    snapshot: Snapshot
    asked_at: date  # = Query.asked_at: trace tự đủ để replay
    stages: dict[str, StageTrace]

    @field_validator("stages")
    @classmethod
    def _complete_and_ordered(cls, stages: dict[str, StageTrace]) -> dict[str, StageTrace]:
        missing = [n for n in STAGE_NAMES if n not in stages]
        unknown = [n for n in stages if n not in STAGE_NAMES]
        if missing or unknown:
            raise ValueError(f"stages thiếu {missing}, không biết {unknown}")
        # JSONB của PostgreSQL không giữ thứ tự khoá; chuẩn hoá về thứ tự cố định.
        return {name: stages[name] for name in STAGE_NAMES}

    def comparable(self) -> dict[str, Any]:
        """Dạng dùng để so replay: bỏ duration_ms (trường vận hành)."""
        dumped = self.model_dump(mode="json")
        for stage in dumped["stages"].values():
            stage.pop("duration_ms")
        return dumped


class Answer(_Contract):
    abstain: bool
    abstain_source: AbstainSource | None = None
    abstain_reason: str | None = None  # mã có cấu trúc: MODEL_SELF, …
    abstain_detail: str | None = None  # lời giải thích nguyên văn của model
    answer: str
    claims: list[Claim]
    citation_ids: list[str]  # mức câu trả lời
    confidence: Confidence | None
    clarification: Clarification | None = None
    trace: Trace

    @model_validator(mode="after")
    def _clarify_shape(self) -> "Answer":
        if (self.confidence is None) != (self.clarification is not None):
            raise ValueError(
                "confidence là None khi và chỉ khi Answer là câu hỏi lại (clarification)"
            )
        if self.clarification is not None and (self.abstain or self.claims or self.citation_ids):
            raise ValueError("câu hỏi lại không có abstain, claims hay citation_ids")
        return self
