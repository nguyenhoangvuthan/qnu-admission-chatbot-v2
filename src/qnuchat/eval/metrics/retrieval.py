"""Metric truy xuất. So ở mức TRANG, không ở mức passage.

Một trang là cặp `(source_id, page)`: trang 5 của nguồn A không khớp trang 5 của nguồn B
(spec phần A §4.2).
"""

import math
from collections.abc import Collection, Sequence

PageKey = tuple[str, int]


def _pages_in_order(retrieved: Sequence[PageKey], k: int) -> list[PageKey]:
    """Trang theo thứ hạng trong `k` vị trí đầu.

    Đã khử trùng lặp do một trang bị tách nhiều passage.
    """
    seen: list[PageKey] = []
    for page in retrieved[:k]:
        if page not in seen:
            seen.append(page)
    return seen


def recall_at_k(retrieved: Sequence[PageKey], gold: Collection[PageKey], k: int) -> float:
    if not gold:
        return float("nan")
    gold_set = set(gold)
    found = set(_pages_in_order(retrieved, k)) & gold_set
    return len(found) / len(gold_set)


def reciprocal_rank(retrieved: Sequence[PageKey], gold: Collection[PageKey]) -> float:
    gold_set = set(gold)
    for position, page in enumerate(_pages_in_order(retrieved, len(retrieved)), start=1):
        if page in gold_set:
            return 1.0 / position
    return 0.0


def ndcg_at_k(retrieved: Sequence[PageKey], gold: Collection[PageKey], k: int) -> float:
    if not gold:
        return float("nan")
    gold_set = set(gold)
    pages = _pages_in_order(retrieved, k)
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, page in enumerate(pages, start=1)
        if page in gold_set
    )
    ideal_hits = min(len(gold_set), k)
    idcg = sum(1.0 / math.log2(position + 1) for position in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def hit_at_k(retrieved: Sequence[PageKey], gold: Collection[PageKey], k: int) -> bool:
    """Có ít nhất một trang gold trong `k` vị trí đầu không. Gold rỗng thì `False`."""
    gold_set = set(gold)
    return any(page in gold_set for page in retrieved[:k])
