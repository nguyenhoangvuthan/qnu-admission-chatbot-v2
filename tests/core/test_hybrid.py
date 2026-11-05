import numpy as np
import pytest

from qnuchat.core.ports import Hit
from qnuchat.core.retrieval.bm25 import BM25Index
from qnuchat.core.retrieval.dense import DenseIndex
from qnuchat.core.retrieval.fusion import RRF_K, rrf_depth, rrf_fuse
from qnuchat.core.retrieval.hybrid import HybridRetriever
from qnuchat.documents import Passage

A = Passage("p004", "nguon", 4, "a")
B = Passage("p005", "nguon", 5, "b")
C = Passage("p006", "nguon", 6, "c")


class FakeIndex:
    def __init__(self, ordered: list[Passage]):
        self._ordered = ordered

    def search(self, query: str, top_k: int) -> list[Hit]:
        return [
            Hit(passage=p, score=1.0 / rank, rank=rank)
            for rank, p in enumerate(self._ordered[:top_k], start=1)
        ]


def hybrid(first, second, top_k=3):
    return HybridRetriever(
        FakeIndex(first), FakeIndex(second), top_k=top_k, rrf_k=RRF_K, embedding_device="cpu"
    )


def test_rrf_constant_is_sixty():
    assert RRF_K == 60


def test_passage_ranked_first_by_both_wins():
    assert hybrid([A, B, C], [A, C, B], top_k=1).retrieve("q").fused[0].passage == A


def test_rrf_score_matches_formula():
    fused = hybrid([A, B], [B, A], top_k=2).retrieve("q").fused
    expected = 1 / (RRF_K + 1) + 1 / (RRF_K + 2)
    assert {h.passage.chunk_id: h.score for h in fused} == pytest.approx(
        {"p004": expected, "p005": expected}
    )


def test_passage_present_in_only_one_list_still_included():
    fused = hybrid([A], [B], top_k=2).retrieve("q").fused
    assert {h.passage.chunk_id for h in fused} == {"p004", "p005"}


def test_output_ranks_are_reassigned_consecutively():
    assert [h.rank for h in hybrid([A, B, C], [C, B, A]).retrieve("q").fused] == [1, 2, 3]


def test_rrf_depth_is_four_times_top_k_with_floor_twenty():
    assert (rrf_depth(1), rrf_depth(5), rrf_depth(10)) == (20, 20, 40)


def test_rrf_fuse_breaks_score_ties_by_chunk_id():
    fused = rrf_fuse(
        [[Hit(passage=B, score=1.0, rank=1)], [Hit(passage=A, score=1.0, rank=1)]],
        rrf_k=RRF_K,
        top_k=2,
    )
    assert [h.passage.chunk_id for h in fused] == ["p004", "p005"]


def test_rrf_fuse_of_no_lists_is_empty():
    assert rrf_fuse([], rrf_k=RRF_K, top_k=5) == []


def test_two_sources_with_the_same_page_stay_separate_after_fusion():
    x = Passage("nguon-a:p001", "nguon-a", 1, "x")
    y = Passage("nguon-b:p001", "nguon-b", 1, "y")
    assert len(hybrid([x, y], [y, x], top_k=2).retrieve("q").fused) == 2


class WordEmbedder:
    """Vector tất định theo từ: đủ để dense xếp hạng khác BM25."""

    VOCAB = ("học", "phí", "điểm", "chuẩn", "ký", "túc", "chỉ", "tiêu", "toán", "ngành")

    def encode(self, texts):
        out = np.full((len(texts), len(self.VOCAB)), 0.01, dtype=np.float32)
        for i, text in enumerate(texts):
            words = text.lower().split()
            for j, word in enumerate(self.VOCAB):
                out[i, j] += words.count(word)
        return out


def test_retrieval_records_both_branches_and_run_metadata():
    passages = [
        Passage("p004", "nguon", 4, "Học phí ngành Công nghệ thông tin là 15 triệu", 2025),
        Passage("p005", "nguon", 5, "Điểm chuẩn ngành Sư phạm Toán là 24 điểm", 2025),
        Passage("p006", "nguon", 6, "Ký túc xá có 2000 chỗ ở cho sinh viên", 2025),
        Passage("p007", "nguon", 7, "Chỉ tiêu tuyển sinh năm 2025 là 4500", 2025),
    ]
    result = HybridRetriever(
        BM25Index(passages),
        DenseIndex(passages, WordEmbedder()),
        top_k=3,
        rrf_k=60,
        embedding_device="cpu",
    ).retrieve("học phí")
    assert set(result.branches) == {"bm25", "dense"}
    assert len(result.branches["bm25"]) == len(passages) == len(result.branches["dense"])
    assert result.meta == {"depth": 20, "top_k": 3, "rrf_k": 60, "embedding_device": "cpu"}
    assert result.fused[0].passage.chunk_id == "p004"
