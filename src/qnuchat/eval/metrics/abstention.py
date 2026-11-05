"""T5 — abstention và cắt coverage.

Nếu không cố định coverage thì một arm chỉ cần abstain nhiều hơn là "thắng"
. Ba mức dưới đây được chốt TRƯỚC khi chạy arm đầu tiên.
"""

from qnuchat.eval.schema import GoldItem, ScoredAnswer

COVERAGE_LEVELS = (1.0, 0.9, 0.8)


def apply_coverage(answers: list[ScoredAnswer], coverage: float) -> list[bool]:
    """Trả về cờ 'có trả lời' sau khi cắt xuống đúng mức coverage.

    Item đã abstain luôn là False. Trong số item còn lại, giữ những item có
    confidence cao nhất cho tới khi đạt hạn ngạch tính trên TOÀN BỘ số item.
    """
    quota = round(coverage * len(answers))
    candidates = [i for i, a in enumerate(answers) if not a.abstain]
    candidates.sort(key=lambda i: (-answers[i].confidence, i))
    kept = set(candidates[:quota])
    return [i in kept for i in range(len(answers))]


def achieved_coverage(answered: list[bool]) -> float:
    """Tỷ lệ item THỰC SỰ được trả lời sau khi cắt — không phải mức đã yêu cầu.

    `apply_coverage` chỉ CẮT BỚT, nó không thể ép một arm trả lời thêm. Nếu arm
    đã abstain 8/10 câu thì mức "80%" trên thực tế chỉ đạt 20%, và so hai arm ở
    hai mức thực tế khác nhau là so sai. Con số này
    phải được báo cáo cùng mọi kết quả tính theo coverage.
    """
    return sum(answered) / len(answered) if answered else float("nan")


def coverage_is_attained(answered: list[bool], requested: float) -> bool:
    """Mức coverage yêu cầu có thật sự đạt được không (sai số làm tròn 1 item)."""
    if not answered:
        return False
    tolerance = 0.5 / len(answered)
    return achieved_coverage(answered) >= requested - tolerance


def abstention_scores(answers: list[ScoredAnswer], items: list[GoldItem]) -> dict:
    true_positive = sum(
        1 for a, it in zip(answers, items, strict=True) if a.abstain and it.must_abstain
    )
    predicted = sum(1 for a in answers if a.abstain)
    actual = sum(1 for it in items if it.must_abstain)
    precision = true_positive / predicted if predicted else 0.0
    recall = true_positive / actual if actual else float("nan")
    f1 = (
        2 * precision * recall / (precision + recall)
        if predicted and actual and (precision + recall) > 0
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1, "n_abstained": predicted}
