import pytest
from pydantic import ValidationError

from qnuchat.eval.schema import ExpectedSlot, GoldItem


def test_gold_item_requires_aggregation_defaults_false():
    item = GoldItem(
        id="PIL-001",
        question="Học phí ngành X năm 2025?",
        origin="curated",
        risk="high",
        admission_year=2025,
        must_abstain=False,
        gold_page_ids=[42],
        expected_slots=[
            ExpectedSlot(
                subject="ngành X",
                predicate="học phí",
                value="1000",
                unit="đồng/tín chỉ",
                admission_year=2025,
            )
        ],
        required_conditions=["nêu rõ là mức năm 2025"],
        forbidden_claims=["mức học phí năm 2026"],
        source_family="tuition_x",
        reviewer="kent",
    )
    assert item.requires_aggregation is False


def test_gold_item_rejects_unknown_origin():
    with pytest.raises(ValidationError):
        GoldItem(
            id="PIL-002",
            question="q",
            origin="bịa",
            risk="normal",
            admission_year=2025,
            must_abstain=True,
            gold_page_ids=[],
            expected_slots=[],
            required_conditions=[],
            forbidden_claims=[],
            source_family="f",
            reviewer="kent",
        )
