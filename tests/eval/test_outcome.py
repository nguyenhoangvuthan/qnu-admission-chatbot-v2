"""Nhóm kết quả của một câu (spec §4.1, plan Task 4)."""

from qnuchat.core.contracts import Claim
from qnuchat.eval.outcome import (
    classify,
    contradicts,
    critical_value_kind,
    incomplete_only_for_year,
)
from qnuchat.eval.schema import ExpectedSlot, GoldItem, ScoredAnswer


def slot(
    subject: str,
    predicate: str,
    value: str,
    unit: str | None = None,
    admission_year: int | None = 2025,
) -> ExpectedSlot:
    return ExpectedSlot(
        subject=subject, predicate=predicate, value=value, unit=unit,
        admission_year=admission_year,
    )


S = slot("ngành CNTT", "học phí", "15", "triệu đồng", 2025)
S2 = slot("ngành CNTT", "chỉ tiêu", "120", "chỉ tiêu", 2025)
A = slot("Kinh tế", "chuyên ngành", "Kinh tế đầu tư")  # V2-PIL-027, hai slot cùng subject+predicate
B = slot("Kinh tế", "chuyên ngành", "Kinh tế phát triển")

_UNSET = object()


def claim_of(
    s: ExpectedSlot,
    *,
    subject: str | None = None,
    value: str | None = None,
    admission_year: object = _UNSET,
) -> Claim:
    """Claim khớp đúng slot `s`, trừ trường được ghi đè."""
    return Claim(
        subject=subject if subject is not None else s.subject,
        predicate=s.predicate,
        value=value if value is not None else s.value,
        unit=s.unit,
        admission_year=s.admission_year if admission_year is _UNSET else admission_year,
    )


def item(slots: list[ExpectedSlot], must_abstain: bool = False) -> GoldItem:
    return GoldItem(
        id="Q1", question="Câu hỏi?", origin="curated", risk="normal",
        admission_year=2025, must_abstain=must_abstain, gold_page_ids=[],
        expected_slots=slots, required_conditions=[], forbidden_claims=[],
        source_family="fam", reviewer="",
    )


def answered(*claims: Claim) -> ScoredAnswer:
    return ScoredAnswer(abstain=False, claims=list(claims), confidence=0.9)


def abstained() -> ScoredAnswer:
    return ScoredAnswer(abstain=True, claims=[], confidence=0.1)


def test_all_slots_matched_is_correct():
    assert classify(item([S]), answered(claim_of(S))) == "correct"


def test_wrong_value_is_critical():
    assert classify(item([S]), answered(claim_of(S, value="16"))) == "critical_error"


def test_wrong_year_is_critical():
    assert classify(item([S]), answered(claim_of(S, admission_year=2024))) == "critical_error"


def test_missing_year_on_claim_is_not_critical_but_incomplete():
    assert classify(item([S]), answered(claim_of(S, admission_year=None))) == "incomplete"


def test_missing_slot_is_incomplete():
    assert classify(item([S, S2]), answered(claim_of(S))) == "incomplete"


def test_missing_and_wrong_is_critical():
    assert classify(item([S, S2]), answered(claim_of(S, value="16"))) == "critical_error"


def test_claim_about_other_subject_is_not_critical():
    assert classify(item([S]), answered(claim_of(S, subject="Luật", value="16"))) == "incomplete"


def test_one_right_one_wrong_claim_for_same_slot_is_critical():
    """Review Focus 4: ghim hành vi để Task 8 đọc tay có mốc so."""
    assert classify(item([S]), answered(claim_of(S), claim_of(S, value="18"))) == "critical_error"


def test_list_answer_with_shared_subject_and_predicate_is_correct():
    assert classify(item([A, B]), answered(claim_of(A), claim_of(B))) == "correct"


def test_list_answer_with_one_invented_item_is_critical():
    invented = claim_of(A, value="Kinh tế số")
    assert classify(item([A, B]), answered(claim_of(A), invented)) == "critical_error"


def test_claim_without_year_but_right_value_is_not_critical():
    assert not contradicts(claim_of(S, admission_year=None), [S])


def test_slot_without_year_does_not_make_claim_year_a_contradiction():
    no_year = slot("ngành CNTT", "học phí", "15", "triệu đồng", None)
    assert not contradicts(claim_of(S), [no_year])


def test_contradiction_uses_value_and_subject_synonyms():
    s = ExpectedSlot(
        subject="Công nghệ thông tin", predicate="học phí", value="15", unit="triệu đồng",
        admission_year=2025, subject_synonyms=["CNTT"], value_synonyms=["mười lăm"],
    )
    c = Claim(subject="ngành CNTT", predicate="học phí", value="mười lăm",
              unit="triệu đồng", admission_year=2025)
    assert not contradicts(c, [s])
    assert contradicts(c.model_copy(update={"value": "16"}), [s])


