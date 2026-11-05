"""Cache ma trận embedding của corpus ra đĩa (spec web app §5.2 bước 4).

Chỉ cache lần encode toàn bộ corpus; câu hỏi luôn đi qua embedder thật.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np


def embedding_cache_key(
    *,
    content_hash: str,
    model: str,
    revision: str,
    device: str,
    torch_version: str,
    st_version: str,
) -> str:
    """Khoá gồm cả thiết bị và phiên bản thư viện: vector CPU và CUDA không lẫn nhau."""
    parts = {
        "content_hash": content_hash,
        "model": model,
        "revision": revision,
        "device": device,
        "torch_version": torch_version,
        "st_version": st_version,
    }
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class CorpusCachedEmbedder:
    def __init__(self, inner, corpus_texts: Sequence[str], cache_path: Path):
        self._inner = inner
        self._corpus_texts = list(corpus_texts)
        self._path = Path(cache_path)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if list(texts) != self._corpus_texts:
            return self._inner.encode(texts)
        if self._path.exists():
            return np.load(self._path)
        matrix = np.asarray(self._inner.encode(texts), dtype=np.float32)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Ghi ra file tạm rồi đổi tên: tiến trình chết giữa chừng không để lại cache nửa vời.
        temporary = self._path.with_name(self._path.stem + ".partial.npy")
        np.save(temporary, matrix)
        temporary.replace(self._path)
        return matrix
