import json
import re
from pathlib import Path

import pytest
import yaml

from experiments.live_check import (
    CORPUS_FILE,
    ShortIdRetriever,
    run_question,
    select_items,
    short_id,
    summarize,
    write_report,
)
from qnuchat.core.errors import PipelineError
from tests.support.fakes import (
    FakeGenerator,
    FakeRetriever,
    make_output,
    make_pipeline,
    make_retrieval,
)

ROOT = Path(__file__).resolve().parents[2]
SERVE = ROOT / "scripts/serve-vllm.sh"
PDF = f"data/tuyen-sinh-dai-hoc-chinh-quy/{CORPUS_FILE}"


def record(item_id, must_abstain=False, evidence=((PDF, 4),)):
    return {
        "item": {"id": item_id, "question": f"câu {item_id}", "must_abstain": must_abstain},
        "gold_evidence": [list(e) for e in evidence],
    }


def row(arm="dai", status="answered", **overrides):
    base = {
        "arm": arm,
        "id": "a",
        "question": "câu a",
        "must_abstain": False,
        "gold_pages": [4],
        "status": status,
        "cause": None,
        "answer": "Học phí là 15 triệu đồng.",
        "citation_ids": ["p004"],
        "unknown_citations": [],
        "cited_pages": [4],
        "seconds": 2.0,
    }
    return {**base, **overrides}


def test_short_id_drops_the_source_prefix_only():
    assert short_id("cam-nang-2025:p074") == "p074"
    assert short_id("cam-nang-2025:p086-2") == "p086-2"
    assert short_id("p004") == "p004"


def test_short_id_retriever_rewrites_every_branch_and_keeps_scores():
    result = ShortIdRetriever(FakeRetriever(prefixed_retrieval())).retrieve("q")
    assert [h.passage.chunk_id for h in result.fused] == ["p004", "p005"]
    assert [h.passage.chunk_id for h in result.branches["bm25"]] == ["p004", "p005"]
    assert result.fused[0].score == 1.0
    assert result.fused[0].passage.source_id == "cam-nang-2025"


def prefixed_retrieval():
    from dataclasses import replace

    base = make_retrieval(("p004", "p005"))
    fix = lambda hit: replace(
        hit, passage=replace(hit.passage, chunk_id=f"cam-nang-2025:{hit.passage.chunk_id}")
    )
    return replace(
        base,
        fused=[fix(h) for h in base.fused],
        branches={k: [fix(h) for h in v] for k, v in base.branches.items()},
    )


def test_select_keeps_only_questions_the_corpus_can_answer():
    other = ("data/x/TB1906.pdf", 2)
    records = [
        record("a"),
        record("b", evidence=(other,)),
        record("c", evidence=((PDF, 5), other)),
        record("d", must_abstain=True, evidence=()),
    ]
    assert {r["item"]["id"] for r in select_items(records, 10)} == {"a", "d"}


def test_select_is_stable_and_keeps_some_abstention_questions():
    records = [record(f"q{i}") for i in range(30)]
    records += [record(f"x{i}", must_abstain=True, evidence=()) for i in range(10)]
    first = select_items(records, 10)
    assert [r["item"]["id"] for r in first] == [
        r["item"]["id"] for r in select_items(list(reversed(records)), 10)
    ]
    assert len(first) == 10
    assert sum(r["item"]["must_abstain"] for r in first) == 2


def test_run_question_records_an_answer_with_cited_pages():
    pipeline = make_pipeline(FakeRetriever(), FakeGenerator())
    out = run_question(pipeline, record("a"), "dai")
    assert out["status"] == "answered"
    assert (out["citation_ids"], out["cited_pages"], out["gold_pages"]) == (["p004"], [4], [4])
    assert out["unknown_citations"] == []


def test_run_question_flags_citations_outside_the_retrieved_passages():
    output = make_output(citation_ids=["p004", "bia-ra"])
    out = run_question(make_pipeline(generator=FakeGenerator(output)), record("a"), "dai")
    assert out["unknown_citations"] == ["bia-ra"]


