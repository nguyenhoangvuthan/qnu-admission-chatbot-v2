import math

import pytest

from qnuchat.eval.metrics.retrieval import (
    hit_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


def hits(*pages: int, source_id: str = "nguon") -> list[tuple[str, int]]:
    """Cặp `(source_id, page)` theo thứ hạng, cùng một nguồn."""
    return [(source_id, page) for page in pages]


def gold(*pages: int, source_id: str = "nguon") -> set[tuple[str, int]]:
    return {(source_id, page) for page in pages}


def test_recall_counts_gold_pages_found():
    assert recall_at_k(hits(4, 5), gold(4, 9), k=5) == pytest.approx(0.5)


def test_recall_is_one_when_all_gold_pages_present():
    assert recall_at_k(hits(4), gold(4), k=5) == 1.0


def test_split_chunks_of_same_page_count_once():
    """Hai passage của trang 12 không được tính thành hai lần trúng."""
    assert recall_at_k(hits(12, 12), gold(12), k=5) == 1.0


def test_duplicate_page_does_not_push_later_gold_out_of_rank():
    """Trang lặp không chiếm thêm hạng: trang 9 vẫn là trang thứ hai."""
    assert reciprocal_rank(hits(4, 4, 9), gold(9)) == pytest.approx(0.5)


def test_recall_respects_cutoff_k():
    assert recall_at_k(hits(4, 5, 9), gold(9), k=2) == 0.0


def test_recall_of_item_without_gold_pages_is_nan():
    assert math.isnan(recall_at_k(hits(4), set(), k=5))


def test_ndcg_of_item_without_gold_pages_is_nan():
    assert math.isnan(ndcg_at_k(hits(4), set(), k=5))


def test_reciprocal_rank_uses_first_gold_position():
    assert reciprocal_rank(hits(4, 9), gold(9)) == pytest.approx(0.5)


def test_reciprocal_rank_is_zero_when_nothing_relevant():
    assert reciprocal_rank(hits(4), gold(99)) == 0.0


def test_ndcg_is_one_for_perfect_ordering():
    assert ndcg_at_k(hits(4, 5, 6), gold(4, 5), k=3) == pytest.approx(1.0)


def test_ndcg_penalises_relevant_result_placed_later():
    good = ndcg_at_k(hits(4, 99), gold(4), k=2)
    bad = ndcg_at_k(hits(99, 4), gold(4), k=2)
    assert good > bad


def test_same_page_number_in_another_source_is_not_a_hit():
    retrieved = [("nguon-b", 5)]
    assert recall_at_k(retrieved, {("nguon-a", 5)}, k=5) == 0.0
    assert reciprocal_rank(retrieved, {("nguon-a", 5)}) == 0.0
    assert ndcg_at_k(retrieved, {("nguon-a", 5)}, k=5) == 0.0
    assert hit_at_k(retrieved, {("nguon-a", 5)}, k=5) is False


def test_same_page_number_in_two_sources_counts_as_two_pages():
    """("a", 5) và ("b", 5) là hai trang khác nhau, không khử lặp lẫn nhau."""
    retrieved = [("a", 5), ("b", 5)]
    assert recall_at_k(retrieved, {("a", 5), ("b", 5)}, k=2) == 1.0
    assert reciprocal_rank(retrieved, {("b", 5)}) == pytest.approx(0.5)


def test_hit_at_k_is_true_when_any_gold_page_in_top_k():
    assert hit_at_k([("a", 1), ("a", 9)], {("a", 9), ("a", 3)}, k=2) is True


def test_hit_at_k_respects_cutoff_k():
    assert hit_at_k(hits(4, 5, 9), gold(9), k=2) is False


def test_hit_at_k_is_false_without_gold_pages():
    assert hit_at_k(hits(4), set(), k=5) is False
