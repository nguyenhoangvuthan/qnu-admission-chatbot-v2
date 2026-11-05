"""Metric truy xuất. So ở mức TRANG, không ở mức passage."""

import math

from qnuchat.core.ports import Hit


def _pages_in_order(retrieved: list[Hit], k: int) -> list[int]:
    """Số trang theo thứ hạng, đã khử trùng lặp do một trang bị tách nhiều passage."""
    seen: list[int] = []
    for hit in retrieved[:k]:
        if hit.passage.page not in seen:
            seen.append(hit.passage.page)
    return seen


def recall_at_k(retrieved: list[Hit], gold_page_ids: list[int], k: int) -> float:
    if not gold_page_ids:
        return float("nan")
    found = set(_pages_in_order(retrieved, k)) & set(gold_page_ids)
    return len(found) / len(set(gold_page_ids))


def reciprocal_rank(retrieved: list[Hit], gold_page_ids: list[int]) -> float:
    gold = set(gold_page_ids)
    for position, page in enumerate(_pages_in_order(retrieved, len(retrieved)), start=1):
        if page in gold:
            return 1.0 / position
    return 0.0


def ndcg_at_k(retrieved: list[Hit], gold_page_ids: list[int], k: int) -> float:
    if not gold_page_ids:
        return float("nan")
    gold = set(gold_page_ids)
    pages = _pages_in_order(retrieved, k)
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, page in enumerate(pages, start=1)
        if page in gold
    )
    ideal_hits = min(len(gold), k)
    idcg = sum(1.0 / math.log2(position + 1) for position in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0
