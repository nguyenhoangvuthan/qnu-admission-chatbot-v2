import logging

import pytest

from qnuchat.core.contracts import STAGE_NAMES, StageTrace
from qnuchat.core.errors import PipelineError
from tests.support.fakes import FakeGenerator, FakeRetriever, make_pipeline, make_query


class Recorder:
    def __init__(self):
        self.events: list[tuple[str, StageTrace]] = []

    def __call__(self, name: str, stage_trace: StageTrace) -> None:
        self.events.append((name, stage_trace))


def test_observer_sees_every_stage_once_in_fixed_order():
    recorder = Recorder()
    answer = make_pipeline().answer(make_query(), on_stage=recorder)
    assert [name for name, _ in recorder.events] == list(STAGE_NAMES)
    for name, seen in recorder.events:
        assert seen == answer.trace.stages[name]


def test_observer_sees_disabled_error_and_skipped_stages():
    recorder = Recorder()
    retriever = FakeRetriever(error=RuntimeError("index hỏng"))
    with pytest.raises(PipelineError):
        make_pipeline(retriever).answer(make_query(), on_stage=recorder)
    statuses = {name: seen.status for name, seen in recorder.events}
    assert list(statuses) == list(STAGE_NAMES)
    assert statuses["query_rewrite"] == "disabled"
    assert statuses["retrieval"] == "error"
    assert statuses["fusion"] == statuses["generation"] == "not_applicable"


def test_answer_is_identical_with_and_without_observer():
    plain = make_pipeline().answer(make_query())
    observed = make_pipeline().answer(make_query(), on_stage=Recorder())
    assert observed.model_dump(exclude={"trace"}) == plain.model_dump(exclude={"trace"})
    assert observed.trace.comparable() == plain.trace.comparable()


def test_failing_observer_is_logged_and_does_not_change_the_answer(caplog, monkeypatch):
    # lint_imports() (tests/arch) cấu hình lại logging và tắt logger đã có: bật lại cho test này.
    monkeypatch.setattr(logging.getLogger("qnuchat.core.pipeline"), "disabled", False)

    def explode(name: str, stage_trace: StageTrace) -> None:
        raise RuntimeError("client đã đóng")

    plain = make_pipeline().answer(make_query())
    with caplog.at_level(logging.ERROR, logger="qnuchat.core.pipeline"):
        observed = make_pipeline().answer(make_query(), on_stage=explode)
    assert observed.trace.comparable() == plain.trace.comparable()
    assert observed.answer == plain.answer
    assert "stage_observer_failed" in caplog.text


def test_observer_cannot_mutate_the_stored_trace():
    def vandal(name: str, stage_trace: StageTrace) -> None:
        stage_trace.data["hacked"] = True

    answer = make_pipeline().answer(make_query(), on_stage=vandal)
    assert all("hacked" not in s.data for s in answer.trace.stages.values())


def test_generation_error_is_reported_before_the_pipeline_raises():
    recorder = Recorder()
    generator = FakeGenerator(error=PipelineError("generation", "timeout", "hết giờ"))
    with pytest.raises(PipelineError):
        make_pipeline(generator=generator).answer(make_query(), on_stage=recorder)
    assert dict(recorder.events)["generation"].status == "error"
