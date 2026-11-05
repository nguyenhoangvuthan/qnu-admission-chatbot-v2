import datetime as dt
import io
import unicodedata
from datetime import date

import openpyxl
import pymupdf
import pytest

from qnuchat.ingest.extract import Extracted, extract_pdf, extract_xlsx
from qnuchat.ingest.pii import _has_name, detect, header_concepts, title_skip

TODAY = date(2026, 10, 12)
PATTERNS = ["danh sách (sinh viên|thí sinh|học viên)", "khen thưởng"]


def ex(text="", tables=()):
    return Extracted(text=text, pages=None, tables=list(tables), scanned_pages=[])


@pytest.mark.parametrize(
    "title", ["Danh sách thí sinh trúng tuyển đợt 1", "QĐ khen thưởng sinh viên năm học 2025-2026"]
)
def test_titles_that_announce_people_lists_are_skipped(title):
    assert title_skip(title, PATTERNS) is not None


@pytest.mark.parametrize("title", ["Danh sách ngành đào tạo 2026", "TB141 - Điểm chuẩn năm 2026"])
def test_other_titles_pass(title):
    assert title_skip(title, PATTERNS) is None


def test_header_with_name_and_birth_date_is_a_people_list():
    table = [
        ["STT", "Họ và tên", "Ngày sinh", "Ngành trúng tuyển"],
        ["1", "Nguyễn Văn A", "01/02/2008", "CNTT"],
    ]
    assert detect(ex(tables=[table]), today=TODAY) == "header:ho_ten+ngay_sinh"


def test_header_on_the_second_row_is_also_checked():
    table = [["DANH SÁCH", "", ""], ["SBD", "Họ tên", "Lớp"], ["37012345", "Trần B", "12A1"]]
    assert detect(ex(tables=[table]), today=TODAY) == "header:ho_ten+lop+sbd"


@pytest.mark.parametrize(
    "header",
    [
        ["STT", "Mã ngành", "Tên ngành", "Chỉ tiêu"],
        ["Mã ngành", "Tên ngành", "Tổ hợp", "Điểm chuẩn"],
        ["Tổ hợp", "Môn 1", "Môn 2", "Môn 3"],
        ["Lớp", "Phòng", "Giờ"],
        ["Đơn vị", "Điện thoại", "Email"],
    ],
)
def test_admission_tables_are_not_people_lists(header):
    assert len(header_concepts(header)) < 2
    assert detect(ex(tables=[header, ["x"] * len(header)]), today=TODAY) is None


def test_five_rows_of_names_with_birth_dates_are_a_people_list():
    rows = "\n".join(
        f"| {i} | Nguyễn Thị Hoa{i} | 0{i}/03/2008 | Sư phạm Toán |" for i in range(1, 6)
    )
    rows = (
        rows.replace("Hoa1", "Hoa")
        .replace("Hoa2", "Lan")
        .replace("Hoa3", "Mai")
        .replace("Hoa4", "Cúc")
        .replace("Hoa5", "Đào")
    )
    assert detect(ex(text=rows), today=TODAY) == "rows"


def test_uppercase_names_with_student_ids_count():
    rows = "\n".join(f"{i}. NGUYỄN VĂN AN 46510{i}0123 K49" for i in range(1, 6))
    assert detect(ex(text=rows), today=TODAY) == "rows"


def test_exam_schedule_with_current_dates_is_not_a_people_list():
    rows = "\n".join(f"| Ngữ Văn | {d}/06/2026 |" for d in range(10, 16))
    assert detect(ex(text=rows), today=TODAY) is None


def test_tuition_table_with_round_amounts_is_not_a_people_list():
    rows = "\n".join(f"| Công Nghệ Thông Tin | 1{i}500000 |" for i in range(6))
    assert detect(ex(text=rows), today=TODAY) is None


def test_four_people_rows_are_below_the_threshold():
    rows = "\n".join(f"| Nguyễn Văn An | 0{i}/03/2008 |" for i in range(1, 5))
    assert detect(ex(text=rows), today=TODAY) is None


def test_nfd_decomposed_names_are_still_a_people_list():
    rows = "\n".join(f"| Nguyễn Thị Hoa{i} | 0{i}/03/2008 |" for i in range(1, 7))
    rows_nfd = unicodedata.normalize("NFD", rows)
    assert rows_nfd != rows
    assert detect(ex(text=rows_nfd), today=TODAY) == "rows"


def test_faculty_rows_with_phone_like_numbers_are_not_a_people_list():
    faculties = ["Công Nghệ Thông Tin", "Kinh Tế", "Sư Phạm Toán", "Ngoại Ngữ", "Y Dược"]
    rows = "\n".join(f"| Khoa {name} | 02563840156 |" for name in faculties)
    assert detect(ex(text=rows), today=TODAY) is None


