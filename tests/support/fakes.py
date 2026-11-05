"""Fake dùng chung cho test: không GPU, không mạng."""

import dataclasses
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from qnuchat.core.config import load_pipeline_config
from qnuchat.core.contracts import Claim, Query, Snapshot
from qnuchat.core.pipeline import QnuChatPipeline, assemble_pipeline
from qnuchat.core.ports import GeneratorOutput, Hit, NoticeOutput, RetrievalResult
from qnuchat.documents import Passage

ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CONFIG = ROOT / "configs/pipeline/b3-qwen3-4b-awq.yaml"
CHAT_CONFIG = ROOT / "configs/pipeline/b3-chat.yaml"
TODAY = date(2026, 9, 29)


def make_passage(
    chunk_id: str = "p004",
    page: int = 4,
    text: str | None = None,
    source_id: str = "cam-nang-2025",
) -> Passage:
    return Passage(
        chunk_id=chunk_id,
        source_id=source_id,
        page=page,
        text=text or f"Nội dung {chunk_id}: học phí ngành CNTT là 15 triệu đồng.",
        source_year=2025,
    )


def make_retrieval(
    chunk_ids: Sequence[str] = ("p004", "p005"),
    device: str = "cpu",
    texts: dict[str, str] | None = None,
) -> RetrievalResult:
    passages = [
        make_passage(cid, page=int(cid[1:4]), text=(texts or {}).get(cid)) for cid in chunk_ids
    ]
    fused = [Hit(passage=p, score=1.0 / (i + 1), rank=i + 1) for i, p in enumerate(passages)]
    return RetrievalResult(
        branches={"bm25": fused, "dense": list(reversed(fused))},
        fused=fused,
        meta={"depth": 20, "top_k": 5, "rrf_k": 60, "embedding_device": device},
    )


def make_output(**overrides) -> GeneratorOutput:
    fields = {
        "answer": "Học phí là 15 triệu đồng.",
        "abstain": False,
        "abstain_reason": None,
        "claims": [
            Claim(
                subject="ngành CNTT",
                predicate="học phí",
                value="15",
                unit="triệu đồng",
                admission_year=2025,
            )
        ],
        "citation_ids": ["p004"],
        "confidence": 0.8,
        "request_sha256": "r" * 64,
        "model": "Qwen/Qwen3-4B-AWQ",
        "prompt_tokens": 1200,
        "completion_tokens": 80,
        "finish_reason": "stop",
        "raw_content": "{}",
        "request": {
            "model": "Qwen/Qwen3-4B-AWQ",
            "messages": [
                {"role": "system", "content": "Bạn là trợ lý tuyển sinh."},
                {"role": "user", "content": "Học phí ngành CNTT?"},
            ],
            "max_tokens": 1024,
            "seed": 42,
        },
    }
    fields.update(overrides)
    return GeneratorOutput(**fields)


class FakeRetriever:
    def __init__(self, result: RetrievalResult | None = None, error: Exception | None = None):
        self.result = result or make_retrieval()
        self.error = error
        self.calls: list[str] = []

    def retrieve(self, query: str) -> RetrievalResult:
        self.calls.append(query)
        if self.error:
            raise self.error
        return self.result


class FakeGenerator:
    def __init__(self, output: GeneratorOutput | None = None, error: Exception | None = None):
        self.output = output or make_output()
        self.error = error
        self.calls: list[tuple[str, list[Passage]]] = []

    def generate(self, question: str, passages: Sequence[Passage]) -> GeneratorOutput:
        self.calls.append((question, list(passages)))
        if self.error:
            raise self.error
        # Request phản ánh đúng câu đã nhận: test kiểm được câu nào thực sự vào prompt.
        request = {
            **self.output.request,
            "messages": [
                self.output.request["messages"][0],
                {"role": "user", "content": question},
            ],
        }
        return dataclasses.replace(self.output, request=request)


class FakeChatApi:
    """Client OpenAI giả: trả `content` định sẵn và ghi lại mọi request đã gửi."""

    def __init__(self, content: str = "{}", finish="stop", usage=(1200, 80), error=None):
        self.content, self.finish, self.usage, self.error = content, finish, usage, error
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=self.finish, message=SimpleNamespace(content=self.content)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=self.usage[0], completion_tokens=self.usage[1]),
        )


class SequenceApi:
    """Trả lần lượt phản hồi (hoặc lỗi) của các FakeChatApi con; ghi mọi request đã gửi."""

    def __init__(self, apis: list[FakeChatApi]):
        self._apis = list(apis)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        api = self._apis[min(len(self.requests), len(self._apis)) - 1]
        return api.chat.completions.create(**kwargs)


NOTICE_TEXT = (
    "Tài liệu hiện có chưa có thông tin về điều bạn hỏi. "
    "Bạn vui lòng liên hệ Phòng Tuyển sinh để được giải đáp."
)


class FakeNoticeWriter:
    def __init__(self, text: str = NOTICE_TEXT, error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls: list[str] = []

    def write(self, question: str) -> NoticeOutput:
        self.calls.append(question)
        if self.error:
            raise self.error
        return NoticeOutput(
            text=self.text,
            request={"model": "Qwen/Qwen3-4B-AWQ", "max_tokens": 128, "question": question},
            request_sha256="n" * 64,
            raw_content=self.text,
            prompt_tokens=150,
            completion_tokens=40,
            finish_reason="stop",
        )


def make_query(text: str = "Học phí ngành CNTT?", **overrides) -> Query:
    return Query(text=text, asked_at=overrides.pop("asked_at", TODAY), **overrides)


def make_snapshot() -> Snapshot:
    return Snapshot(
        id="snap0123abcd",
        content_hash="c" * 64,
        vector_hash="v" * 64,
    )


def make_pipeline(
    retriever=None, generator=None, config=SHIPPED_CONFIG, notice_writer=None
) -> QnuChatPipeline:
    return assemble_pipeline(
        load_pipeline_config(config),
        snapshot=make_snapshot(),
        retriever=retriever or FakeRetriever(),
        generator=generator or FakeGenerator(),
        runtime_info={"vllm_version": "0.30.0-test"},
        # Cấu hình chat bật empty_answer_notice; cấu hình tắt thì pipeline bỏ qua writer.
        notice_writer=notice_writer or FakeNoticeWriter(),
    )
