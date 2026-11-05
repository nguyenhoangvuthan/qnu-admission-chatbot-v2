"""Snapshot tri thức: băm file nguồn, tham số chia và toàn bộ text passage."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from qnuchat.core.config import CorpusConfig, EmbeddingConfig
from qnuchat.core.contracts import Snapshot
from qnuchat.documents import Passage


def _sha256(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_snapshot(
    *,
    corpus: CorpusConfig,
    embedding: EmbeddingConfig,
    passages: Sequence[Passage],
) -> Snapshot:
    content_hash = _sha256(
        {
            "sources": [
                {
                    "source_id": source.source_id,
                    "sha256": hashlib.sha256(Path(source.path).read_bytes()).hexdigest(),
                    "excluded_pages": sorted(source.excluded_pages),
                    "source_year": source.source_year,
                }
                for source in corpus.sources
            ],
            "max_chunk_chars": corpus.max_chunk_chars,
            "chunks": [[p.chunk_id, p.page, p.text] for p in passages],
        }
    )
    vector_hash = _sha256(
        {
            "model": embedding.model,
            "revision": embedding.revision,
            "chunk_ids": [p.chunk_id for p in passages],
        }
    )
    return Snapshot(id=content_hash[:12], content_hash=content_hash, vector_hash=vector_hash)
