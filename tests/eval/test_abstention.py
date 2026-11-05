import pytest

from qnuchat.eval.metrics.abstention import (
    COVERAGE_LEVELS,
    abstention_scores,
    achieved_coverage,
    apply_coverage,
    coverage_is_attained,
)
from qnuchat.eval.schema import GoldItem, ScoredAnswer


def ans(confidence: float, abstain: bool = False) -> ScoredAnswer:
    return ScoredAnswer(abstain=abstain, claims=[], confidence=confidence)


def item(must_abstain: bool) -> GoldItem:
    return GoldItem(
        id="i", question="q", origin="challenge", risk="high", admission_year=2025,
        must_abstain=must_abstain, gold_page_ids=[], expected_slots=[],
        required_conditions=[], forbidden_claims=[], source_family="f", reviewer="kent",
    )


def test_coverage_levels_are_the_three_from_spec():
    assert COVERAGE_LEVELS == (1.0, 0.9, 0.8)


def test_full_coverage_answers_everything_not_already_abstained():
    answers = [ans(0.9), ans(0.1), ans(0.5, abstain=True)]
    assert apply_coverage(answers, coverage=1.0) == [True, True, False]


def test_lower_coverage_drops_lowest_confidence_first():
    answers = [ans(0.9), ans(0.5), ans(0.1), ans(0.7)]
    answered = apply_coverage(answers, coverage=0.5)
    assert answered == [True, False, False, True]


def test_coverage_is_computed_over_all_items_including_abstained():
    """Arm không được ăn gian bằng cách abstain đúng chỗ dễ."""
    answers = [ans(0.9), ans(0.8), ans(0.1, abstain=True), ans(0.05, abstain=True)]
    assert sum(apply_coverage(answers, coverage=0.5)) == 2


def test_abstention_recall_counts_correctly_refused_items():
    answers = [ans(0.1, abstain=True), ans(0.9)]
    items = [item(must_abstain=True), item(must_abstain=True)]
    assert abstention_scores(answers, items)["recall"] == pytest.approx(0.5)


def test_abstention_precision_penalises_refusing_answerable_items():
    answers = [ans(0.1, abstain=True), ans(0.1, abstain=True)]
    items = [item(must_abstain=True), item(must_abstain=False)]
    assert abstention_scores(answers, items)["precision"] == pytest.approx(0.5)


def test_f1_is_zero_when_nothing_abstained():
    scores = abstention_scores([ans(0.9)], [item(must_abstain=True)])
    assert scores["f1"] == 0.0


def test_achieved_coverage_reports_the_real_answered_fraction():
    """8/10 đã abstain: mức yêu cầu 80% trên thực tế chỉ đạt 20%."""
    answers = [ans(0.9), ans(0.8)] + [ans(0.1, abstain=True) for _ in range(8)]
    answered = apply_coverage(answers, coverage=0.8)
    assert achieved_coverage(answered) == pytest.approx(0.2)


def test_unreachable_coverage_level_is_flagged():
    answers = [ans(0.9), ans(0.8)] + [ans(0.1, abstain=True) for _ in range(8)]
    answered = apply_coverage(answers, coverage=0.8)
    assert coverage_is_attained(answered, 0.8) is False


def test_reachable_coverage_level_is_attained():
    answers = [ans(0.9), ans(0.8), ans(0.7), ans(0.6), ans(0.5)]
    answered = apply_coverage(answers, coverage=0.8)
    assert achieved_coverage(answered) == pytest.approx(0.8)
    assert coverage_is_attained(answered, 0.8) is True


def test_rounding_of_one_item_does_not_count_as_unattained():
    """quota = round(0.9 * 7) = 6 → 6/7 ≈ 0.857 < 0.9 nhưng đó là làm tròn, không
    phải arm abstain quá nhiều."""
    answers = [ans(0.9) for _ in range(7)]
    answered = apply_coverage(answers, coverage=0.9)
    assert coverage_is_attained(answered, 0.9) is True
