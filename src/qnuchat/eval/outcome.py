"""Xếp mỗi câu vào đúng một nhóm kết quả (spec §4.1)."""

from collections.abc import Sequence
from typing import Literal

from qnuchat.core.contracts import Claim
from qnuchat.eval.metrics.slots import entity_matches, normalise_value, slot_matches
from qnuchat.eval.schema import ExpectedSlot, GoldItem, ScoredAnswer

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


def _agrees(claim: Claim, slot: ExpectedSlot) -> bool:
    """Cùng giá trị (tính synonym) và năm không lệch. Không xét `unit`."""
    values = {normalise_value(v) for v in (slot.value, *slot.value_synonyms)}
    years_agree = (
        claim.admission_year is None
        or slot.admission_year is None
        or claim.admission_year == slot.admission_year
    )
    return normalise_value(claim.value) in values and years_agree


def contradicts(claim: Claim, slots: Sequence[ExpectedSlot]) -> bool:
    """Claim nói về một slot kỳ vọng mà không khớp giá trị/năm của slot nào cùng đối tượng.

    Xét cả danh sách slot cùng `subject` và `predicate`, không từng slot riêng: câu kiểu
    "Kinh tế có hai chuyên ngành nào?" có nhiều slot cùng đối tượng khác giá trị, nên claim
    đúng cho slot này không được tính là mâu thuẫn với slot kia (sửa spec §4.1, 11/11/2026).
    Claim về đối tượng không có trong gold thì không đủ căn cứ để gọi là sai.
    """
    same = [s for s in slots if _same_subject_and_predicate(claim, s)]
    if not same:
        return False
    return not any(_agrees(claim, s) for s in same)


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
