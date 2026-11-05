"""Paired bootstrap CLUSTERED theo fact family.

Lấy mẫu lại theo item là sai khi nhiều item chia chung một fact: bốn paraphrase
của cùng một sự kiện không phải bốn quan sát độc lập.
"""

import numpy as np


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
