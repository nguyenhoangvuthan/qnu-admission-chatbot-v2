"""Hình dạng JSON mà model phải trả, ràng buộc bằng guided decoding."""

from pydantic import BaseModel, Field

# Thứ tự khoá là thứ tự model viết. `abstain_reason` phải đứng sau `answer`: đặt trước thì model
# viết `"abstain_reason":""` rồi viết luôn `"answer":""`, dù `claims` có đúng số liệu.
ANSWER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "abstain": {"type": "boolean"},
        "answer": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": ["string", "null"]},
                    "admission_year": {"type": ["integer", "null"]},
                },
                "required": ["subject", "predicate", "value"],
                "additionalProperties": False,
            },
        },
        "citation_ids": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "abstain_reason": {"type": ["string", "null"]},
    },
    "required": ["abstain", "answer", "claims", "citation_ids", "confidence"],
    "additionalProperties": False,
}

# Guided decoding qua `response_format` chuẩn OpenAI, KHÔNG qua extra_body.
# vLLM đã bỏ họ tham số `guided_*` (guided_json/guided_regex/guided_choice/
# guided_grammar) và thay bằng `structured_outputs`; một client gửi `guided_json`
# tới vLLM đời mới sẽ mất ràng buộc schema — và mất nó một cách IM LẶNG, vì
# extra_body chỉ là dict tự do. `response_format` là đường đi chuẩn của giao thức
# OpenAI, vLLM hỗ trợ ở cả hai đời tham số, nên nó không khoá vào một phiên bản
# vLLM cụ thể. Nếu buộc phải quay lại tham số riêng của vLLM thì dùng
# `extra_body={"structured_outputs": {"json": ANSWER_JSON_SCHEMA}}` — KHÔNG dùng
# lại guided_json. Không đặt "strict": True: schema của claims cố ý để
# unit/admission_year không bắt buộc, còn strict mode đòi mọi field phải required.
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "qnu_answer", "schema": ANSWER_JSON_SCHEMA},
}


class ModelClaim(BaseModel):
    subject: str
    predicate: str
    value: str
    unit: str | None = None
    admission_year: int | None = None


class ModelAnswer(BaseModel):
    """Một phản hồi của model đã parse; khác `core.contracts.Answer` là chưa có trace."""

    abstain: bool
    answer: str
    claims: list[ModelClaim]
    citation_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    abstain_reason: str | None = None
