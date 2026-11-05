import pytest

from qnuchat.documents import Page
from qnuchat.ingest.chunking import chunk_pages


def chunk(text: str, page: int = 7, source_id: str = "nguon-a", max_chars: int = 1500):
    return chunk_pages([Page(page, text)], source_id=source_id, max_chars=max_chars)


def test_short_page_becomes_single_passage_without_part_number():
    passages = chunk("ngắn", page=12)
    assert [p.chunk_id for p in passages] == ["nguon-a:p012"]
    assert (passages[0].page, passages[0].source_id) == (12, "nguon-a")


def test_long_page_splits_into_numbered_parts_on_the_same_page():
    passages = chunk("\n\n".join(["câu " * 100] * 6))
    assert [p.chunk_id for p in passages] == ["nguon-a:p007-1", "nguon-a:p007-2"]
    assert {p.page for p in passages} == {7}


def test_two_sources_with_the_same_page_do_not_collide():
    """Pilot sinh `p001` cho cả hai nguồn, nên RRF gộp nhầm hai đoạn khác nhau thành một."""
    a = chunk("nguồn A", page=1, source_id="nguon-a")
    b = chunk("nguồn B", page=1, source_id="nguon-b")
    assert a[0].chunk_id != b[0].chunk_id


@pytest.mark.parametrize("text", ["x" * 10_000, "\n".join(["y" * 90] * 100)])
def test_no_passage_exceeds_the_limit(text):
    """Pilot chỉ tách một lần: trang 10.000 ký tự cho hai phần 5.000 dù giới hạn 1.500."""
    passages = chunk(text)
    assert max(len(p.text) for p in passages) <= 1500
    assert len({p.chunk_id for p in passages}) == len(passages)


def test_split_keeps_text_order_and_content():
    lines = [f"dòng {i:03d} " + "x" * 40 for i in range(200)]
    passages = chunk("\n".join(lines))
    assert "\n".join(p.text for p in passages) == "\n".join(lines)


def test_split_lands_on_newline_not_at_raw_midpoint():
    """Chỉ nhánh cắt theo "\\n" mới tái tạo được nguyên văn khi nối lại bằng "\\n"."""
    lines = [f"dòng {i:02d} " + "x" * (30 + i % 7) for i in range(45)]
    text = "\n".join(lines)
    midpoint = len(text) // 2
    # Tiền đề: điểm giữa thô KHÔNG được rơi vào ký tự xuống dòng, nếu không hai
    # nhánh cho cùng kết quả và test mất khả năng phân biệt.
    assert text[midpoint] != "\n"
    first, second = chunk(text)
    assert first.text + "\n" + second.text == text


def test_no_separator_falls_back_to_the_midpoint():
    first, second = chunk("a" * 3000)
    assert abs(len(first.text) - len(second.text)) < 100


def test_empty_page_produces_no_passage():
    assert chunk("   ") == []


def test_page_number_is_padded_to_three_digits():
    assert chunk("a", page=105)[0].chunk_id == "nguon-a:p105"


def test_source_year_is_carried():
    passages = chunk_pages([Page(1, "a")], source_id="s", source_year=2025)
    assert passages[0].source_year == 2025


def test_limit_must_be_positive():
    with pytest.raises(ValueError, match="dương"):
        chunk("a", max_chars=0)
