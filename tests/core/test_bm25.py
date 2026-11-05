from qnuchat.core.retrieval.bm25 import BM25Index
from qnuchat.documents import Passage

CHUNKS = [
    Passage("p004", "nguon", 4, "Học phí ngành Công nghệ thông tin là 15 triệu đồng"),
    Passage("p005", "nguon", 5, "Chỉ tiêu ngành Sư phạm Toán học năm 2025"),
    Passage("p006", "nguon", 6, "Ký túc xá và chỗ ở cho sinh viên năm nhất"),
]


def test_search_returns_requested_number_of_results():
    index = BM25Index(CHUNKS)
    assert len(index.search("học phí", top_k=2)) == 2


def test_search_ranks_lexically_matching_chunk_first():
    index = BM25Index(CHUNKS)
    assert index.search("ký túc xá", top_k=1)[0].passage.chunk_id == "p006"


def test_ranks_are_one_indexed_and_consecutive():
    index = BM25Index(CHUNKS)
    assert [r.rank for r in index.search("ngành", top_k=3)] == [1, 2, 3]


def test_single_digit_token_is_searchable():
    """token_pattern mặc định của bm25s bỏ token 1 ký tự — số liệu tuyển sinh cần giữ."""
    chunks = [
        Passage("p010", "nguon", 10, "Tổ hợp A 0 1 dành cho ngành kỹ thuật"),
        Passage("p011", "nguon", 11, "Không liên quan gì cả"),
    ]
    index = BM25Index(chunks)
    assert index.search("0", top_k=1)[0].passage.chunk_id == "p010"


def test_top_k_larger_than_corpus_is_clamped():
    index = BM25Index(CHUNKS)
    assert len(index.search("ngành", top_k=99)) == 3
