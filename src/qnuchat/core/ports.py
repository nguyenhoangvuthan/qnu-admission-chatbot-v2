"""Cổng (Protocol) mà pipeline dùng; adapter cắm vào. Core không biết vLLM hay model nào."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from qnuchat.core.contracts import Claim, StageTrace
from qnuchat.documents import Passage


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float
    rank: int


@dataclass(frozen=True)
class RetrievalResult:
    branches: dict[str, list[Hit]]  # ứng viên của từng nhánh trước khi gộp
    fused: list[Hit]  # kết quả sau khi gộp, đã cắt top_k
    meta: dict[str, Any] = field(default_factory=dict)  # depth, top_k, rrf_k, embedding_device


@dataclass(frozen=True)
class GeneratorOutput:
    answer: str
    abstain: bool
    abstain_reason: str | None
    claims: list[Claim]
    citation_ids: list[str]
    confidence: float
    request_sha256: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None
    raw_content: str | None
    # Đúng kwargs đã gửi LLM (model, messages, max_tokens, seed, response_format, extra_body):
    # ghi vào trace để xem nguyên văn prompt và để replay bắt được prompt bị đổi ngầm.
    request: dict[str, Any]


@dataclass(frozen=True)
class NoticeOutput:
    """Câu báo chưa có thông tin, viết khi model trả câu rỗng mà không từ chối."""

    text: str
    request: dict[str, Any]  # đúng kwargs đã gửi LLM, như GeneratorOutput.request
    request_sha256: str
    raw_content: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None


# Được gọi sau mỗi stage (kể cả stage tắt, lỗi, bị bỏ qua) với tên stage và một BẢN SAO trace của
# stage đó. Chạy trong thread của pipeline; ném lỗi thì pipeline ghi log rồi đi tiếp.
StageObserver = Callable[[str, StageTrace], None]


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...


class Retriever(Protocol):
    def retrieve(self, query: str) -> RetrievalResult: ...


class Generator(Protocol):
    def generate(self, question: str, passages: Sequence[Passage]) -> GeneratorOutput: ...


class NoticeWriter(Protocol):
    def write(self, question: str) -> NoticeOutput: ...
