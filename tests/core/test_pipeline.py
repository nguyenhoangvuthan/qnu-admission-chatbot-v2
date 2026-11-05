from datetime import date

import pytest

from qnuchat.core.contracts import STAGE_NAMES, Turn
from qnuchat.core.errors import PipelineError
from qnuchat.core.pipeline import QnuChatPipeline
from qnuchat.core.stages.base import RunState
from qnuchat.core.stages.generation import GenerationStage
from qnuchat.core.stages.retrieval import FusionStage
from tests.support.fakes import (
    FakeGenerator,
    FakeRetriever,
    make_output,
    make_pipeline,
    make_query,
    make_snapshot,
)

EXECUTED = {"retrieval", "fusion", "generation"}


def test_trace_lists_every_stage_in_fixed_order():
    answer = make_pipeline().answer(make_query())
    assert list(answer.trace.stages) == list(STAGE_NAMES)
    assert answer.trace.pipeline_config_name == "b3-qwen3-4b-awq"
    assert len(answer.trace.pipeline_config_hash) == 64


def test_trace_carries_asked_at_from_the_query_even_on_error():
    query = make_query(asked_at=date(2027, 1, 2))
    assert make_pipeline().answer(query).trace.asked_at == date(2027, 1, 2)
    failing = make_pipeline(generator=FakeGenerator(error=PipelineError("generation", "x", "y")))
    with pytest.raises(PipelineError) as info:
        failing.answer(query)
    assert info.value.partial_trace.asked_at == date(2027, 1, 2)


def test_only_retrieval_fusion_and_generation_execute():
    stages = make_pipeline().answer(make_query()).trace.stages
    assert {n for n, s in stages.items() if s.status == "executed"} == EXECUTED
    assert all(s.status == "disabled" for n, s in stages.items() if n not in EXECUTED)
    assert "history" in stages["query_rewrite"].data["note"]


def test_retrieval_stage_records_branches_fused_and_device():
    data = make_pipeline().answer(make_query()).trace.stages["retrieval"].data
    assert set(data["branches"]) == {"bm25", "dense"}
    assert data["fused"][0] == {"chunk_id": "p004", "score": 1.0, "rank": 1}
    assert data["embedding_device"] == "cpu" and data["depth"] == 20


def test_fusion_stage_records_the_passages_the_model_saw():
    data = make_pipeline().answer(make_query()).trace.stages["fusion"].data
    assert [p["chunk_id"] for p in data["passages"]] == ["p004", "p005"]
    assert data["passages"][0]["page"] == 4 and "học phí" in data["passages"][0]["text"]
    assert data["n_passages"] == 2 and data["n_chars"] > 0


def test_generation_stage_records_request_usage_and_runtime():
    data = make_pipeline().answer(make_query()).trace.stages["generation"].data
    assert data["request_sha256"] == "r" * 64
    assert (data["prompt_tokens"], data["completion_tokens"]) == (1200, 80)
    assert data["finish_reason"] == "stop" and data["model"] == "Qwen/Qwen3-4B-AWQ"
    assert data["revision"] == "74d4bd2bd4bff9cafc9345221320bffb08b406a3"
    assert data["runtime"] == {"vllm_version": "0.30.0-test"}
    assert data["unknown_citations"] == []


def test_history_never_reaches_retrieval_or_generation():
    retriever, generator = FakeRetriever(), FakeGenerator()
    query = make_query(history=[Turn(question="Câu trước?", answer="Trả lời trước", abstain=False)])
    make_pipeline(retriever, generator).answer(query)
    assert retriever.calls == [query.text]
    assert generator.calls[0][0] == query.text


def test_answered_turn_has_no_abstain_fields_and_answer_level_citations():
    answer = make_pipeline().answer(make_query())
    assert (answer.abstain, answer.abstain_source, answer.abstain_reason) == (False, None, None)
    assert answer.abstain_detail is None
    assert answer.citation_ids == ["p004"]
    assert (answer.confidence.source, answer.confidence.calibrated) == ("model_self_report", False)


def test_model_abstention_fills_source_reason_and_detail():
    generator = FakeGenerator(
        make_output(
            abstain=True,
            abstain_reason="Tài liệu không nêu học phí",
            answer="",
            claims=[],
            citation_ids=[],
            confidence=0.1,
        )
    )
    answer = make_pipeline(generator=generator).answer(make_query())
    assert answer.abstain is True
    assert answer.abstain_source == "model"
    assert answer.abstain_reason == "MODEL_SELF"
    assert answer.abstain_detail == "Tài liệu không nêu học phí"


