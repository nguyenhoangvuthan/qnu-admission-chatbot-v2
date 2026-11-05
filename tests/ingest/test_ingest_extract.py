import io
import logging

import docx
import openpyxl
import pymupdf
import pytest
from PIL import Image

from qnuchat.ingest.extract import (
    ExtractError,
    extract,
    extract_docx,
    extract_html,
    extract_pdf,
    extract_xlsx,
    image_size,
    sniff,
    table_to_markdown,
)

TEXT = (
    "Thong bao tuyen sinh dai hoc chinh quy nam 2026 cua Truong Dai hoc Quy Nhon, xet tuyen dot 1."
)


def png(width=300, height=300) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def pdf_with_text() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), TEXT, fontsize=10)
    return doc.tobytes()


def pdf_scanned_second_page() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), TEXT, fontsize=10)
    page = doc.new_page()
    page.insert_image(page.rect, stream=png())
    return doc.tobytes()


def docx_bytes() -> bytes:
    document = docx.Document()
    document.add_paragraph("Học phí năm học 2026-2027")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Ngành", "Học phí"
    table.cell(1, 0).text, table.cell(1, 1).text = "Sư phạm Toán", "0"
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def xlsx_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Chỉ tiêu"
    sheet.append(["Mã ngành", "Tên ngành", "Chỉ tiêu"])
    sheet.append(["7480201", "Công nghệ thông tin", 200])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def test_sniff_by_content_not_by_name():
    assert sniff(pdf_with_text()) == "pdf"
    assert sniff(docx_bytes()) == "docx"
    assert sniff(xlsx_bytes()) == "xlsx"
    assert sniff(png()) == "image"
    assert sniff("﻿<!DOCTYPE html><html>lỗi</html>".encode()) == "html"
    assert sniff(b"\x00\x01garbage") == "unknown"


def test_binary_blob_containing_html_text_is_not_html():
    assert sniff(b"\x00\x01\x02<html>" + b"\x00" * 20) == "unknown"
    assert sniff(b"\x89BLOB" + b"\x00" * 8 + b"<!doctype html>") == "unknown"


def test_html_after_whitespace_and_bom_is_html():
    assert sniff(b"\xef\xbb\xbf  \r\n<!DOCTYPE html><p>x") == "html"
    assert sniff("<HTML><body>Tuyển sinh".encode()) == "html"
    assert sniff("<html>é".encode("latin-1")) == "html"


def test_image_size():
    assert image_size(png(320, 240)) == (320, 240)


def test_table_to_markdown_pads_rows_and_escapes_pipes():
    md = table_to_markdown([["Ngành", "Điểm"], ["A|B"], ["", ""]])
    assert md.splitlines() == ["| Ngành | Điểm |", "|---|---|", "| A\\|B |  |"]


def test_html_tables_become_markdown_and_blocks_become_lines():
    html = (
        "<div><h3>Điểm chuẩn</h3><p>Năm 2026.</p><table><tr><th>Ngành</th><th>Điểm</th></tr>"
        "<tr><td>CNTT</td><td>24,5</td></tr></table><p>Hết.</p></div>"
    )
    result = extract_html(html)
    assert result.tables == [[["Ngành", "Điểm"], ["CNTT", "24,5"]]]
    assert "| CNTT | 24,5 |" in result.text
    lines = result.text.splitlines()
    assert lines[0] == "Điểm chuẩn" and lines[1] == "Năm 2026." and lines[-1] == "Hết."


def test_pdf_with_text_layer_has_no_scanned_pages():
    result = extract_pdf(pdf_with_text())
    assert result.scanned_pages == [] and "Quy Nhon" in result.text and len(result.pages) == 1


def test_pdf_page_without_text_is_marked_scanned():
    assert extract_pdf(pdf_scanned_second_page()).scanned_pages == [2]


def test_broken_pdf_raises_extract_error():
    with pytest.raises(ExtractError):
        extract_pdf(b"%PDF-1.7 broken")


def test_docx_paragraphs_and_tables():
    result = extract_docx(docx_bytes())
    assert "Học phí năm học 2026-2027" in result.text
    assert result.tables == [[["Ngành", "Học phí"], ["Sư phạm Toán", "0"]]]


