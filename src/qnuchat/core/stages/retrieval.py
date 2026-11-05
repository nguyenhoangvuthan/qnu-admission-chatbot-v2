"""Retrieval và fusion: ghi lại ứng viên từng nhánh và các passage thực sự vào prompt."""

from typing import Any

from qnuchat.core.ports import Hit, Retriever
from qnuchat.core.stages.base import RunState
from qnuchat.documents import Passage


def _hit(hit: Hit) -> dict[str, Any]:
    return {"chunk_id": hit.passage.chunk_id, "score": hit.score, "rank": hit.rank}


class RetrievalStage:
    name = "retrieval"
    enabled = True
    note = ""

    def __init__(self, retriever: Retriever):
        self._retriever = retriever

    def run(self, state: RunState) -> dict[str, Any]:
        result = self._retriever.retrieve(state.search_text)
        state.retrieval = result
        return {
            "branches": {name: [_hit(h) for h in hits] for name, hits in result.branches.items()},
            "fused": [_hit(h) for h in result.fused],
            **result.meta,
        }


class FusionStage:
    """Passage sống sót sau gộp và ngân sách; đây là thứ model thực sự nhìn thấy."""

    name = "fusion"
    enabled = True
    note = ""

    def run(self, state: RunState) -> dict[str, Any]:
        assert state.retrieval is not None, "fusion chạy trước retrieval"
        state.passages = [hit.passage for hit in state.retrieval.fused]
        # Số token của prompt chỉ biết sau khi gọi vLLM: xem generation.prompt_tokens.
        return {
            "passages": [_passage(p) for p in state.passages],
            "n_passages": len(state.passages),
            "n_chars": sum(len(p.text) for p in state.passages),
        }


def _passage(p: Passage) -> dict[str, Any]:
    return {
        "chunk_id": p.chunk_id,
        "source_id": p.source_id,
        "page": p.page,
        "source_year": p.source_year,
        "text": p.text,
    }
