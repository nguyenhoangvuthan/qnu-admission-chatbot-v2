import pytest

from qnuchat.core.contracts import Clarification, Turn
from qnuchat.core.errors import PipelineError
from tests.support.fakes import CHAT_CONFIG, FakeGenerator, FakeRetriever, make_pipeline, make_query

AFTER = ("retrieval", "fusion", "generation")


def chat(retriever=None, generator=None):
    return make_pipeline(retriever=retriever, generator=generator, config=CHAT_CONFIG)


def test_clarify_stops_every_later_stage_without_calling_retrieval_or_llm():
    retriever, generator = FakeRetriever(), FakeGenerator()
    answer = chat(retriever, generator).answer(make_query("Học phí bao nhiêu?"))
    assert answer.clarification.slot == "major"
    assert answer.answer == answer.clarification.prompt
    assert (answer.abstain, answer.confidence, answer.claims, answer.citation_ids) == (
        False, None, [], [],
    )
    assert retriever.calls == [] and generator.calls == []
    stages = answer.trace.stages
    assert stages["query_rewrite"].status == "executed"
    assert stages["query_rewrite"].data["decision"] == "clarify"
    for name in AFTER:
        if stages[name].status != "disabled":
            assert (stages[name].status, stages[name].data) == (
                "not_applicable", {"reason": "clarification_needed"},
            )
    assert stages["retrieval"].status == "not_applicable"


def test_follow_up_sends_the_standalone_question_to_retrieval_and_the_llm():
    retriever, generator = FakeRetriever(), FakeGenerator()
    history = [
        Turn(question="Ngành Kỹ thuật phần mềm học mấy năm?", answer="4,5 năm", abstain=False)
    ]
    answer = chat(retriever, generator).answer(make_query("Ra trường làm gì?", history=history))
    expected = "Ra trường làm gì? ngành Kỹ thuật phần mềm"
    assert retriever.calls == [expected]
    assert generator.calls[0][0] == expected
    assert answer.trace.stages["generation"].data["request"]["messages"][1]["content"] == expected
    assert answer.clarification is None and answer.confidence is not None


def test_reply_to_a_clarification_answers_the_pending_question():
    ask = Clarification(slot="major", prompt="?", options=[])
    history = [Turn(question="Học phí bao nhiêu?", answer="?", abstain=False, clarification=ask)]
    generator = FakeGenerator()
    chat(generator=generator).answer(make_query("Kỹ thuật phần mềm", history=history))
    assert generator.calls[0][0] == "Học phí bao nhiêu? ngành Kỹ thuật phần mềm"


def test_unexpected_rewrite_failure_is_an_execution_error(monkeypatch):
    import qnuchat.core.stages.query_rewrite as stage_module

    def boom(query, matcher):
        raise KeyError("hỏng")

    monkeypatch.setattr(stage_module, "rewrite", boom)
    with pytest.raises(PipelineError) as caught:
        chat().answer(make_query("Học phí ngành CNTT?"))
    assert caught.value.stage == "query_rewrite"
    assert caught.value.partial_trace.stages["retrieval"].data == {"reason": "skipped_after_error"}


def test_enabled_stage_without_catalog_is_refused():
    from qnuchat.core.stages.query_rewrite import QueryRewriteStage

    with pytest.raises(ValueError, match="danh mục"):
        QueryRewriteStage(enabled=True)
