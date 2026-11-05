"""Nối các phần thật bằng PDF nhỏ tự sinh; chỉ embedder và vLLM là giả."""

from types import SimpleNamespace

import numpy as np
import pymupdf
import pytest

from qnuchat.adapters import runtime as runtime_module
from qnuchat.adapters.runtime import build_runtime, load_passages
from qnuchat.core.config import CorpusConfig, SourceConfig, load_pipeline_config


class TinyEmbedder:
    def __init__(self, *_, **__):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return np.ones((len(texts), 4), dtype=np.float32)

    def describe(self):
        return {"device": "cpu", "torch_version": "test"}


def write_pdf(path, texts):
    doc = pymupdf.open()
    for text in texts:
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return str(path)


def corpus(tmp_path, excluded=()):
    first = write_pdf(tmp_path / "a.pdf", ["hoc phi nam 2025", "chi tieu"])
    second = write_pdf(tmp_path / "b.pdf", ["ky tuc xa"])
    return CorpusConfig(
        max_chunk_chars=1500,
        sources=[
            SourceConfig(
                source_id="nguon-a", path=first, excluded_pages=list(excluded), source_year=2025
            ),
            SourceConfig(source_id="nguon-b", path=second),
        ],
    )


def test_passages_from_all_sources_have_unique_ids(tmp_path):
    passages = load_passages(corpus(tmp_path))
    assert [p.chunk_id for p in passages] == ["nguon-a:p001", "nguon-a:p002", "nguon-b:p001"]
    assert [p.source_year for p in passages] == [2025, 2025, None]


def test_excluded_pages_apply_to_their_own_source_only(tmp_path):
    passages = load_passages(corpus(tmp_path, excluded=[1]))
    assert [p.chunk_id for p in passages] == ["nguon-a:p002", "nguon-b:p001"]


def test_empty_corpus_is_an_error(tmp_path):
    path = write_pdf(tmp_path / "a.pdf", ["x"])
    config = CorpusConfig(
        max_chunk_chars=1500,
        sources=[SourceConfig(source_id="a", path=path, excluded_pages=[1])],
    )
    with pytest.raises(ValueError, match="rỗng"):
        load_passages(config)


def test_build_runtime_wires_a_working_retriever(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module, "BGEEmbedder", TinyEmbedder)
    loaded = load_pipeline_config("configs/pipeline/b3-chat.yaml")
    config = loaded.config.model_copy(update={"corpus": corpus(tmp_path)})
    built = build_runtime(
        SimpleNamespace(config=config),
        base_url="http://localhost:9/v1",
        api_key="k",
        timeout_s=1.0,
        embedding_device="cpu",
        cache_dir=tmp_path / "cache",
    )
    result = built.retriever.retrieve("ky tuc xa")
    assert result.branches["bm25"][0].passage.chunk_id == "nguon-b:p001"
    assert len(result.fused) == 3
    assert result.meta["embedding_device"] == "cpu"
    assert built.notice_writer is not None
    assert list((tmp_path / "cache").glob("emb-*.npy"))
