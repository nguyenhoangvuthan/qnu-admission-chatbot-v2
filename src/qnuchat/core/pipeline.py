"""QnuChatPipeline: chạy chuỗi stage cố định, ghi Trace, không biến lỗi hạ tầng thành Answer."""

import logging
import time
from collections.abc import Sequence
from typing import Any

from qnuchat.core.config import LoadedConfig
from qnuchat.core.contracts import (
    STAGE_NAMES,
    Answer,
    Confidence,
    Query,
    Snapshot,
    StageTrace,
    Trace,
)
from qnuchat.core.errors import PipelineError
from qnuchat.core.ports import Generator, NoticeWriter, Retriever, StageObserver
from qnuchat.core.stages.base import RunState, Stage
from qnuchat.core.stages.generation import GenerationStage
from qnuchat.core.stages.query_rewrite import QueryRewriteStage
from qnuchat.core.stages.retrieval import FusionStage, RetrievalStage

logger = logging.getLogger(__name__)


class QnuChatPipeline:
    def __init__(
        self,
        *,
        config_name: str,
        config_hash: str,
        snapshot: Snapshot,
        stages: Sequence[Stage],
    ):
        names = tuple(stage.name for stage in stages)
        if names != STAGE_NAMES:
            raise ValueError(f"Stage phải đúng thứ tự {STAGE_NAMES}, nhận {names}")
        self._config_name = config_name
        self._config_hash = config_hash
        self._snapshot = snapshot
        self._stages = list(stages)

    def answer(self, query: Query, on_stage: StageObserver | None = None) -> Answer:
        state = RunState(query=query, search_text=query.text)
        traces: dict[str, StageTrace] = {}
        failure: PipelineError | None = None
        for stage in self._stages:
            if not stage.enabled:
                data: dict[str, Any] = {"note": stage.note} if stage.note else {}
                traces[stage.name] = StageTrace(status="disabled", data=data)
            elif failure is not None:
                traces[stage.name] = StageTrace(
                    status="not_applicable", data={"reason": "skipped_after_error"}
                )
            elif state.clarification is not None:
                # Câu hỏi lại: không retrieval, không gọi LLM.
                traces[stage.name] = StageTrace(
                    status="not_applicable", data={"reason": "clarification_needed"}
                )
            else:
                started = time.perf_counter()
                try:
                    data = stage.run(state)
                    status = "executed"
                except PipelineError as exc:
                    failure, status = exc, "error"
                    data = {"cause": exc.cause, "message": exc.message, **exc.details}
                except Exception as exc:  # noqa: BLE001 — lỗi ngoài dự kiến vẫn là execution error
                    failure = PipelineError(stage.name, "error", f"{type(exc).__name__}: {exc}")
                    failure.__cause__ = exc
                    status = "error"
                    data = {"cause": failure.cause, "message": failure.message}
                traces[stage.name] = StageTrace(
                    status=status, data=data, duration_ms=(time.perf_counter() - started) * 1000
                )
            _notify(on_stage, stage.name, traces[stage.name])
        trace = Trace(
            pipeline_config_name=self._config_name,
            pipeline_config_hash=self._config_hash,
            snapshot=self._snapshot,
            asked_at=query.asked_at,
            stages=traces,
        )
        if failure is not None:
            failure.partial_trace = trace
            raise failure
        return self._to_answer(state, trace)

    @staticmethod
    def _to_answer(state: RunState, trace: Trace) -> Answer:
        if state.clarification is not None:
            return Answer(
                abstain=False,
                answer=state.clarification.prompt,
                claims=[],
                citation_ids=[],
                confidence=None,
                clarification=state.clarification,
                trace=trace,
            )
        generated = state.generated
        if generated is None:
            raise RuntimeError("GenerationStage chạy xong mà không sinh kết quả")
        if state.notice is not None:
            # Câu rỗng không được đếm là đã trả lời; bản gốc nằm ở raw_response.
            return Answer(
                abstain=True,
                abstain_source="model",
                abstain_reason="EMPTY_ANSWER",
                abstain_detail=state.notice,
                answer=generated.answer,
                claims=[],
                citation_ids=[],
                confidence=Confidence(value=generated.confidence),
                trace=trace,
            )
        abstain = generated.abstain
        return Answer(
            abstain=abstain,
            abstain_source="model" if abstain else None,
            abstain_reason="MODEL_SELF" if abstain else None,
            abstain_detail=generated.abstain_reason if abstain else None,
            answer=generated.answer,
            claims=generated.claims,
            citation_ids=generated.citation_ids,
            confidence=Confidence(value=generated.confidence),
            trace=trace,
        )


def _notify(on_stage: StageObserver | None, name: str, stage_trace: StageTrace) -> None:
    """Báo một stage vừa xong. Người theo dõi chỉ nhận bản sao và không làm đổi câu trả lời."""
    if on_stage is None:
        return
    try:
        on_stage(name, stage_trace.model_copy(deep=True))
    except Exception:  # người theo dõi (UI) hỏng không được làm hỏng câu trả lời
        logger.exception("stage_observer_failed %s", name)


def assemble_pipeline(
    loaded: LoadedConfig,
    *,
    snapshot: Snapshot,
    retriever: Retriever,
    generator: Generator,
    runtime_info: dict[str, Any] | None = None,
    notice_writer: NoticeWriter | None = None,
) -> QnuChatPipeline:
    """Lắp pipeline theo cấu hình; `query_rewrite` là stage duy nhất có thể tắt.

    `notice_writer` chỉ được dùng khi cờ generation.empty_answer_notice bật."""
    cfg = loaded.config
    if cfg.generation.empty_answer_notice and notice_writer is None:
        raise ValueError("generation.empty_answer_notice bật cần notice_writer")
    stages: list[Stage] = [
        QueryRewriteStage(enabled=cfg.stages.query_rewrite.enabled, catalog=loaded.catalog),
        RetrievalStage(retriever),
        FusionStage(),
        GenerationStage(
            generator,
            revision=cfg.generator.revision,
            runtime_info=runtime_info or {},
            notice_writer=notice_writer if cfg.generation.empty_answer_notice else None,
        ),
    ]
    return QnuChatPipeline(
        config_name=loaded.name,
        config_hash=loaded.sha256,
        snapshot=snapshot,
        stages=stages,
    )
