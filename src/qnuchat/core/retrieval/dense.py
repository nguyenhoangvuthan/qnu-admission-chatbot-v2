"""Dense search trong bộ nhớ: cosine trên vector đã chuẩn hoá."""

import numpy as np

from qnuchat.core.ports import Embedder, Hit
from qnuchat.documents import Passage


def _l2_normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.clip(norms, 1e-12, None)


class DenseIndex:
    def __init__(self, passages: list[Passage], embedder: Embedder):
        self.passages = passages
        self._embedder = embedder
        self.matrix = _l2_normalise(
            np.asarray(embedder.encode([p.text for p in passages]), dtype=np.float32)
        )

    def search(self, query: str, top_k: int) -> list[Hit]:
        k = min(top_k, len(self.passages))
        if k == 0:
            return []
        vector = _l2_normalise(np.asarray(self._embedder.encode([query]), dtype=np.float32))[0]
        scores = self.matrix @ vector
        order = np.argsort(-scores)[:k]
        return [
            Hit(passage=self.passages[int(idx)], score=float(scores[idx]), rank=rank)
            for rank, idx in enumerate(order, start=1)
        ]
