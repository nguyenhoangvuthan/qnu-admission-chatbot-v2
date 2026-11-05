"""Spec #17 §4: câu rỗng mà không từ chối → câu báo chưa có thông tin, từ chối EMPTY_ANSWER."""

import pytest

from qnuchat.core.config import load_pipeline_config
from qnuchat.core.contracts import Claim
from qnuchat.core.errors import PipelineError
from qnuchat.core.pipeline import assemble_pipeline
from tests.support.fakes import (
    SHIPPED_CONFIG,
    FakeGenerator,
    FakeNoticeWriter,
    FakeRetriever,
    make_output,
    make_pipeline,
    make_query,
    make_snapshot,
)

EMPTY = {
    "answer": "",
    "claims": [Claim(subject="ngành", predicate="điểm chuẩn", value="chưa được cung cấp")],
    "citation_ids": ["p004"],
}
NOTICE_KEYS = {
    "request",
    "raw_response",
    "request_sha256",
    "prompt_tokens",
    "completion_tokens",
    "finish_reason",
}


@pytest.fixture
def notice_config(tmp_path):
    path = tmp_path / "notice.yaml"
    path.write_text(
        f"extends: {SHIPPED_CONFIG}\ngeneration: {{empty_answer_notice: true}}\n", encoding="utf-8"
    )
    return path


def run(config, output, notice=None, text="Học phí ngành CNTT?"):
    notice = notice or FakeNoticeWriter()
    pipeline = make_pipeline(generator=FakeGenerator(output), config=config, notice_writer=notice)
    return pipeline.answer(make_query(text)), notice


def test_empty_answer_becomes_an_empty_answer_abstention(notice_config):
    answer, notice = run(
        notice_config, make_output(**EMPTY), text="điểm chuẩn ngành Sư phạm Tiếng Anh năm 2025"
    )
    assert notice.calls == ["điểm chuẩn ngành Sư phạm Tiếng Anh năm 2025"]
    assert (answer.abstain, answer.abstain_source, answer.abstain_reason) == (
        True,
        "model",
        "EMPTY_ANSWER",
    )
    assert answer.abstain_detail == notice.text
    assert answer.claims == [] and answer.citation_ids == []
    data = answer.trace.stages["generation"].data
    assert data["raw_response"] == "{}"  # bản gốc giữ nguyên
    assert set(data["empty_answer_notice"]) == NOTICE_KEYS
    assert data["empty_answer_notice"]["raw_response"] == notice.text


def test_whitespace_only_answer_is_empty(notice_config):
    answer, notice = run(notice_config, make_output(**{**EMPTY, "answer": "  \n"}))
    assert answer.abstain_reason == "EMPTY_ANSWER" and len(notice.calls) == 1


def test_model_abstention_never_calls_the_notice_writer(notice_config):
    output = make_output(
        abstain=True, abstain_reason="không có", answer="", claims=[], citation_ids=[]
    )
    answer, notice = run(notice_config, output)
    assert notice.calls == []
    assert (answer.abstain_reason, answer.abstain_detail) == ("MODEL_SELF", "không có")
    assert "empty_answer_notice" not in answer.trace.stages["generation"].data


def test_non_empty_answer_has_no_notice_key(notice_config):
    answer, notice = run(notice_config, make_output())
    assert notice.calls == [] and answer.abstain is False
    assert "empty_answer_notice" not in answer.trace.stages["generation"].data


def test_flag_off_keeps_empty_answer_as_answered():
    answer, notice = run(SHIPPED_CONFIG, make_output(**EMPTY))
    assert notice.calls == []
    assert answer.abstain is False and answer.answer == ""
    assert "empty_answer_notice" not in answer.trace.stages["generation"].data


def test_notice_failure_is_a_generation_error_keeping_both_requests(notice_config):
    err = PipelineError(
        "generation", "truncated", "x", details={"request": {"n": 2}, "raw_response": "Chưa"}
    )
    with pytest.raises(PipelineError) as info:
        run(notice_config, make_output(**EMPTY), notice=FakeNoticeWriter(error=err))
    stage = info.value.partial_trace.stages["generation"]
    assert stage.status == "error" and info.value.cause == "truncated"
    assert stage.data["raw_response"] == "{}"
    assert stage.data["request"]["messages"][1]["content"] == "Học phí ngành CNTT?"
    assert stage.data["empty_answer_notice"] == {"request": {"n": 2}, "raw_response": "Chưa"}


def test_flag_on_without_a_writer_is_refused(notice_config):
    with pytest.raises(ValueError, match="notice_writer"):
        assemble_pipeline(
            load_pipeline_config(notice_config),
            snapshot=make_snapshot(),
            retriever=FakeRetriever(),
            generator=FakeGenerator(),
        )
