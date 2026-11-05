"""BM25 cho tiếng Việt."""

import bm25s

from qnuchat.core.ports import Hit
from qnuchat.documents import Passage

# Mặc định của bm25s là r"(?u)\b\w\w+\b", loại bỏ token một ký tự.
# Dữ liệu tuyển sinh đầy số lẻ và mã tổ hợp một ký tự, nên phải nới.
TOKEN_PATTERN = r"(?u)\b\w+\b"


def _tokenize(texts: list[str]):
    # stopwords=[] và stemmer=None: bm25s chỉ có tài nguyên cho tiếng Anh.
    return bm25s.tokenize(
        texts,
        lower=True,
        token_pattern=TOKEN_PATTERN,
        stopwords=[],
        stemmer=None,
        show_progress=False,
    )


class BM25Index:
    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self._retriever = bm25s.BM25()
        self._retriever.index(_tokenize([p.text for p in passages]), show_progress=False)

    def search(self, query: str, top_k: int) -> list[Hit]:
        k = min(top_k, len(self.passages))
        if k == 0:
            return []
        doc_ids, scores = self._retriever.retrieve(_tokenize([query]), k=k, show_progress=False)
        return [
            Hit(passage=self.passages[int(doc_ids[0, i])], score=float(scores[0, i]), rank=i + 1)
            for i in range(k)
        ]
