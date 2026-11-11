"""Giá trị slot có trong câu trả lời chữ (spec §4.1, sửa lần ba)."""

from qnuchat.eval.metrics.answer_text import value_in_text
from qnuchat.eval.schema import ExpectedSlot


def slot(value: str, *synonyms: str, unit: str | None = None) -> ExpectedSlot:
    return ExpectedSlot(
        subject="ngành CNTT", predicate="p", value=value, unit=unit, admission_year=2025,
        value_synonyms=list(synonyms),
    )


def test_number_with_unit_and_sentence_period():
    assert value_in_text("Ngành có tổng cộng 138 tín chỉ.", slot("138", unit="tín chỉ"))


def test_vietnamese_decimal_comma_matches_gold_with_comma():
    assert value_in_text("Thời gian đào tạo là 4,5 năm.", slot("4,5", unit="năm"))


def test_short_number_does_not_match_inside_a_decimal():
    assert not value_in_text("Thời gian đào tạo là 4,5 năm.", slot("4", unit="năm"))


def test_number_does_not_match_inside_a_longer_number():
    assert not value_in_text("Có 1380 sinh viên.", slot("138"))
    assert not value_in_text("Học phí 15.000.000 đồng.", slot("15"))


def test_thousands_dots_are_normalised_on_both_sides():
    assert value_in_text("Học phí 15.000.000 đồng.", slot("15000000"))


def test_text_value_ignores_case_and_punctuation():
    assert value_in_text("Có hai chuyên ngành: Kinh tế đầu tư, Kinh tế phát triển.",
                         slot("Kinh tế đầu tư"))
    assert value_in_text("Ngành Báo chí - Truyền thông", slot("Báo chí – Truyền thông"))


def test_text_value_must_be_contiguous_tokens():
    assert not value_in_text("Kinh tế và đầu tư", slot("Kinh tế đầu tư"))


def test_value_synonym_counts():
    assert value_in_text("Tốt nghiệp được cấp bằng cử nhân.", slot("Cử nhân", "bằng cử nhân"))
    assert value_in_text("Học phí mười lăm triệu.", slot("15", "mười lăm"))


def test_missing_value_is_false():
    assert not value_in_text("Tài liệu chưa có thông tin này.", slot("138"))
