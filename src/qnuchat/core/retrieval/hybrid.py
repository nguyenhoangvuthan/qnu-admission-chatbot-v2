"""Retriever BM25 + dense gộp RRF, ghi lại ứng viên của từng nhánh."""

from typing import Protocol

from qnuchat.core.ports import Hit, RetrievalResult
from qnuchat.core.retrieval.fusion import rrf_depth, rrf_fuse


class SearchIndex(Protocol):
    def search(self, query: str, top_k: int) -> list[Hit]: ...


class HybridRetriever:
    def __init__(
        self,
        bm25: SearchIndex,
        dense: SearchIndex,
        *,
        top_k: int,
        rrf_k: int,
        embedding_device: str,
    ):
        self._bm25 = bm25
        self._dense = dense
        self._top_k = top_k
        self._rrf_k = rrf_k
        self._embedding_device = embedding_device

    def retrieve(self, query: str) -> RetrievalResult:
        depth = rrf_depth(self._top_k)
        bm25_hits = self._bm25.search(query, top_k=depth)
        dense_hits = self._dense.search(query, top_k=depth)
        return RetrievalResult(
            branches={"bm25": bm25_hits, "dense": dense_hits},
            fused=rrf_fuse([bm25_hits, dense_hits], self._rrf_k, self._top_k),
            meta={
                "depth": depth,
                "top_k": self._top_k,
                "rrf_k": self._rrf_k,
                "embedding_device": self._embedding_device,
            },
        )
