"""Hành vi v2 phải khớp qnu_rag đã đo ở tag v1-final, ngoài dạng chunk_id.

Fixture ghi kết quả chạy thật của code cũ trên Cẩm nang 2025. So chữ của passage, thứ hạng và điểm
từng nhánh, gộp RRF, và nguyên văn prompt người dùng. Khác fixture nghĩa là baseline đã đo không còn
dùng được; đổi có chủ đích thì phải chạy lại baseline, không chỉ sửa fixture.

Riêng system prompt và schema đã cố ý khác v1 từ 06/11/2026 để hết câu trả lời rỗng, nên fixture ghi
giá trị v2 của hai phần đó: vẫn phát hiện đổi ngầm, nhưng không còn nghĩa là khớp v1.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from qnuchat.adapters.generation.generator import VllmGenerator
from qnuchat.adapters.generation.schema import RESPONSE_FORMAT
from qnuchat.core.retrieval.bm25 import BM25Index
from qnuchat.core.retrieval.dense import DenseIndex
from qnuchat.core.retrieval.fusion import rrf_fuse
from qnuchat.ingest.chunking import chunk_pages
from qnuchat.ingest.pdf import load_pdf_pages

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf"
GOLDEN = json.loads((ROOT / "tests/fixtures/pilot_parity.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(not PDF.exists(), reason="PDF corpus chưa có")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class HashEmbedder:
    """Túi từ băm vào 64 chiều: tất định, không cần model, vẫn cho thứ hạng khác BM25."""

    def encode(self, texts):
        vectors = np.zeros((len(texts), 64), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().split():
                vectors[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1
        return vectors


def ranking(hits):
    return [[h.passage.chunk_id, round(h.score, 6), h.rank] for h in hits]


@pytest.fixture(scope="module")
def corpus():
    pages = load_pdf_pages(PDF, frozenset({1, 2, 3, 107, 108}))
    passages = chunk_pages(pages, source_id="cam-nang-2025", max_chars=1500, source_year=2025)
    return pages, passages, BM25Index(passages), DenseIndex(passages, HashEmbedder())


def test_pdf_pages_match(corpus):
    assert [[p.page, sha(p.text)] for p in corpus[0]] == GOLDEN["pages"]


def test_passages_match(corpus):
    actual = [[p.chunk_id, p.page, len(p.text), sha(p.text)] for p in corpus[1]]
    assert actual == GOLDEN["chunks"]


@pytest.mark.parametrize("question", GOLDEN["queries"])
def test_rankings_and_prompt_match(corpus, question):
    _, _, bm25, dense = corpus
    expected = GOLDEN["queries"][question]
    bm25_hits, dense_hits = bm25.search(question, 20), dense.search(question, 20)
    fused = rrf_fuse([bm25_hits, dense_hits], 60, 5)
    assert ranking(bm25_hits) == expected["bm25"]
    assert ranking(dense_hits) == expected["dense"]
    assert ranking(fused) == expected["fused"]

    generator = VllmGenerator(
        None,
        model="Qwen/Qwen3-4B-AWQ",
        max_tokens=1024,
        seed=42,
        chat_template_kwargs={"enable_thinking": False},
    )
    request = generator.request_kwargs(question, [h.passage for h in fused])
    assert sorted(request) == expected["keys"]
    assert sha(request["messages"][0]["content"]) == expected["system_sha"]
    assert sha(request["messages"][1]["content"]) == expected["user_sha"]
    # Không sort_keys: thứ tự khoá là thứ tự model viết, đổi nó là đổi câu trả lời.
    response_format = json.dumps(RESPONSE_FORMAT, ensure_ascii=False)
    assert sha(response_format) == expected["response_format_sha"]
