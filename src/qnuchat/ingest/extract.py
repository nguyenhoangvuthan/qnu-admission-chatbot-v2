"""Trích text lớp chữ (không OCR): HTML khung nội dung, PDF, DOCX, XLSX;
nhận dạng loại file theo nội dung (spec §7.1). Trang PDF gần như không có chữ được đánh dấu
`scanned_pages` để OCR ở Plan 2.

Không chạy model nào nên chạy CPU (spec W7).
"""

import io
import itertools
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import docx
import lxml.etree
import lxml.html
import openpyxl
import pymupdf
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image, UnidentifiedImageError

pymupdf.no_recommend_layout()  # tắt banner "Consider using the pymupdf_layout package…" ra stdout
logger = logging.getLogger(__name__)

SCANNED_MIN_CHARS = 50
# Dòng nhìn thấy của PDF: chữ có đáy lệch nhau ≤ 3 pt là cùng một dòng; khoảng trống giữa hai
# chữ rộng hơn chiều cao chữ coi là ranh giới ô (bảng không kẻ khung).
LINE_TOLERANCE_PT = 3.0
_BLOCK = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "section",
        "article",
        "ul",
        "ol",
        "pre",
        "blockquote",
    }
)
_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html",
}

Kind = Literal["pdf", "docx", "xlsx", "image", "html", "unknown"]


class ExtractError(Exception):
    pass


@dataclass(frozen=True)
class Extracted:
    text: str
    pages: list[str] | None
    tables: list[list[list[str]]]
    scanned_pages: list[int]


def sniff(data: bytes) -> Kind:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        return "unknown"
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    if b"\x00" not in head:
        try:
            text = head.decode("utf-8")
        except UnicodeDecodeError:
            text = head.decode("latin-1")
        text = text.lower()
        if "<html" in text or "<!doctype html" in text:
            return "html"
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        return "image"
    except (UnidentifiedImageError, OSError, ValueError):
        return "unknown"


def mime_of(data: bytes, kind: str) -> str:
    if kind == "image":
        with Image.open(io.BytesIO(data)) as img:
            return f"image/{(img.format or 'octet-stream').lower()}"
    return _MIME.get(kind, "application/octet-stream")


def image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def _text(value) -> str:
    if isinstance(value, datetime | date):
        # openpyxl đọc ô ngày thành datetime: viết kiểu Việt Nam để luật ngày sinh (W3) nhận ra.
        return value.strftime("%d/%m/%Y")
    return " ".join(str(value if value is not None else "").split())


def _cell(value) -> str:
    return _text(value).replace("|", "\\|")


