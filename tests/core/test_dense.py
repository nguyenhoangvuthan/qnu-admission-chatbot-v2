from typing import ClassVar

import numpy as np
import pytest

from qnuchat.adapters.embeddings.bge import EmbedderDeviceError, resolve_device
from qnuchat.core.retrieval.dense import DenseIndex
from qnuchat.documents import Passage

CHUNKS = [
    Passage("p004", "nguon", 4, "học phí"),
    Passage("p005", "nguon", 5, "chỉ tiêu"),
    Passage("p006", "nguon", 6, "ký túc xá"),
]


class FakeEmbedder:
    """Vector one-hot: chunk thứ i thành trục i; truy vấn khớp chunk theo bảng tra."""

    TABLE: ClassVar[dict[str, int]] = {"học phí": 0, "chỉ tiêu": 1, "ký túc xá": 2}

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), 3), dtype=np.float32)
        for row, text in enumerate(texts):
            vectors[row, self.TABLE[text]] = 1.0
        return vectors


def test_dense_search_finds_exact_semantic_match():
    index = DenseIndex(CHUNKS, embedder=FakeEmbedder())
    assert index.search("ký túc xá", top_k=1)[0].passage.chunk_id == "p006"


def test_dense_scores_are_descending():
    index = DenseIndex(CHUNKS, embedder=FakeEmbedder())
    scores = [r.score for r in index.search("học phí", top_k=3)]
    assert scores == sorted(scores, reverse=True)


def test_dense_ranks_are_one_indexed():
    index = DenseIndex(CHUNKS, embedder=FakeEmbedder())
    assert [r.rank for r in index.search("học phí", top_k=3)] == [1, 2, 3]


def test_dense_top_k_clamped_to_corpus_size():
    index = DenseIndex(CHUNKS, embedder=FakeEmbedder())
    assert len(index.search("học phí", top_k=50)) == 3


def test_dense_embeddings_are_l2_normalised():
    index = DenseIndex(CHUNKS, embedder=FakeEmbedder())
    norms = np.linalg.norm(index.matrix, axis=1)
    assert np.allclose(norms, 1.0)


def test_resolve_device_defaults_to_cuda(monkeypatch):
    """Không khai gì thì chạy GPU — không âm thầm lùi về CPU."""
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_device(None) == "cuda"


def test_resolve_device_raises_when_cuda_missing(monkeypatch):
    """Torch CPU-only / driver hỏng phải làm run DỪNG, không phải chạy chậm 40 lần."""
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(EmbedderDeviceError) as excinfo:
        resolve_device("cuda")
    assert "cpu" in str(excinfo.value)


def test_resolve_device_allows_explicit_cpu_optout(monkeypatch):
    """Máy dev không GPU vẫn chạy được, nhưng phải KHAI BÁO chủ đích."""
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("cpu") == "cpu"