def test_xlsx_sheets_become_tables():
    result = extract_xlsx(xlsx_bytes())
    assert result.tables == [
        [["Mã ngành", "Tên ngành", "Chỉ tiêu"], ["7480201", "Công nghệ thông tin", "200"]]
    ]
    assert "## Chỉ tiêu" in result.text


def test_extract_dispatches_and_refuses_unknown_kinds():
    assert extract("docx", docx_bytes()).tables
    with pytest.raises(ExtractError):
        extract("image", png())


def test_docx_table_keeps_raw_pipe_in_tables_and_escapes_only_markdown():
    document = docx.Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Ngành", "Ghi chú"
    table.cell(1, 0).text, table.cell(1, 1).text = "A|B", "x"
    out = io.BytesIO()
    document.save(out)
    result = extract_docx(out.getvalue())
    assert result.tables[0][1][0] == "A|B"
    assert "| A\\|B | x |" in result.text


def test_xlsx_cell_keeps_raw_pipe_in_tables_and_escapes_only_markdown():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Ngành", "Ghi chú"])
    sheet.append(["A|B", "x"])
    out = io.BytesIO()
    workbook.save(out)
    result = extract_xlsx(out.getvalue())
    assert result.tables[0][1][0] == "A|B"
    assert "| A\\|B | x |" in result.text


def test_xlsx_date_cells_are_written_dd_mm_yyyy():
    import datetime as dt

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    stamp = dt.datetime(2005, 12, 31, 8, 30)
    sheet.append(["Nguyễn Văn An", dt.date(2006, 2, 1), stamp])
    out = io.BytesIO()
    workbook.save(out)
    result = extract_xlsx(out.getvalue())
    assert result.tables == [[["Nguyễn Văn An", "01/02/2006", "31/12/2005"]]]
    assert "| Nguyễn Văn An | 01/02/2006 | 31/12/2005 |" in result.text


def test_pdf_cells_on_one_visual_line_stay_on_one_line():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Danh sach lop K49A, Truong Dai hoc Quy Nhon", fontsize=10)
    rows = [("Nguyen Van An", "01/02/2006"), ("Le Van Ba", "02/02/2006")]
    for number, (name, day) in enumerate(rows):
        y = 100 + 18 * number
        page.insert_text((72, y), str(number + 1), fontsize=10)
        page.insert_text((110, y), name, fontsize=10)
        page.insert_text((300, y + 1), day, fontsize=10)  # lệch 1 pt vẫn cùng dòng
    result = extract_pdf(doc.tobytes())
    assert result.text.splitlines() == [
        "Danh sach lop K49A, Truong Dai hoc Quy Nhon",
        "1 | Nguyen Van An | 01/02/2006",
        "2 | Le Van Ba | 02/02/2006",
    ]
    assert result.scanned_pages == []


@pytest.mark.parametrize(
    "fragment",
    ["", "   ", "<html><head><title>x</title></head></html>", "<!-- chỉ có comment -->"],
)
def test_odd_html_fragments_give_empty_text_without_raising(fragment):
    result = extract_html(fragment)
    assert result.text == "" and result.tables == []


def test_inline_text_before_a_block_child_starts_a_new_line():
    assert extract_html("<div>Intro<p>Body</p></div>").text == "Intro\nBody"


def test_find_tables_failure_is_logged_not_swallowed(monkeypatch, caplog):
    def boom(self, *args, **kwargs):
        raise RuntimeError("bảng hỏng")

    monkeypatch.setattr(pymupdf.Page, "find_tables", boom)
    # tests/arch chạy import-linter, nó dựng lại logging và tắt logger đã có: bật lại cho test
    monkeypatch.setattr(logging.getLogger("qnuchat.ingest.extract"), "disabled", False)
    with caplog.at_level("WARNING", logger="qnuchat.ingest.extract"):
        result = extract_pdf(pdf_with_text())
    assert "Quy Nhon" in result.text and result.tables == []
    assert "pdf_find_tables_failed page=1" in caplog.text


def test_docx_text_keeps_paragraph_and_table_order():
    document = docx.Document()
    document.add_paragraph("Đoạn một")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Ngành"
    table.rows[0].cells[1].text = "Chỉ tiêu"
    document.add_paragraph("Đoạn hai")
    out = io.BytesIO()
    document.save(out)
    lines = extract_docx(out.getvalue()).text.splitlines()
    assert lines.index("Đoạn một") < lines.index("| Ngành | Chỉ tiêu |") < lines.index("Đoạn hai")
