import math

import pytest

from qnuchat.core.ports import Hit
from qnuchat.documents import Passage
from qnuchat.eval.metrics.retrieval import ndcg_at_k, recall_at_k, reciprocal_rank


def hits(*chunk_ids_pages) -> list[Hit]:
    return [
        Hit(passage=Passage(cid, "nguon", page, "x"), score=1.0, rank=i)
        for i, (cid, page) in enumerate(chunk_ids_pages, start=1)
    ]


def test_recall_counts_gold_pages_found():
    retrieved = hits(("p004", 4), ("p005", 5))
    assert recall_at_k(retrieved, gold_page_ids=[4, 9], k=5) == pytest.approx(0.5)


def test_recall_is_one_when_all_gold_pages_present():
    assert recall_at_k(hits(("p004", 4)), gold_page_ids=[4], k=5) == 1.0


def test_split_chunks_of_same_page_count_once():
    """p012a và p012b đều thuộc trang 12 — không được tính thành hai lần trúng."""
    retrieved = hits(("p012a", 12), ("p012b", 12))
    assert recall_at_k(retrieved, gold_page_ids=[12], k=5) == 1.0


def test_recall_respects_cutoff_k():
    retrieved = hits(("p004", 4), ("p005", 5), ("p009", 9))
    assert recall_at_k(retrieved, gold_page_ids=[9], k=2) == 0.0


def test_recall_of_item_without_gold_pages_is_nan():
    assert math.isnan(recall_at_k(hits(("p004", 4)), gold_page_ids=[], k=5))


def test_reciprocal_rank_uses_first_gold_position():
    retrieved = hits(("p004", 4), ("p009", 9))
    assert reciprocal_rank(retrieved, gold_page_ids=[9]) == pytest.approx(0.5)


def test_reciprocal_rank_is_zero_when_nothing_relevant():
    assert reciprocal_rank(hits(("p004", 4)), gold_page_ids=[99]) == 0.0


def test_ndcg_is_one_for_perfect_ordering():
    retrieved = hits(("p004", 4), ("p005", 5), ("p006", 6))
    assert ndcg_at_k(retrieved, gold_page_ids=[4, 5], k=3) == pytest.approx(1.0)


def test_ndcg_penalises_relevant_result_placed_later():
    good = ndcg_at_k(hits(("p004", 4), ("p099", 99)), [4], k=2)
    bad = ndcg_at_k(hits(("p099", 99), ("p004", 4)), [4], k=2)
    assert good > bad
