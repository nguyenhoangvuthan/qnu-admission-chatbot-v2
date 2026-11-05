"""Chia trang thành passage. Đơn vị là một trang PDF; trang quá dài được tách tới khi đủ ngắn."""

from qnuchat.documents import Page, Passage

MAX_CHARS = 1500


def _split_at_boundary_near_middle(text: str) -> tuple[str, str]:
    """Tách tại ranh giới gần điểm giữa nhất, theo thứ tự: \\n\\n, \\n, sau đó giữa.

    Lý do: PyMuPDF phát ra single newlines (\\n), không paragraph breaks (\\n\\n).
    Đo được: 0/103 trang có \\n\\n; 103/103 có \\n. Tách tại newline để tránh cắt
    giữa từ, giúp embedding của dense retrieval không bị giảm chất lượng.
    """
    middle = len(text) // 2
    for sep in ["\n\n", "\n"]:
        boundaries = []
        start = text.find(sep)
        while start != -1:
            boundaries.append(start)
            start = text.find(sep, start + 1)
        if boundaries:
            best = min(boundaries, key=lambda b: abs(b - middle))
            return text[:best], text[best + len(sep) :]
    return text[:middle], text[middle:]


def _split_to_limit(text: str, max_chars: int) -> list[str]:
    """Tách đệ quy tới khi mọi phần không vượt `max_chars`; phần rỗng bị bỏ, thứ tự được giữ."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    head, tail = _split_at_boundary_near_middle(text)
    return [*_split_to_limit(head, max_chars), *_split_to_limit(tail, max_chars)]


def chunk_pages(
    pages: list[Page],
    *,
    source_id: str,
    max_chars: int = MAX_CHARS,
    source_year: int | None = None,
) -> list[Passage]:
    """Sinh `chunk_id` dạng `<source_id>:p001` hoặc `<source_id>:p001-2` khi trang bị tách.

    ID không chứa phiên bản nội dung: model phải chép lại ID khi trích dẫn nên ID càng ngắn càng
    tốt. Phiên bản nguồn nằm trong Snapshot, và Trace ghi Snapshot của từng lượt.
    """
    if max_chars < 1:
        raise ValueError("max_chars phải dương")
    passages: list[Passage] = []
    for page in pages:
        parts = _split_to_limit(page.text, max_chars)
        code = f"{source_id}:p{page.page:03d}"
        for index, part in enumerate(parts, start=1):
            chunk_id = code if len(parts) == 1 else f"{code}-{index}"
            passages.append(Passage(chunk_id, source_id, page.page, part, source_year))
    return passages