def test_unit_is_not_considered_for_contradiction():
    c = claim_of(S).model_copy(update={"unit": "đồng"})
    assert not contradicts(c, [S])


def test_no_slot_with_same_subject_and_predicate_is_not_contradiction():
    assert not contradicts(claim_of(S2), [S])


# --- chuẩn hoá thêm khi xét critical_error (sửa spec §4.1 lần hai) ------------

CREDITS = ExpectedSlot(
    subject="ngành CNTT", predicate="tổng số tín chỉ", value="138", unit="tín chỉ",
    admission_year=2025, unit_synonyms=["TC"],
)
DEGREE = slot("Ngôn ngữ Anh", "văn bằng", "Cử nhân")


def test_value_with_slot_unit_appended_is_not_critical_but_incomplete():
    c = claim_of(CREDITS, value="138 tín chỉ")
    assert not contradicts(c, [CREDITS])
    assert classify(item([CREDITS]), answered(c)) == "incomplete"


def test_value_with_unit_synonym_appended_is_not_critical():
    assert not contradicts(claim_of(CREDITS, value="138 TC"), [CREDITS])


def test_wrong_number_with_unit_appended_is_still_critical():
    assert contradicts(claim_of(CREDITS, value="140 tín chỉ"), [CREDITS])


def test_trailing_punctuation_is_not_critical():
    assert not contradicts(claim_of(CREDITS, value="138."), [CREDITS])
    assert not contradicts(claim_of(A, value="Kinh tế đầu tư."), [A, B])


def test_major_prefix_on_value_is_not_critical():
    assert not contradicts(claim_of(A, value="Chuyên ngành Kinh tế đầu tư"), [A, B])


def test_short_wrong_text_value_is_still_critical():
    assert contradicts(claim_of(DEGREE, value="Kỹ sư"), [DEGREE])


def test_unit_is_only_cut_at_the_end_of_the_value():
    assert contradicts(claim_of(CREDITS, value="tín chỉ 138"), [CREDITS])


# --- loại giá trị của critical_error (spec §4.2) ------------------------------


def test_critical_value_kind_is_none_when_not_critical():
    assert critical_value_kind(item([S]), answered(claim_of(S))) is None
    assert critical_value_kind(item([S]), None) is None
    assert critical_value_kind(item([S]), abstained()) is None


def test_critical_value_kind_number():
    assert critical_value_kind(item([S]), answered(claim_of(S, value="16"))) == "number"


def test_critical_value_kind_text():
    wrong = claim_of(DEGREE, value="Kỹ sư")
    assert critical_value_kind(item([DEGREE]), answered(wrong)) == "text"


def test_critical_value_kind_number_wins_over_text():
    claims = answered(claim_of(DEGREE, value="Kỹ sư"), claim_of(S, value="16"))
    assert critical_value_kind(item([DEGREE, S]), claims) == "number"


# --- incomplete chỉ vì thiếu năm (spec §4.2) ----------------------------------


def test_incomplete_only_for_year_when_every_slot_lacks_only_the_year():
    answer = answered(claim_of(S, admission_year=None), claim_of(S2, admission_year=None))
    assert classify(item([S, S2]), answer) == "incomplete"
    assert incomplete_only_for_year(item([S, S2]), answer)


def test_incomplete_with_a_missing_slot_is_not_only_for_year():
    answer = answered(claim_of(S, admission_year=None))
    assert not incomplete_only_for_year(item([S, S2]), answer)


def test_other_outcomes_are_not_incomplete_only_for_year():
    assert not incomplete_only_for_year(item([S]), answered(claim_of(S)))
    assert not incomplete_only_for_year(item([S]), answered(claim_of(S, value="16")))
    assert not incomplete_only_for_year(item([S]), None)


def test_abstain_on_answerable_is_abstained():
    assert classify(item([S]), abstained()) == "abstained"


def test_must_abstain_and_abstained_is_ok():
    assert classify(item([], must_abstain=True), abstained()) == "abstained_ok"


def test_must_abstain_but_answered_is_wrong():
    assert classify(item([], must_abstain=True), answered(claim_of(S))) == "answered_wrongly"


def test_none_answer_is_execution_error():
    assert classify(item([S]), None) == "execution_error"


def test_none_answer_on_must_abstain_is_execution_error_not_abstention():
    assert classify(item([], must_abstain=True), None) == "execution_error"
