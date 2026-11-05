"""load_gold — nửa tự động hóa được của việc dựng gold (Critical 1)."""

import json
import pathlib

import pytest
from pydantic import ValidationError

from qnuchat.eval.schema import load_gold


def _item(item_id: str) -> dict:
    return {
        "id": item_id,
        "question": "Học phí ngành CNTT năm 2025 là bao nhiêu?",
        "origin": "curated",
        "risk": "high",
        "admission_year": 2025,
        "must_abstain": False,
        "gold_page_ids": [42],
        "expected_slots": [],
        "required_conditions": [],
        "forbidden_claims": [],
        "source_family": "tuition_it",
        "reviewer": "kent",
    }


def test_load_gold_parses_two_well_formed_lines(tmp_path: pathlib.Path):
    path = tmp_path / "gold.jsonl"
    path.write_text(
        json.dumps(_item("PIL-001"), ensure_ascii=False)
        + "\n"
        + json.dumps(_item("PIL-002"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    items = load_gold(path)
    assert [i.id for i in items] == ["PIL-001", "PIL-002"]


def test_load_gold_skips_blank_lines(tmp_path: pathlib.Path):
    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n"
        + json.dumps(_item("PIL-001"), ensure_ascii=False)
        + "\n\n   \n"
        + json.dumps(_item("PIL-002"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    items = load_gold(path)
    assert len(items) == 2


def test_load_gold_raises_on_malformed_line(tmp_path: pathlib.Path):
    path = tmp_path / "gold.jsonl"
    path.write_text(
        json.dumps(_item("PIL-001"), ensure_ascii=False) + "\n{ not json\n", encoding="utf-8"
    )
    with pytest.raises(json.JSONDecodeError):
        load_gold(path)


def test_load_gold_raises_on_line_missing_required_field(tmp_path: pathlib.Path):
    broken = _item("PIL-001")
    del broken["reviewer"]
    path = tmp_path / "gold.jsonl"
    path.write_text(json.dumps(broken, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_gold(path)


def test_load_gold_accepts_str_or_path(tmp_path: pathlib.Path):
    path = tmp_path / "gold.jsonl"
    path.write_text(json.dumps(_item("PIL-001"), ensure_ascii=False) + "\n", encoding="utf-8")
    assert len(load_gold(str(path))) == 1
