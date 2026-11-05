import numpy as np

from qnuchat.adapters.embeddings.cache import CorpusCachedEmbedder, embedding_cache_key


class CountingEmbedder:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return np.arange(len(texts) * 3, dtype=np.float32).reshape(len(texts), 3)


def test_corpus_encode_is_computed_once_then_read_from_disk(tmp_path):
    inner, texts = CountingEmbedder(), ["một", "hai", "ba"]
    path = tmp_path / "cache" / "emb.npy"
    first = CorpusCachedEmbedder(inner, texts, path).encode(texts)
    second = CorpusCachedEmbedder(CountingEmbedder(), texts, path).encode(texts)
    assert np.array_equal(first, second) and path.exists()
    assert len(inner.calls) == 1


def test_cache_hit_never_calls_the_inner_embedder(tmp_path):
    texts, path = ["một", "hai"], tmp_path / "emb.npy"
    CorpusCachedEmbedder(CountingEmbedder(), texts, path).encode(texts)
    inner = CountingEmbedder()
    CorpusCachedEmbedder(inner, texts, path).encode(texts)
    assert inner.calls == []


def test_queries_bypass_the_cache(tmp_path):
    inner, path = CountingEmbedder(), tmp_path / "emb.npy"
    cached = CorpusCachedEmbedder(inner, ["một", "hai"], path)
    cached.encode(["câu hỏi"])
    cached.encode(["câu hỏi"])
    assert len(inner.calls) == 2 and not path.exists()


def test_cache_key_depends_on_every_part():
    base = {
        "content_hash": "c" * 64,
        "model": "m",
        "revision": "r" * 40,
        "device": "cpu",
        "torch_version": "2.14.0",
        "st_version": "6.1.0",
    }
    keys = {embedding_cache_key(**base)}
    for name, other in [
        ("content_hash", "d" * 64),
        ("model", "n"),
        ("revision", "s" * 40),
        ("device", "cuda"),
        ("torch_version", "2.15.0"),
        ("st_version", "6.2.0"),
    ]:
        keys.add(embedding_cache_key(**{**base, name: other}))
    assert len(keys) == 7 and all(len(k) == 16 for k in keys)