def test_execution_error_is_not_an_abstention():
    error = PipelineError("generation", "timeout", "hết giờ")
    out = run_question(make_pipeline(generator=FakeGenerator(error=error)), record("a"), "dai")
    assert (out["status"], out["cause"]) == ("error", "timeout")


def test_summary_counts_citation_quality_on_answered_rows_only():
    rows = [
        row(),
        row(citation_ids=["bia"], unknown_citations=["bia"], cited_pages=[]),
        row(citation_ids=[], cited_pages=[]),
        row(status="abstained", citation_ids=[], cited_pages=[], must_abstain=True),
        row(status="error", cause="timeout", citation_ids=[], cited_pages=[]),
    ]
    summary = summarize(rows)
    assert (summary["n"], summary["answered"], summary["abstained"]) == (5, 3, 1)
    assert summary["errors"] == {"timeout": 1}
    assert summary["answered_with_citation"] == 2
    assert summary["answered_with_unknown_citation"] == 1
    assert summary["cited_gold_page"] == 1
    assert summary["correct_abstention"] == 1


def test_report_lists_questions_whose_outcome_differs_between_arms(tmp_path):
    rows = [row("dai", id="a"), row("ngan", id="a", status="abstained", citation_ids=[])]
    rows += [row("dai", id="b"), row("ngan", id="b")]
    text = write_report(rows, tmp_path / "report.md", {"vllm_version": "x"})
    assert "| Trả lời có nội dung |" in text
    assert "| **Trả lời rỗng hoặc rác** |" in text
    assert re.search(r"Khác nhau giữa hai arm: 1", text)
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == text


def test_serve_flags_match_the_pipeline_config_and_stay_on_loopback():
    config = yaml.safe_load(
        (ROOT / "configs/pipeline/b3-qwen3-4b-awq.yaml").read_text(encoding="utf-8")
    )
    script = SERVE.read_text(encoding="utf-8")
    assert config["generator"]["model"] in script
    assert config["generator"]["revision"] in script
    assert "--host 127.0.0.1" in script
    assert "--default-chat-template-kwargs" not in script


def test_report_output_is_json_serialisable():
    assert json.dumps(summarize([row()]))


def test_nothing_runs_from_the_old_repository():
    for name in ("serve-vllm.sh", "thuc-nghiem-live.sh"):
        assert "qnu-admission-chatbot" not in (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_vllm_environment_is_locked_with_the_cuda_torch_build():
    lock = (ROOT / "environments/vllm/uv.lock").read_text(encoding="utf-8")
    assert 'name = "vllm"\nversion = "0.33.0"' in lock
    assert 'name = "torch"\nversion = "2.14.0+cu132"' in lock


@pytest.mark.parametrize("answer", ["", "   ", ":[{", None])
def test_blank_or_garbage_answers_do_not_count_as_real_answers(answer):
    summary = summarize([row(answer=answer), row()])
    assert summary["answered"] == 2
    assert summary["answered_blank"] == 1
    assert summary["answered_with_content"] == 1


def test_a_short_numeric_answer_is_not_blank():
    assert summarize([row(answer="135")])["answered_blank"] == 0


def test_citation_quality_ignores_blank_answers():
    """Trích dẫn của câu rỗng không giúp được người đọc, không được làm đẹp chỉ số."""
    summary = summarize([row(answer=""), row()])
    assert summary["cited_gold_page"] == 1
    assert summary["answered_with_citation"] == 1


def test_run_question_keeps_claims_and_raw_response_for_diagnosis():
    output = make_output(answer="", raw_content='{"answer":""}')
    out = run_question(make_pipeline(generator=FakeGenerator(output)), record("a"), "dai")
    assert out["raw_response"] == '{"answer":""}'
    assert out["claims"][0]["value"] == "15"
