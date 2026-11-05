"""T1 — key-fact accuracy. Sai giá trị là fail tuyệt đối, không có điểm bộ phận."""

import re

from qnuchat.core.contracts import Claim
from qnuchat.eval.metrics.numbers import normalise_number
from qnuchat.eval.schema import ExpectedSlot, ScoredAnswer

# "ngành Công nghệ thông tin" và "Công nghệ thông tin" là cùng một đối tượng.
# CHỈ cắt tiền tố phân loại chung; KHÔNG cắt "khối ngành" (một khối ngành không
# phải một ngành) và không cắt gì ở giữa chuỗi — "Luật" phải khác "Luật kinh tế".
_SUBJECT_PREFIX = re.compile(r"^(chuyên ngành|ngành học|ngành)\s+")
_TRAILING_PUNCT = re.compile(r"[.,;:!?]+$")


def normalise_value(text: str | None) -> str:
    if text is None:
        return ""
    value = text.strip().lower()
    value = normalise_number(value)
    return re.sub(r"\s+", " ", value)


def normalise_entity(text: str | None) -> str:
    """Chuẩn hoá subject/predicate: không đụng tới số, chỉ cắt tiền tố phân loại."""
    entity = re.sub(r"\s+", " ", (text or "").strip().lower())
    entity = _TRAILING_PUNCT.sub("", entity)
    return _SUBJECT_PREFIX.sub("", entity).strip()


def entity_matches(claim_text: str | None, expected_text: str, synonyms: list[str]) -> bool:
    """Khớp CHÍNH XÁC sau chuẩn hoá, cộng danh sách từ đồng nghĩa khai báo sẵn.

    Cố ý KHÔNG dùng substring: trong tên ngành, quan hệ bao hàm là chuyện thường
    ("Luật" nằm trong "Luật kinh tế"), nên substring sẽ chấm đúng cho một câu
    trả lời về ngành khác. Biến thể diễn đạt thật thì khai báo bằng
    `subject_synonyms`/`predicate_synonyms` trong gold, như `condition_synonyms`
    của T4 — chấm điểm phải tất định, không đoán.
    """
    actual = normalise_entity(claim_text)
    return any(actual == normalise_entity(v) for v in (expected_text, *synonyms))


def slot_matches(claim: Claim, expected: ExpectedSlot) -> bool:
    """Một claim khớp slot khi khớp CẢ đối tượng, loại thông tin, giá trị và đơn vị.

    Bỏ subject/predicate ra khỏi phép so là bug chấm điểm nghiêm trọng: hỏi điểm
    chuẩn CNTT mà trả lời điểm sàn ngành Luật cùng con số vẫn được tính đúng.
    """
    return (
        entity_matches(claim.subject, expected.subject, expected.subject_synonyms)
        and entity_matches(claim.predicate, expected.predicate, expected.predicate_synonyms)
        and normalise_value(claim.value)
        in {normalise_value(v) for v in [expected.value, *expected.value_synonyms]}
        and normalise_value(claim.unit)
        in {normalise_value(v) for v in [expected.unit, *expected.unit_synonyms]}
        and claim.admission_year == expected.admission_year
    )


def key_fact_accuracy(answer: ScoredAnswer, expected_slots: list[ExpectedSlot]) -> float:
    """1.0 khi MỌI slot mong đợi đều được khớp bởi một claim nào đó, ngược lại 0.0."""
    if not expected_slots:
        return 1.0
    if answer.abstain:
        return 0.0
    matched = sum(
        any(slot_matches(c, expected) for c in answer.claims) for expected in expected_slots
    )
    return 1.0 if matched == len(expected_slots) else 0.0
