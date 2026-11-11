"""Thống kê cho eval: paired bootstrap clustered và khoảng Wilson.

Paired bootstrap CLUSTERED theo fact family: lấy mẫu lại theo item là sai khi
nhiều item chia chung một fact, vì bốn paraphrase của cùng một sự kiện không
phải bốn quan sát độc lập.

Khoảng Wilson dùng cho một tỷ lệ đơn (tỷ lệ đúng, coverage, hit@5) trong báo cáo
chấm phần A.
"""

import math

import numpy as np


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Khoảng điểm Wilson cho tỷ lệ `successes / n`, mặc định 95%.

    Khác khoảng Wald, Wilson không sụp về độ rộng 0 khi tỷ lệ là 0 hoặc 1, nên
    hợp với mẫu nhỏ của bộ câu hỏi. Hai đầu được cắt về [0, 1] để khử sai số
    làm tròn. `n = 0` không có thông tin nên báo lỗi; nơi gọi tự in "—".
    """
    if n <= 0:
        raise ValueError("cần n > 0 để tính khoảng Wilson")
    if not 0 <= successes <= n:
        raise ValueError(f"successes phải nằm trong [0, {n}], nhận {successes}")

    p = successes / n
    z2 = z * z
    denominator = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def paired_bootstrap_ci(
    scores_a: list[float],
    scores_b: list[float],
    families: list[str],
    n_resamples: int = 10_000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict:
    if not (len(scores_a) == len(scores_b) == len(families)):
        raise ValueError("scores_a, scores_b và families phải cùng độ dài")

    if not families:
        raise ValueError("cần ít nhất một item để bootstrap")

    a = np.asarray(scores_a, dtype=float)
    b = np.asarray(scores_b, dtype=float)
    diff = a - b

    unique = sorted(set(families))
    index_by_family = {f: np.flatnonzero(np.asarray(families) == f) for f in unique}

    rng = np.random.default_rng(seed)
    means = np.empty(n_resamples, dtype=float)
    for draw in range(n_resamples):
        picked = rng.choice(len(unique), size=len(unique), replace=True)
        rows = np.concatenate([index_by_family[unique[p]] for p in picked])
        means[draw] = diff[rows].mean()

    low, high = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return {
        "mean_diff": float(diff.mean()),
        "ci_low": float(low),
        "ci_high": float(high),
        "n_clusters": len(unique),
        "n_items": len(diff),
    }
