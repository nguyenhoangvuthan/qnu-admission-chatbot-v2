import hashlib
import json

import pytest

from qnuchat.eval.cases import (
    EvalCase,
    StaleRunError,
    check_gold_unchanged,
    gold_digests,
    read_rows,
    select_cases,
)

SOURCES = {"data/a.pdf": "nguon-a"}


def row(id: str, must_abstain: bool = False, evidence: list | None = None) -> dict:
    """Dòng nháp tối thiểu: `item` đủ trường bắt buộc của `GoldItem`."""
    return {
        "item": {
            "id": id,
            "question": f"Câu hỏi {id}?",
            "origin": "curated",
            "risk": "normal",
            "admission_year": 2025,
            "must_abstain": must_abstain,
            "gold_page_ids": [],
            "expected_slots": [],
            "required_conditions": [],
            "forbidden_claims": [],
            "source_family": "fam",
            "reviewer": "",
        },
        "task_type": "lookup",
        "gold_evidence": evidence if evidence is not None else [],
    }


def write_jsonl(path, rows) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def test_keeps_case_whose_evidence_is_all_in_corpus():
    cases, excluded = select_cases([row("Q1", evidence=[["data/a.pdf", 4]])], SOURCES)
    assert [c.gold_evidence for c in cases] == [(("nguon-a", 4),)] and excluded == []


def test_kept_case_carries_item_and_task_type():
    cases, _ = select_cases([row("Q1", evidence=[["data/a.pdf", 4]])], SOURCES)
    assert isinstance(cases[0], EvalCase)
    assert cases[0].item.id == "Q1" and cases[0].task_type == "lookup"


def test_excludes_case_with_evidence_outside_corpus_with_reason():
    evidence = [["data/a.pdf", 4], ["data/b.pdf", 1]]
    _, excluded = select_cases([row("Q2", evidence=evidence)], SOURCES)
    assert excluded == [{"id": "Q2", "reason": "source_not_in_corpus", "gold_evidence": evidence}]


def test_excludes_answerable_case_without_evidence():
    _, excluded = select_cases([row("Q3", evidence=[])], SOURCES)
    assert excluded[0]["reason"] == "no_gold_evidence"


def test_keeps_must_abstain_case_even_without_evidence():
    cases, _ = select_cases([row("Q4", must_abstain=True, evidence=[])], SOURCES)
    assert cases[0].item.must_abstain and cases[0].gold_evidence == ()


def test_must_abstain_case_with_evidence_outside_corpus_is_kept_with_empty_evidence():
    cases, excluded = select_cases(
        [row("Q5", must_abstain=True, evidence=[["data/b.pdf", 1]])], SOURCES
    )
    assert [c.item.id for c in cases] == ["Q5"] and cases[0].gold_evidence == () and excluded == []


def test_source_path_is_compared_in_posix_form():
    cases, _ = select_cases([row("Q6", evidence=[["data/./a.pdf", 2]])], SOURCES)
    assert cases[0].gold_evidence == (("nguon-a", 2),)


def test_read_rows_keeps_file_order_and_skips_blank_lines(tmp_path):
    first, second = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    write_jsonl(first, [row("Q1"), row("Q2")])
    second.write_text("\n" + json.dumps(row("Q3")) + "\n\n", encoding="utf-8")
    assert [r["item"]["id"] for r in read_rows([first, second])] == ["Q1", "Q2", "Q3"]


def test_duplicate_id_across_files_is_refused(tmp_path):
    first, second = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    write_jsonl(first, [row("Q1")])
    write_jsonl(second, [row("Q1")])
    with pytest.raises(ValueError, match="Q1"):
        read_rows([first, second])


def test_gold_digests_records_posix_path_and_sha256(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_bytes(b"{}\n")
    assert gold_digests([path]) == [
        {"path": path.as_posix(), "sha256": hashlib.sha256(b"{}\n").hexdigest()}
    ]


def test_unchanged_gold_file_passes(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    check_gold_unchanged(gold_digests([path]))


def test_changed_gold_file_is_refused(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    recorded = gold_digests([path])
    path.write_text("{} \n", encoding="utf-8")
    with pytest.raises(StaleRunError, match="g.jsonl"):
        check_gold_unchanged(recorded)


def test_stale_error_shows_old_and_new_hash_prefixes(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_bytes(b"{}\n")
    recorded = gold_digests([path])
    path.write_bytes(b"{} \n")
    old = hashlib.sha256(b"{}\n").hexdigest()[:12]
    new = hashlib.sha256(b"{} \n").hexdigest()[:12]
    with pytest.raises(StaleRunError) as info:
        check_gold_unchanged(recorded)
    assert old in str(info.value) and new in str(info.value)