def test_unknown_citations_are_reported_not_dropped():
    generator = FakeGenerator(make_output(citation_ids=["p004", "p999"]))
    answer = make_pipeline(generator=generator).answer(make_query())
    assert answer.citation_ids == ["p004", "p999"]
    assert answer.trace.stages["generation"].data["unknown_citations"] == ["p999"]


def test_generation_error_carries_a_partial_trace():
    generator = FakeGenerator(error=PipelineError("generation", "timeout", "hết giờ"))
    with pytest.raises(PipelineError) as info:
        make_pipeline(generator=generator).answer(make_query())
    error = info.value
    assert (error.stage, error.cause) == ("generation", "timeout")
    stages = error.partial_trace.stages
    assert stages["retrieval"].status == "executed"
    assert stages["fusion"].status == "executed"
    assert stages["generation"].status == "error"
    assert stages["generation"].data == {"cause": "timeout", "message": "hết giờ"}
    assert stages["query_rewrite"].status == "disabled"


def test_retrieval_error_skips_later_enabled_stages_but_keeps_disabled_ones():
    retriever = FakeRetriever(error=RuntimeError("index hỏng"))
    generator = FakeGenerator()
    with pytest.raises(PipelineError) as info:
        make_pipeline(retriever, generator).answer(make_query())
    error = info.value
    assert (error.stage, error.cause) == ("retrieval", "error")
    assert isinstance(error.__cause__, RuntimeError)
    stages = error.partial_trace.stages
    assert stages["retrieval"].status == "error"
    for name in ("fusion", "generation"):
        assert stages[name].status == "not_applicable"
        assert stages[name].data == {"reason": "skipped_after_error"}
    assert stages["query_rewrite"].status == "disabled"
    assert generator.calls == []


def test_pipeline_requires_the_fixed_stage_order():
    with pytest.raises(ValueError, match="thứ tự"):
        QnuChatPipeline(
            config_name="x",
            config_hash="y",
            snapshot=make_snapshot(),
            stages=[FusionStage()],
        )


OLD_GENERATION_KEYS = {
    "model",
    "revision",
    "request_sha256",
    "prompt_tokens",
    "completion_tokens",
    "finish_reason",
    "unknown_citations",
    "runtime",
}


def test_generation_trace_adds_only_request_and_raw_response():
    """Nghiệm thu 3: tắt query_rewrite thì trace chỉ thêm hai trường của generation."""
    answer = make_pipeline().answer(make_query())
    data = answer.trace.stages["generation"].data
    assert set(data) == OLD_GENERATION_KEYS | {"request", "raw_response"}
    assert data["request"]["messages"][1]["content"] == "Học phí ngành CNTT?"
    assert data["raw_response"] == "{}"


def test_rewrite_disabled_sends_query_text_even_with_history():
    generator, retriever = FakeGenerator(), FakeRetriever()
    history = [Turn(question="Ngành KTPM học mấy năm?", answer="4,5 năm", abstain=False)]
    make_pipeline(retriever=retriever, generator=generator).answer(
        make_query("Ra trường làm gì?", history=history)
    )
    assert generator.calls[0][0] == "Ra trường làm gì?"
    assert retriever.calls == ["Ra trường làm gì?"]


def test_generation_stage_sends_search_text_not_query_text():
    """Stage trước đổi `search_text` thì generator nhận câu đó, không phải `query.text`."""
    generator = FakeGenerator()
    stage = GenerationStage(generator, revision="rev", runtime_info={})
    state = RunState(
        query=make_query("Còn học phí?"), search_text="Học phí ngành CNTT năm 2025?"
    )
    data = stage.run(state)
    assert generator.calls[0][0] == "Học phí ngành CNTT năm 2025?"
    assert data["request"]["messages"][1]["content"] == "Học phí ngành CNTT năm 2025?"


def test_failed_generation_keeps_the_request_in_the_partial_trace():
    request = {"model": "m", "messages": [{"role": "user", "content": "q"}]}
    error = PipelineError(
        "generation", "timeout", "hết giờ", details={"request": request, "raw_response": None}
    )
    with pytest.raises(PipelineError) as caught:
        make_pipeline(generator=FakeGenerator(error=error)).answer(make_query())
    data = caught.value.partial_trace.stages["generation"].data
    assert data == {
        "cause": "timeout",
        "message": "hết giờ",
        "request": request,
        "raw_response": None,
    }