def test_five_rows_of_names_with_12_digit_cccd_are_a_people_list():
    rows = "\n".join("| Trần Văn Bình | 052203001234 |" for _ in range(5))
    assert detect(ex(text=rows), today=TODAY) == "rows"


# ---------------------------------------------------------------- hình dạng thật (review cuối)


def _xlsx(rows) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


_TITLE_ROWS = [["TRƯỜNG ĐẠI HỌC QUY NHƠN"], ["DANH SÁCH SINH VIÊN LỚP K49"], []]
_NAMES = ["Nguyễn Văn An", "Trần Thị Bình", "Lê Văn Cường", "Phạm Thị Dung", "Hoàng Văn Em"]
_NAMES += ["Võ Thị Giang"]


def test_xlsx_header_below_three_title_rows_with_real_dates_is_a_people_list():
    rows = _TITLE_ROWS + [["Họ và tên", "Ngày sinh", "Lớp"]]
    rows += [[name, dt.date(2006, 2, i + 1), "K49A"] for i, name in enumerate(_NAMES)]
    assert detect(extract_xlsx(_xlsx(rows)), today=TODAY) == "header:ho_ten+lop+ngay_sinh"


def test_xlsx_staff_directory_with_name_and_phone_header_is_a_people_list():
    rows = [["TRƯỜNG ĐẠI HỌC QUY NHƠN"], ["DANH BẠ CÁN BỘ PHÒNG ĐÀO TẠO"], []]
    rows += [["Họ và tên", "Chức vụ", "Số điện thoại"]]
    rows += [[name, "Chuyên viên", f"090512345{i}"] for i, name in enumerate(_NAMES)]
    assert detect(extract_xlsx(_xlsx(rows)), today=TODAY) == "header:ho_ten+sdt"


def test_header_is_looked_for_in_the_first_ten_rows():
    table = [[f"tiêu đề {i}", ""] for i in range(9)] + [["Họ tên", "SBD"], ["Trần B", "37012345"]]
    assert detect(ex(tables=[table]), today=TODAY) == "header:ho_ten+sbd"


def test_xlsx_without_header_but_names_and_date_cells_is_a_people_list():
    rows = [[i + 1, name, dt.date(2006, 3, i + 1)] for i, name in enumerate(_NAMES)]
    assert detect(extract_xlsx(_xlsx(rows)), today=TODAY) == "rows"


def test_table_rows_without_header_are_checked_by_the_row_rule():
    table = [[str(i + 1), name, f"0{i + 1}/02/2006"] for i, name in enumerate(_NAMES)]
    assert detect(ex(tables=[table]), today=TODAY) == "rows"


def _borderless_pdf(rows) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for number, cells in enumerate(rows):
        y = 100 + 18 * number
        for x, cell in zip((72, 110, 300, 420), cells, strict=False):
            page.insert_text((x, y), cell, fontsize=10)
    return doc.tobytes()


def test_borderless_pdf_table_of_names_and_birth_dates_is_a_people_list():
    names = ["Nguyen Van An", "Tran Thi Binh", "Le Van Cuong", "Pham Thi Dung", "Hoang Van Em"]
    names += ["Vo Thi Giang"]
    rows = [[str(i + 1), name, f"0{i + 1}/02/2006", "K49A"] for i, name in enumerate(names)]
    assert detect(extract_pdf(_borderless_pdf(rows)), today=TODAY) == "rows"


@pytest.mark.parametrize(
    "table",
    [
        [["7480201", "Công Nghệ Thông Tin", "200"]] * 6,
        [["Công Nghệ Thông Tin", f"1{i}500000"] for i in range(6)],
        [["Ngữ Văn", f"{d}/06/2026"] for d in range(10, 16)],
        [["Khoa Công Nghệ Thông Tin", "02563840156"]] * 6,
        [["Mã Ngành", "Tên Ngành", "Tổ Hợp", "Điểm Chuẩn"]]
        + [["7140209", "Sư Phạm Toán", "A00", "24,5"]] * 6,
    ],
)
def test_admission_tables_are_not_people_lists_by_rows_either(table):
    assert detect(ex(tables=[table]), today=TODAY) is None


def test_xlsx_admission_sheet_with_title_rows_is_not_a_people_list():
    rows = [["TRƯỜNG ĐẠI HỌC QUY NHƠN"], ["CHỈ TIÊU TUYỂN SINH 2026"], []]
    rows += [["Mã ngành", "Tên ngành", "Tổ hợp", "Chỉ tiêu"]]
    rows += [["7480201", "Công Nghệ Thông Tin", "A00", 200]] * 6
    assert detect(extract_xlsx(_xlsx(rows)), today=TODAY) is None


