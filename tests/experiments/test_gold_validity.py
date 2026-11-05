"""Kiểm tính hợp lệ của gold pilot thật (Critical 1e).

Bỏ qua sạch sẽ khi `benchmarks/pilot/gold.jsonl` chưa tồn tại — file này chỉ
xuất hiện sau khi chủ dự án đối chiếu thủ công từng item với trang PDF nguồn
(10-15 giờ công, xem `benchmarks/pilot/README.md`).
"""

import pathlib

import pytest

from experiments.prepare_gold import PILOT_EXCLUDED_PAGES
from qnuchat.eval.schema import load_gold

GOLD_PATH = pathlib.Path("benchmarks/pilot/gold.jsonl")

pytestmark = pytest.mark.skipif(
    not GOLD_PATH.exists(),
    reason="benchmarks/pilot/gold.jsonl chưa được dựng — cần đối chiếu thủ công với PDF nguồn",
)


@pytest.fixture(scope="module")
def gold():
    return load_gold(GOLD_PATH)


def test_gold_has_60_to_80_items(gold):
    assert 60 <= len(gold) <= 80


def test_gold_ids_are_unique(gold):
    ids = [item.id for item in gold]
    assert len(ids) == len(set(ids))


def test_no_gold_page_id_falls_in_excluded_pages(gold):
    for item in gold:
        offending = set(item.gold_page_ids) & PILOT_EXCLUDED_PAGES
        assert not offending, f"{item.id} trích trang bị loại khỏi corpus: {offending}"


def test_answerable_items_cite_at_least_one_page(gold):
    for item in gold:
        if not item.must_abstain:
            assert item.gold_page_ids, f"{item.id} trả lời được nhưng không có gold_page_ids"


def test_must_abstain_items_have_no_expected_slots(gold):
    for item in gold:
        if item.must_abstain:
            assert item.expected_slots == [], f"{item.id} must_abstain nhưng vẫn có expected_slots"


def test_every_item_names_a_reviewer(gold):
    for item in gold:
        assert item.reviewer.strip(), f"{item.id} chưa có reviewer"


def test_every_noisy_item_shares_a_source_family_with_a_curated_item(gold):
    curated_families = {item.source_family for item in gold if item.origin == "curated"}
    for item in gold:
        if item.origin == "noisy":
            assert item.source_family in curated_families, (
                f"{item.id} (noisy) không cùng source_family với item curated nào"
            )
