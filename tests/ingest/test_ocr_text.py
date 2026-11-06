from qnuchat.ingest.ocr.text import fix_combo_codes, group_rows, page_text


def line(text, x0, y0, x1, y1):
    return {"text": text, "box": [x0, y0, x1, y1]}


def test_fix_combo_codes_turns_letter_o_into_zero_inside_codes_only():
    assert fix_combo_codes("DO1, BOO, coo") == "D01, B00, C00"
    assert fix_combo_codes("HOC phí 2025") == "HOC phí 2025"


def test_rows_join_cells_of_one_visual_row_left_to_right():
    rows = group_rows(
        [
            line("Nguyễn Văn An", 300, 100, 500, 130),
            line("1", 100, 102, 120, 128),
            line("01/02/2005", 600, 105, 700, 132),
            line("Trần Thị Bình", 300, 150, 500, 180),
        ]
    )
    assert rows == [["1", "Nguyễn Văn An", "01/02/2005"], ["Trần Thị Bình"]]


def test_rows_fix_combo_codes_and_render_like_a_text_layer():
    rows = group_rows([line("DO1", 0, 0, 50, 20), line("Toán", 60, 0, 100, 20)])
    assert page_text(rows) == "D01 | Toán"
