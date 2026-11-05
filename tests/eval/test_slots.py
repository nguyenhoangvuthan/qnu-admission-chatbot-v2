import pytest

from qnuchat.core.contracts import Claim
from qnuchat.eval.metrics.slots import key_fact_accuracy, normalise_value, slot_matches
from qnuchat.eval.schema import ExpectedSlot, ScoredAnswer


def slot(value: str, unit: str | None = "điểm") -> ExpectedSlot:
    return ExpectedSlot(
        subject="ngành CNTT", predicate="điểm chuẩn",
        value=value, unit=unit, admission_year=2025,
    )


def claim(value: str, unit: str | None = "điểm") -> Claim:
    return Claim(
        subject="ngành CNTT", predicate="điểm chuẩn",
        value=value, unit=unit, admission_year=2025,
    )


def answer_with(*claims: Claim) -> ScoredAnswer:
    return ScoredAnswer(abstain=False, claims=list(claims), confidence=0.9)


def test_decimal_comma_and_dot_are_equivalent():
    assert normalise_value("22,5") == normalise_value("22.5")


def test_normalisation_collapses_whitespace_and_case():
    assert normalise_value("  22,5  Điểm ") == normalise_value("22.5 điểm")


def test_thousand_separators_are_removed():
    assert normalise_value("15.000.000") == normalise_value("15000000")


def test_exact_slot_match_is_true():
    assert slot_matches(claim("22,5"), slot("22.5")) is True


def test_wrong_value_is_absolute_failure():
    """22,5 và 24,5 gần nhau về chuỗi nhưng khiến thí sinh trượt — không có điểm bộ phận."""
    assert slot_matches(claim("24,5"), slot("22,5")) is False


def test_unit_mismatch_fails():
    assert slot_matches(claim("22,5", unit="triệu"), slot("22,5", unit="điểm")) is False


def test_accuracy_is_one_when_every_expected_slot_matched():
    assert key_fact_accuracy(answer_with(claim("22,5")), [slot("22,5")]) == 1.0


def test_accuracy_is_zero_when_one_of_two_slots_missing():
    result = key_fact_accuracy(answer_with(claim("22,5")), [slot("22,5"), slot("18,0")])
    assert result == pytest.approx(0.0)


def test_abstained_answer_scores_zero():
    abstained = ScoredAnswer(abstain=True, claims=[], confidence=0.1)
    assert key_fact_accuracy(abstained, [slot("22,5")]) == 0.0


def test_item_without_expected_slots_scores_one():
    assert key_fact_accuracy(answer_with(), []) == 1.0


def slot_for(subject: str, predicate: str, **kwargs) -> ExpectedSlot:
    return ExpectedSlot(
        subject=subject, predicate=predicate, value="22,5", unit="điểm",
        admission_year=2025, **kwargs,
    )


def claim_for(subject: str, predicate: str) -> Claim:
    return Claim(
        subject=subject, predicate=predicate, value="22,5", unit="điểm",
        admission_year=2025,
    )


def test_right_value_on_the_wrong_subject_is_not_a_match():
    """Hỏi điểm chuẩn CNTT, trả lời về ngành Luật cùng con số — phải là fail."""
    assert slot_matches(
        claim_for("ngành Luật", "điểm chuẩn"), slot_for("ngành CNTT", "điểm chuẩn")
    ) is False


def test_right_value_on_the_wrong_predicate_is_not_a_match():
    """Điểm sàn không phải điểm chuẩn, dù trùng giá trị."""
    assert slot_matches(
        claim_for("ngành CNTT", "điểm sàn"), slot_for("ngành CNTT", "điểm chuẩn")
    ) is False


def test_key_fact_accuracy_is_zero_for_answer_about_another_subject():
    wrong = answer_with(claim_for("ngành Luật", "điểm chuẩn"))
    assert key_fact_accuracy(wrong, [slot_for("ngành CNTT", "điểm chuẩn")]) == 0.0


def test_subject_prefix_nganh_is_optional():
    assert slot_matches(
        claim_for("Công nghệ thông tin", "điểm chuẩn"),
        slot_for("ngành Công nghệ thông tin", "điểm chuẩn"),
    ) is True


def test_nested_industry_name_is_not_a_match():
    """"Luật" ⊂ "Luật kinh tế" — khớp bao hàm sẽ chấm sai, phải khớp chính xác."""
    assert slot_matches(
        claim_for("ngành Luật kinh tế", "điểm chuẩn"), slot_for("ngành Luật", "điểm chuẩn")
    ) is False


def test_declared_predicate_synonym_matches():
    assert slot_matches(
        claim_for("ngành CNTT", "điểm trúng tuyển"),
        slot_for("ngành CNTT", "điểm chuẩn", predicate_synonyms=["điểm trúng tuyển"]),
    ) is True


def test_declared_subject_synonym_matches():
    assert slot_matches(
        claim_for("Công nghệ thông tin", "điểm chuẩn"),
        slot_for("ngành CNTT", "điểm chuẩn", subject_synonyms=["Công nghệ thông tin"]),
    ) is True


def test_entity_normalisation_ignores_case_spacing_and_trailing_punctuation():
    assert slot_matches(
        claim_for("  NGÀNH   cntt.", "Điểm  Chuẩn"), slot_for("ngành CNTT", "điểm chuẩn")
    ) is True


def test_explicit_value_aliases_do_not_relax_entity_identity():
    expected = ExpectedSlot(subject="Sư phạm Khoa học tự nhiên", predicate="cấp học",
                            value="THCS", value_synonyms=["trung học cơ sở"],
                            admission_year=2025)
    claim = Claim(subject="Sư phạm Khoa học tự nhiên", predicate="cấp học",
                  value="trung học cơ sở", admission_year=2025)
    assert slot_matches(claim, expected)
    assert not slot_matches(claim.model_copy(update={"subject": "Sư phạm Toán"}), expected)
    assert not slot_matches(claim.model_copy(update={"value": "THPT"}), expected)
