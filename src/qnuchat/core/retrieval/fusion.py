"""Reciprocal Rank Fusion: gộp theo thứ hạng, không theo điểm."""

from collections.abc import Sequence

from qnuchat.core.ports import Hit
from qnuchat.documents import Passage

RRF_K = 60


def rrf_depth(top_k: int) -> int:
    """Độ sâu lấy ở mỗi nhánh trước khi gộp: sâu hơn top_k để phép gộp có gì mà gộp."""
    return max(top_k * 4, 20)


def rrf_fuse(ranked_lists: Sequence[Sequence[Hit]], rrf_k: int, top_k: int) -> list[Hit]:
    """Điểm BM25 và điểm cosine không cùng thang đo, nên chỉ dùng thứ hạng.

    Hoà điểm thì xếp theo chunk_id để kết quả tất định.
    """
    fused: dict[str, float] = {}
    seen: dict[str, Passage] = {}
    for hits in ranked_lists:
        for hit in hits:
            key = hit.passage.chunk_id
            fused[key] = fused.get(key, 0.0) + 1.0 / (rrf_k + hit.rank)
            seen[key] = hit.passage
    ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    return [
        Hit(passage=seen[key], score=score, rank=rank)
        for rank, (key, score) in enumerate(ordered, start=1)
    ]