def test_name_only_header_with_name_cells_is_a_people_list():
    table = [["STT", "Họ và tên", "Điểm"]] + [
        [str(i + 1), name, "8,5"] for i, name in enumerate(_NAMES[:3])
    ]
    assert detect(ex(tables=[table]), today=TODAY) == "header:ho_ten"


def test_name_only_header_with_two_data_rows_is_below_the_threshold():
    table = [["STT", "Họ và tên", "Điểm"]] + [
        [str(i + 1), name, "8,5"] for i, name in enumerate(_NAMES[:2])
    ]
    assert detect(ex(tables=[table]), today=TODAY) is None


def test_name_only_header_with_non_name_cells_is_not_a_people_list():
    table = [["Họ tên", "Ghi chú"]] + [["Không", "ghi"], ["12", "x"], ["", "y"], ["7480201", "z"]]
    assert detect(ex(tables=[table]), today=TODAY) is None


def test_markdown_escaped_pipe_does_not_break_name_tokens():
    rows = "\n".join(f"| {i} | Lê Văn\\| 0{i}/02/2006 |" for i in range(1, 6))
    assert detect(ex(text=rows), today=TODAY) == "rows"


@pytest.mark.parametrize("amount", ["15750500", "12345678", "9876543210"])
def test_tuition_table_with_irregular_amounts_is_not_a_people_list(amount):
    table = [["Ngành Công Nghệ Thông Tin", amount]] * 6
    assert detect(ex(tables=[table]), today=TODAY) is None
    assert (
        detect(
            ex(text="\n".join(f"| Công Nghệ Thông Tin | {amount} |" for _ in range(6))), today=TODAY
        )
        is None
    )


def test_person_in_another_cell_is_still_found_after_an_organisation_phrase():
    rows = "\n".join(f"| Ngành Công Nghệ | Lê Văn Nam | 0{i}/02/2006 |" for i in range(1, 6))
    assert detect(ex(text=rows), today=TODAY) == "rows"


def test_organisation_phrases_are_excused_but_plain_names_are_not():
    for phrase in ("Khoa Công Nghệ Thông Tin", "Phòng Đào Tạo", "Trường Đại Học Quy Nhơn"):
        assert not _has_name(phrase)
    for phrase in ("Nguyễn Văn An", "TRẦN THỊ BÌNH", "Lê Công Minh"):
        assert _has_name(phrase)


@pytest.mark.parametrize(
    "name",
    [
        "Đoàn Văn Hậu",
        "ĐOÀN THỊ LAN",
        "Văn Thị Hoa",
        "Y Bhiu Niê",
        "Đoàn Thanh Hải",
        "ĐOÀN THANH BÌNH",
    ],
)
def test_surnames_doan_van_y_are_names(name):
    assert _has_name(name)


@pytest.mark.parametrize(
    "phrase",
    [
        "Văn học",
        "Văn Học",
        "Văn hóa du lịch",
        "Đoàn Thanh niên",
        "ĐOÀN THANH NIÊN",
        "Đoàn thanh niên",
        "Y khoa",
        "Y Dược",
    ],
)
def test_organisation_pairs_are_not_names(phrase):
    assert not _has_name(phrase)


def test_people_list_with_a_doan_row_is_still_found():
    rows = [f"| Nguyễn Văn An | 0{i}/02/2008 |" for i in range(1, 3)]
    rows += ["| Đoàn Văn Hậu | 01/02/2008 |"]
    rows += [f"| Lê Thị Bình | 0{i}/02/2008 |" for i in range(4, 6)]
    assert detect(ex(text="\n".join(rows)), today=TODAY) == "rows"


def test_name_only_header_with_doan_van_y_names_is_caught():
    table = [["Họ và tên"], ["Đoàn Văn Hậu"], ["Văn Thị Hoa"], ["Y Bhiu Niê"]]
    assert detect(ex(tables=[table]), today=TODAY) == "header:ho_ten"


def test_people_list_with_a_doan_thanh_row_is_still_found():
    rows = [f"| Nguyễn Văn An | 0{i}/02/2008 |" for i in range(1, 3)]
    rows += ["| Đoàn Thanh Hải | 03/04/2008 |"]
    rows += [f"| Lê Thị Bình | 0{i}/02/2008 |" for i in range(4, 6)]
    assert detect(ex(text="\n".join(rows)), today=TODAY) == "rows"
