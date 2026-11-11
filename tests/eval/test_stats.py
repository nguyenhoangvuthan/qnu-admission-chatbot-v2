import pytest

from qnuchat.eval.stats import paired_bootstrap_ci, wilson_interval


def test_identical_scores_give_zero_difference():
    result = paired_bootstrap_ci([1.0, 0.0, 1.0], [1.0, 0.0, 1.0], ["a", "b", "c"])
    assert result["mean_diff"] == pytest.approx(0.0)
    assert result["ci_low"] <= 0.0 <= result["ci_high"]


def test_consistent_advantage_yields_positive_interval():
    a = [1.0] * 20
    b = [0.0] * 20
    families = [f"fam{i}" for i in range(20)]
    result = paired_bootstrap_ci(a, b, families)
    assert result["mean_diff"] == pytest.approx(1.0)
    assert result["ci_low"] > 0.0


def test_cluster_count_reflects_families_not_items():
    families = ["fam1", "fam1", "fam1", "fam2"]
    result = paired_bootstrap_ci([1.0] * 4, [0.0] * 4, families)
    assert result["n_clusters"] == 2


def test_fewer_clusters_widens_the_interval():
    """8 item gom vào 4 family kém tin cậy hơn 8 item độc lập.

    Sai số chuẩn tỷ lệ nghịch với căn bậc hai của SỐ CLUSTER, không phải số item,
    nên gộp item lại phải làm khoảng tin cậy rộng ra.
    """
    a = [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    b = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    fine = paired_bootstrap_ci(a, b, [f"f{i}" for i in range(8)], seed=7)
    coarse = paired_bootstrap_ci(a, b, ["g1", "g1", "g2", "g2", "g3", "g3", "g4", "g4"], seed=7)
    assert coarse["n_clusters"] == 4 and fine["n_clusters"] == 8
    fine_width = fine["ci_high"] - fine["ci_low"]
    coarse_width = coarse["ci_high"] - coarse["ci_low"]
    assert coarse_width > fine_width


def test_single_cluster_collapses_the_interval():
    """Một cluster duy nhất thì mọi lần lấy mẫu lại đều giống hệt nhau.

    Đây là hành vi đúng của bootstrap clustered, và cũng là lời cảnh báo: một
    benchmark mà mọi câu chia chung một fact family thì không có thông tin nào
    để suy diễn thống kê.
    """
    result = paired_bootstrap_ci([1.0, 0.0], [0.0, 1.0], ["f1", "f1"], seed=7)
    assert result["n_clusters"] == 1
    assert result["ci_high"] == result["ci_low"]


def test_same_seed_reproduces_identical_interval():
    args = ([1.0, 0.0], [0.0, 1.0], ["f1", "f2"])
    assert paired_bootstrap_ci(*args, seed=1) == paired_bootstrap_ci(*args, seed=1)


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([1.0], [1.0, 0.0], ["f1", "f2"])


def test_empty_input_is_rejected():
    with pytest.raises(ValueError, match="ít nhất một item"):
        paired_bootstrap_ci([], [], [])


def test_wilson_matches_precomputed_values():
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.2775328), abs=1e-6)
    assert wilson_interval(10, 10) == pytest.approx((0.7224672, 1.0), abs=1e-6)
    assert wilson_interval(5, 10) == pytest.approx((0.2365931, 0.7634069), abs=1e-6)


def test_wilson_refuses_empty_sample():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_wilson_refuses_successes_outside_sample():
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
