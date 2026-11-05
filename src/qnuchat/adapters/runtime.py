"""Dựng phần nặng của pipeline thật: đọc nguồn, chia passage, snapshot, embedder, index, client.

Logic chọn lựa đã nằm ở các module khác; file này chỉ nối chúng theo cấu hình.
"""

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from qnuchat.adapters.embeddings.bge import BGEEmbedder
from qnuchat.adapters.embeddings.cache import CorpusCachedEmbedder, embedding_cache_key
from qnuchat.adapters.generation.generator import VllmGenerator
from qnuchat.adapters.generation.notice_writer import VllmNoticeWriter
from qnuchat.core.config import CorpusConfig, LoadedConfig
from qnuchat.core.contracts import Snapshot
from qnuchat.core.ports import Generator, NoticeWriter
from qnuchat.core.retrieval.bm25 import BM25Index
from qnuchat.core.retrieval.dense import DenseIndex
from qnuchat.core.retrieval.hybrid import HybridRetriever
from qnuchat.core.snapshot import build_snapshot
from qnuchat.documents import Passage
from qnuchat.ingest.chunking import chunk_pages
from qnuchat.ingest.pdf import load_pdf_pages


@dataclass(frozen=True)
class Runtime:
    retriever: HybridRetriever
    generator: Generator
    snapshot: Snapshot
    api: OpenAI
    embedding: dict[str, Any]  # BGEEmbedder.describe(): device, torch_version, …
    # Có khi cờ generation.empty_answer_notice bật; cùng client vLLM với generator.
    notice_writer: NoticeWriter | None = None


def load_passages(corpus: CorpusConfig) -> list[Passage]:
    passages: list[Passage] = []
    for source in corpus.sources:
        pages = load_pdf_pages(source.path, frozenset(source.excluded_pages))
        passages += chunk_pages(
            pages,
            source_id=source.source_id,
            max_chars=corpus.max_chunk_chars,
            source_year=source.source_year,
        )
    if not passages:
        raise ValueError("Corpus rỗng: không có passage nào sau khi loại trang")
    return passages


def build_runtime(
    loaded: LoadedConfig,
    *,
    base_url: str,
    api_key: str,
    timeout_s: float,
    embedding_device: str,
    cache_dir: str | Path,
) -> Runtime:
    cfg = loaded.config
    passages = load_passages(cfg.corpus)
    snapshot = build_snapshot(corpus=cfg.corpus, embedding=cfg.embedding, passages=passages)

    # device="cpu"/"cuda" đến từ cấu hình vận hành; resolve_device FAIL NGAY nếu đòi CUDA mà
    # không có (không lặng lẽ chạy CPU).
    embedder = BGEEmbedder(cfg.embedding.model, cfg.embedding.revision, device=embedding_device)
    describe = embedder.describe()
    key = embedding_cache_key(
        content_hash=snapshot.content_hash,
        model=cfg.embedding.model,
        revision=cfg.embedding.revision,
        device=describe["device"],
        torch_version=describe["torch_version"],
        st_version=importlib.metadata.version("sentence-transformers"),
    )
    cached = CorpusCachedEmbedder(
        embedder, [p.text for p in passages], Path(cache_dir) / f"emb-{key}.npy"
    )
    retriever = HybridRetriever(
        BM25Index(passages),
        DenseIndex(passages, cached),
        top_k=cfg.retrieval.top_k,
        rrf_k=cfg.retrieval.rrf_k,
        embedding_device=describe["device"],
    )
    # max_retries=0 và timeout ở tầng I/O: deadline nằm trong thread, không bọc từ ngoài.
    api = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0)
    generator = VllmGenerator(
        api,
        model=cfg.generator.model,
        max_tokens=cfg.generator.max_tokens,
        seed=cfg.generator.seed,
        chat_template_kwargs=cfg.generator.chat_template_kwargs,
    )
    notice_writer = (
        VllmNoticeWriter(
            api,
            model=cfg.generator.model,
            seed=cfg.generator.seed,
            chat_template_kwargs=cfg.generator.chat_template_kwargs,
        )
        if cfg.generation.empty_answer_notice
        else None
    )
    return Runtime(
        retriever=retriever,
        generator=generator,
        snapshot=snapshot,
        api=api,
        embedding=describe,
        notice_writer=notice_writer,
    )