def table_to_markdown(rows: list[list[str]]) -> str:
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [[_cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(lines)


def _clean(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


_EMPTY = Extracted(text="", pages=None, tables=[], scanned_pages=[])


def extract_html(main_html: str) -> Extracted:
    if not main_html.strip():
        return _EMPTY
    try:
        root = lxml.html.fragment_fromstring(main_html, create_parent="div")
    except (lxml.etree.ParserError, AssertionError, ValueError):
        # Mảnh lạ (cả tài liệu chỉ có <head>, chỉ có comment…): không có chữ nào để lọc hay lưu.
        return _EMPTY
    tables: list[list[list[str]]] = []
    top_level = [
        t for t in root.iter("table") if not any(a.tag == "table" for a in t.iterancestors())
    ]
    for table in top_level:
        rows = [
            [" ".join(cell.text_content().split()) for cell in tr.xpath("./th|./td")]
            for tr in table.xpath(".//tr")
        ]
        rows = [r for r in rows if r]
        tables.append(rows)
        block = lxml.html.Element("pre")
        block.text = "\n" + table_to_markdown(rows) + "\n"
        block.tail = table.tail
        table.getparent().replace(table, block)
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag in _BLOCK:
            element.tail = "\n" + (element.tail or "")
            _break_before(element)
    return Extracted(text=_clean(root.text_content()), pages=None, tables=tables, scanned_pages=[])


def _break_before(element) -> None:
    """Xuống dòng trước phần tử khối nếu ngay trước nó còn chữ chưa kết thúc dòng
    (`<div>Intro<p>Body</p></div>`); không thêm dòng trống khi đã ở đầu dòng."""
    previous = element.getprevious()
    if previous is not None:
        if not (previous.tail or "").rstrip(" \t").endswith("\n"):
            previous.tail = (previous.tail or "") + "\n"
        return
    parent = element.getparent()
    if parent is not None:
        text = (parent.text or "").rstrip(" \t")
        if text and not text.endswith("\n"):
            parent.text = parent.text + "\n"


def extract_pdf(data: bytes) -> Extracted:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # pymupdf ném nhiều kiểu lỗi khác nhau cho file hỏng
        raise ExtractError(f"PDF không mở được: {exc}") from exc
    if doc.page_count == 0:
        doc.close()
        raise ExtractError("PDF không có trang nào (file hỏng)")
    pages: list[str] = []
    tables: list[list[list[str]]] = []
    scanned: list[int] = []
    with doc:
        for number, page in enumerate(doc, start=1):
            text = _visual_text(page)
            if sum(ch.isalnum() for ch in text) < SCANNED_MIN_CHARS:
                scanned.append(number)
            pages.append(_clean(text))
            try:
                found = page.find_tables()
            # find_tables hỏng trên trang vẽ lạ: bỏ bảng, giữ text, ghi cảnh báo
            except Exception as exc:  # noqa: BLE001
                logger.warning("pdf_find_tables_failed page=%d: %s", number, exc)
                continue
            for table in found.tables:
                tables.append([[_text(c) for c in row] for row in table.extract()])
    return Extracted(
        text="\n\n".join(p for p in pages if p), pages=pages, tables=tables, scanned_pages=scanned
    )


def _visual_text(page) -> str:
    """Text của trang theo dòng nhìn thấy: bảng không kẻ khung đặt mỗi ô một khối riêng nên
    `get_text("text")` tách họ tên và ngày sinh ra hai dòng; ở đây chúng nằm chung một dòng,
    ô cách nhau bằng " | "."""
    words = sorted(page.get_text("words"), key=lambda w: (w[3], w[0]))
    lines: list[list[tuple]] = []
    for word in words:
        if lines and word[3] - lines[-1][0][3] <= LINE_TOLERANCE_PT:
            lines[-1].append(word)
        else:
            lines.append([word])
    out: list[str] = []
    for line in lines:
        line.sort(key=lambda w: w[0])
        parts = [line[0][4]]
        for prev, word in itertools.pairwise(line):
            gap = word[0] - prev[2]
            parts.append(" | " if gap > (prev[3] - prev[1]) else " ")
            parts.append(word[4])
        out.append("".join(parts))
    return "\n".join(out)


def extract_docx(data: bytes) -> Extracted:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ExtractError(f"DOCX không mở được: {exc}") from exc
    tables: list[list[list[str]]] = []
    parts: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            parts.append(Paragraph(child, document).text)
        elif child.tag == qn("w:tbl"):
            table = [[_text(c.text) for c in row.cells] for row in Table(child, document).rows]
            tables.append(table)
            parts.append(table_to_markdown(table))
    return Extracted(text=_clean("\n".join(parts)), pages=None, tables=tables, scanned_pages=[])


def extract_xlsx(data: bytes) -> Extracted:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ExtractError(f"XLSX không mở được: {exc}") from exc
    tables: list[list[list[str]]] = []
    parts: list[str] = []
    for sheet in workbook.worksheets:
        rows = [[_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        tables.append(rows)
        parts += [f"## {sheet.title}", table_to_markdown(rows)]
    workbook.close()
    return Extracted(text=_clean("\n".join(parts)), pages=None, tables=tables, scanned_pages=[])


def extract(kind: str, data: bytes) -> Extracted:
    if kind == "pdf":
        return extract_pdf(data)
    if kind == "docx":
        return extract_docx(data)
    if kind == "xlsx":
        return extract_xlsx(data)
    raise ExtractError(f"không trích được loại {kind!r}")
