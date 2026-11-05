import unicodedata
from datetime import date

import pytest
from pydantic import ValidationError

from qnuchat.core.contracts import (
    STAGE_NAMES,
    Answer,
    Claim,
    Clarification,
    Confidence,
    Query,
    Snapshot,
    StageTrace,
    Trace,
    Turn,
)
from qnuchat.core.errors import PipelineError
from tests.support.fakes import make_query, make_snapshot

TODAY = date(2026, 9, 29)


def make_trace(stages=None) -> Trace:
    stages = stages or {n: StageTrace(status="disabled", duration_ms=1.5) for n in STAGE_NAMES}
    return Trace(
        pipeline_config_name="b3",
        pipeline_config_hash="h" * 64,
        snapshot=Snapshot(
            id="s",
            content_hash="c" * 64,
            vector_hash="v",
        ),
        asked_at=TODAY,
        stages=stages,
    )


def test_query_strips_surrounding_whitespace():
    assert Query(text="  Học phí?  \n", asked_at=TODAY).text == "Học phí?"


@pytest.mark.parametrize("text", ["", "   ", "\n\t ", "x" * 1001])
def test_query_rejects_blank_and_oversize(text):
    with pytest.raises(ValidationError):
        Query(text=text, asked_at=TODAY)


def test_query_accepts_exactly_one_thousand_characters():
    assert len(Query(text="x" * 1000, asked_at=TODAY).text) == 1000


def test_query_accepts_decomposed_vietnamese():
    text = unicodedata.normalize("NFD", "Điểm chuẩn ngành Sư phạm Toán năm 2025?")
    assert Query(text=text, asked_at=TODAY).text == text


def test_query_defaults_and_extra_fields():
    query = Query(text="q", asked_at=TODAY)
    assert query.history == []
    with pytest.raises(ValidationError):
        Query(text="q", asked_at=TODAY, unexpected=1)


def test_query_requires_asked_at():
    with pytest.raises(ValidationError):
        Query(text="q")


def test_confidence_is_always_uncalibrated_self_report():
    confidence = Confidence(value=0.5)
    assert (confidence.source, confidence.calibrated) == ("model_self_report", False)
    with pytest.raises(ValidationError):
        Confidence(value=0.5, calibrated=True)
    with pytest.raises(ValidationError):
        Confidence(value=1.5)



def test_trace_requires_every_stage():
    stages = {n: StageTrace(status="disabled") for n in STAGE_NAMES if n != "fusion"}
    with pytest.raises(ValidationError):
        make_trace(stages)


def test_trace_rejects_unknown_stage():
    stages = {n: StageTrace(status="disabled") for n in STAGE_NAMES}
    stages["mystery"] = StageTrace(status="disabled")
    with pytest.raises(ValidationError):
        make_trace(stages)


def test_trace_normalises_stage_order_after_a_jsonb_round_trip():
    reversed_stages = {n: StageTrace(status="disabled") for n in reversed(STAGE_NAMES)}
    assert list(make_trace(reversed_stages).stages) == list(STAGE_NAMES)


def test_comparable_drops_duration_and_nothing_else():
    trace = make_trace()
    comparable = trace.comparable()
    assert all("duration_ms" not in s for s in comparable["stages"].values())
    assert comparable["stages"]["fusion"] == {"status": "disabled", "data": {}}
    assert comparable["pipeline_config_hash"] == "h" * 64
    assert comparable["asked_at"] == "2026-09-29"


def test_trace_requires_asked_at():
    with pytest.raises(ValidationError):
        Trace.model_validate(make_trace().model_dump(mode="json", exclude={"asked_at"}))


def test_answer_round_trips_through_json():
    answer = Answer(
        abstain=False,
        answer="15 triệu",
        claims=[Claim(subject="a", predicate="b", value="c")],
        citation_ids=["p004"],
        confidence=Confidence(value=0.8),
        trace=make_trace(),
    )
    assert Answer.model_validate_json(answer.model_dump_json()) == answer


def _trace():
    return Trace(
        pipeline_config_name="b3-chat",
        pipeline_config_hash="h" * 64,
        snapshot=make_snapshot(),
        asked_at=make_query().asked_at,
        stages={n: StageTrace(status="disabled") for n in STAGE_NAMES},
    )


CLAR = Clarification(slot="major", prompt="Bạn muốn hỏi học phí của ngành nào?", options=["A", "B"])


def test_clarify_answer_has_no_confidence_claims_or_citations():
    answer = Answer(
        abstain=False, answer=CLAR.prompt, claims=[], citation_ids=[],
        confidence=None, clarification=CLAR, trace=_trace(),
    )
    assert answer.clarification.slot == "major"


@pytest.mark.parametrize(
    "fields",
    [
        {"confidence": None, "clarification": None},  # câu trả lời thường phải có confidence
        {"confidence": Confidence(value=0.5), "clarification": CLAR},
        {"confidence": None, "clarification": CLAR, "abstain": True},
        {"confidence": None, "clarification": CLAR, "citation_ids": ["p1"]},
    ],
)
def test_answer_validator_rejects_mixed_shapes(fields):
    base = {"abstain": False, "answer": "x", "claims": [], "citation_ids": [], "trace": _trace()}
    with pytest.raises(ValidationError):
        Answer(**{**base, **fields})


def test_clarification_options_are_capped_at_six():
    with pytest.raises(ValidationError):
        Clarification(slot="major", prompt="?", options=[str(i) for i in range(7)])


def test_turn_carries_an_optional_clarification():
    assert Turn(question="q", answer="a", abstain=False).clarification is None
    assert Turn(question="q", answer="a", abstain=False, clarification=CLAR).clarification == CLAR


def test_pipeline_error_details_default_to_empty():
    assert PipelineError("generation", "timeout", "x").details == {}
    err = PipelineError("generation", "timeout", "x", details={"request": {"model": "m"}})
    assert err.details == {"request": {"model": "m"}}
