"""Xếp mỗi câu vào đúng một nhóm kết quả (spec §4.1)."""

import re
from collections.abc import Sequence
from typing import Literal

from qnuchat.core.contracts import Claim
from qnuchat.eval.metrics.slots import entity_matches, normalise_value, slot_matches
from qnuchat.eval.schema import ExpectedSlot, GoldItem, ScoredAnswer

ValueKind = Literal["number", "text"]

Outcome = Literal[
    "correct",
    "critical_error",
    "incomplete",
    "abstained",
    "abstained_ok",
    "answered_wrongly",
    "execution_error",
]


def _same_subject_and_predicate(claim: Claim, slot: ExpectedSlot) -> bool:
    return entity_matches(claim.subject, slot.subject, slot.subject_synonyms) and entity_matches(
        claim.predicate, slot.predicate, slot.predicate_synonyms
    )


# Chỉ dùng khi xét critical_error (sửa spec §4.1 lần hai): cách viết khác của cùng giá trị không
# phải lỗi nghiêm trọng. `correct` vẫn so bằng `slot_matches`, không qua chuẩn hoá này.
_TRAILING_PUNCT = re.compile(r"[.,;:!?]+$")
_MAJOR_PREFIX = re.compile(r"^(chuyên ngành|ngành học|ngành)\s+")
_NUMBER = re.compile(r"^[\d.]+$")


def _loose(text: str | None) -> str:
    value = _TRAILING_PUNCT.sub("", normalise_value(text)).strip()
    return _MAJOR_PREFIX.sub("", value).strip()


def _claim_value(claim: Claim, slot: ExpectedSlot) -> str:
    """Giá trị claim đã chuẩn hoá, bỏ đơn vị của slot nếu model ghi nó ở cuối `value`."""
    value = _loose(claim.value)
    for unit in (slot.unit, *slot.unit_synonyms):
        suffix = " " + normalise_value(unit) if unit else ""
        if suffix.strip() and value.endswith(suffix):
            return _loose(value[: -len(suffix)])
    return value


def _agrees(claim: Claim, slot: ExpectedSlot) -> bool:
    """Cùng giá trị (tính synonym, chuẩn hoá lỏng) và năm không lệch. Không xét `unit`."""
    values = {_loose(v) for v in (slot.value, *slot.value_synonyms)}
    years_agree = (
        claim.admission_year is None
        or slot.admission_year is None
        or claim.admission_year == slot.admission_year
    )
    return _claim_value(claim, slot) in values and years_agree


def _is_number(slot: ExpectedSlot) -> bool:
    return bool(_NUMBER.match(normalise_value(slot.value)))


def _same(claim: Claim, slots: Sequence[ExpectedSlot]) -> list[ExpectedSlot]:
    return [s for s in slots if _same_subject_and_predicate(claim, s)]


def contradicts(claim: Claim, slots: Sequence[ExpectedSlot]) -> bool:
    """Claim nói về một slot kỳ vọng mà không khớp giá trị/năm của slot nào cùng đối tượng.

    Xét cả danh sách slot cùng `subject` và `predicate`, không từng slot riêng: câu kiểu
    "Kinh tế có hai chuyên ngành nào?" có nhiều slot cùng đối tượng khác giá trị, nên claim
    đúng cho slot này không được tính là mâu thuẫn với slot kia (sửa spec §4.1, 11/11/2026).
    Claim về đối tượng không có trong gold thì không đủ căn cứ để gọi là sai.
    """
    same = _same(claim, slots)
    if not same:
        return False
    return not any(_agrees(claim, s) for s in same)


def critical_value_kind(item: GoldItem, answer: ScoredAnswer | None) -> ValueKind | None:
    """Loại giá trị của lỗi nghiêm trọng (spec §4.2); `None` khi câu không phải `critical_error`.

    "number" khi có claim mâu thuẫn với slot số; "text" khi mọi mâu thuẫn chỉ ở slot chữ. Cột chữ
    dễ đếm nhầm vì diễn đạt khác (spec §4.1), nên báo cáo tách riêng để đọc tay.
    """
    if classify(item, answer) != "critical_error":
        return None
    assert answer is not None
    slots = item.expected_slots
    for claim in answer.claims:
        if contradicts(claim, slots) and any(_is_number(s) for s in _same(claim, slots)):
            return "number"
    return "text"


def classify(item: GoldItem, answer: ScoredAnswer | None) -> Outcome:
    """Nhóm kết quả của một câu. `answer is None` nghĩa là câu lỗi khi chạy.

    Lỗi chạy không bao giờ thành từ chối (AGENTS.md), kể cả ở câu phải từ chối.
    """
    if answer is None:
        return "execution_error"
    if item.must_abstain:
        return "abstained_ok" if answer.abstain else "answered_wrongly"
    if answer.abstain:
        return "abstained"
    slots = item.expected_slots
    if any(contradicts(c, slots) for c in answer.claims):
        return "critical_error"
    if all(any(slot_matches(c, s) for c in answer.claims) for s in slots):
        return "correct"
    return "incomplete"


def incomplete_only_for_year(item: GoldItem, answer: ScoredAnswer | None) -> bool:
    """Câu `incomplete` mà sẽ `correct` nếu claim thiếu `admission_year` được lấy năm của slot.

    `slot_matches` đòi năm bằng nhau, nên model hay bỏ trống năm làm tỷ lệ đúng tụt mà nhìn nhóm
    kết quả không thấy lý do (spec §4.2). Chỉ để báo cáo, không đổi nhóm của câu.
    """
    if classify(item, answer) != "incomplete":
        return False
    assert answer is not None
    return all(
        any(
            slot_matches(
                c if c.admission_year is not None
                else c.model_copy(update={"admission_year": s.admission_year}),
                s,
            )
            for c in answer.claims
        )
        for s in item.expected_slots
    )
