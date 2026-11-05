"""Đọc dòng chữ từ HTML và DOCX, cùng cách đánh số dòng mà gold tham chiếu."""

from html.parser import HTMLParser

_BLOCK = {"p", "tr", "li", "br", "h1", "h2", "h3", "h4", "div", "table"}


class _ArticleText(HTMLParser):
    """Chữ trong div.chitietbaiviet (nội dung bài trên site trường), bỏ menu và chân trang."""

    def __init__(self):
        super().__init__()
        self.depth = 0  # > 0 khi đang ở trong bài
        self.lines: list[str] = []
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if not self.depth:
            classes = (dict(attrs).get("class") or "").split()
            if tag == "div" and "chitietbaiviet" in classes:
                self.depth = 1
            return
        if tag == "div":
            self.depth += 1
        if tag in _BLOCK:
            self.flush()

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag in ("td", "th"):
            self._buf.append(" | ")
        if tag in _BLOCK:
            self.flush()
        if tag == "div":
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self._buf.append(data)

    def flush(self):
        line = " ".join("".join(self._buf).split()).strip(" |")
        if line:
            self.lines.append(line)
        self._buf = []


def html_lines(html: str) -> list[str]:
    parser = _ArticleText()
    parser.feed(html)
    parser.flush()
    return parser.lines


def docx_lines(path) -> list[str]:
    """Đoạn văn rồi từng dòng bảng (ô nối bằng " | "), như đề xuất công nghệ §1."""
    import docx

    d = docx.Document(str(path))
    lines = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [" ".join(c.text.split()) for c in row.cells]
            line = " | ".join(c for c in cells if c)
            if line:
                lines.append(line)
    return lines
