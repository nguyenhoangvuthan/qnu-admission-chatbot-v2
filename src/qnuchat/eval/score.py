"""Chấm một lượt chạy thành `report.json` và `report.md` (spec phần A §4).

Đọc lại `manifest.json` và `records.jsonl` do runner ghi, không gọi model. Bộ câu hỏi đổi hash so
với manifest thì từ chối chấm. Mẫu số N là số câu trả lời được có `status = ok`; câu lỗi chạy không
tính là từ chối và không vào mẫu số. Mọi tỷ lệ kèm khoảng Wilson 95%; N = 0 thì tỷ lệ là `None`.
"""

import json
import math
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import get_args

from qnuchat.core.contracts import Answer
from qnuchat.eval.cases import EvalCase, check_gold_unchanged, read_rows, select_cases
from qnuchat.eval.metrics.abstention import abstention_scores
from qnuchat.eval.metrics.retrieval import (
    PageKey,
    hit_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from qnuchat.eval.outcome import Outcome, classify, critical_value_kind
from qnuchat.eval.runner import MANIFEST, RECORDS, read_records
from qnuchat.eval.schema import ScoredAnswer
from qnuchat.eval.stats import wilson_interval

OUTCOMES: tuple[str, ...] = get_args(Outcome)

# Nhãn tiếng Việt của từng nhóm kết quả trong report.md.
_OUTCOME_LABELS = {
    "correct": "Đúng",
    "critical_error": "Lỗi nghiêm trọng",
    "incomplete": "Thiếu",
    "abstained": "Từ chối",
    "abstained_ok": "Từ chối đúng",
    "answered_wrongly": "Trả lời câu phải từ chối",
    "execution_error": "Lỗi chạy",
}


class ScoreError(ValueError):
    """Không chấm được lượt chạy với dữ liệu hiện tại."""


def rate(k: int, n: int) -> dict | None:
    """Tỷ lệ `k / n` kèm Wilson 95%; `n == 0` thì `None` (báo cáo in "—")."""
    if n == 0:
        return None
    low, high = wilson_interval(k, n)
    return {"k": k, "n": n, "value": k / n, "ci_low": low, "ci_high": high}


def score_run(run_dir: Path) -> dict:
    """Chấm lượt ở `run_dir` thành dict cấu trúc `report.json` (plan Task 6)."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / MANIFEST).read_text(encoding="utf-8"))
    check_gold_unchanged(manifest["gold_files"])

    rows = read_rows([Path(entry["path"]) for entry in manifest["gold_files"]])
    cases, _ = select_cases(rows, manifest["sources"])
    with_forbidden = [c.item.id for c in cases if c.item.forbidden_claims]
    if with_forbidden:
        raise ScoreError(
            "chưa có metric cho forbidden_claims; câu có trường này khác rỗng: "
            + ", ".join(with_forbidden)
        )

    mode = manifest["mode"]
    records = read_records(run_dir / RECORDS)
    done = [(c, records[c.item.id]) for c in cases if c.item.id in records]
    if mode == "full":
        for case, record in done:
            if record["status"] == "ok" and record.get("answer") is None:
                raise ScoreError(f"câu {case.item.id}: dòng ok mà không có answer ở chế độ full")

    errors = Counter(
        record["error"]["cause"] for _, record in done if record["status"] == "execution_error"
    )
    task_types = sorted({case.task_type for case in cases})
    return {
        "label": manifest["label"],
        "run_id": manifest.get("run_id", run_dir.name),
        "mode": mode,
        "sources": list(dict.fromkeys(manifest["sources"].values())),
        "missing": len(cases) - len(done),
        "execution_errors": dict(sorted(errors.items())),
        "overall": _section(done, mode),
        "by_task_type": {
            t: _section([(c, r) for c, r in done if c.task_type == t], mode) for t in task_types
        },
    }


def _section(done: Sequence[tuple[EvalCase, dict]], mode: str) -> dict:
    ok = [(case, record) for case, record in done if record["status"] == "ok"]
    answerable = [(case, record) for case, record in ok if not case.item.must_abstain]
    n = len(answerable)
    section: dict = {"n": n}
    if mode == "full":
        scored = {case.item.id: _scored(record) for case, record in ok}
        outcomes = Counter(
            classify(case.item, scored.get(case.item.id)) for case, _ in done
        )
        section["outcomes"] = {name: outcomes[name] for name in OUTCOMES}
        section["accuracy"] = rate(outcomes["correct"], n)
        section["critical_error_rate"] = rate(outcomes["critical_error"], n)
        kinds = {c.item.id: critical_value_kind(c.item, scored.get(c.item.id)) for c, _ in done}
        section["critical_error_kinds"] = {
            kind: sum(k == kind for k in kinds.values()) for kind in ("number", "text")
        }
        section["critical_error_text_ids"] = sorted(i for i, k in kinds.items() if k == "text")
        section["coverage"] = rate(n - outcomes["abstained"], n)
        section["abstention"] = _abstention(ok, scored, outcomes["answered_wrongly"])
    section["retrieval"] = _retrieval(answerable)
    return section


def _scored(record: dict) -> ScoredAnswer:
    answer = Answer.model_validate(record["answer"])
    # Câu hỏi lại không có confidence (contract của core); coi như 0.
    confidence = answer.confidence.value if answer.confidence is not None else 0.0
    return ScoredAnswer(abstain=answer.abstain, claims=answer.claims, confidence=confidence)


def _abstention(
    ok: Sequence[tuple[EvalCase, dict]], scored: dict[str, ScoredAnswer], answered_wrongly: int
) -> dict | None:
    if not ok:
        return None
    scores = abstention_scores(
        [scored[case.item.id] for case, _ in ok], [case.item for case, _ in ok]
    )
    return {
        "precision": _finite(scores["precision"]),
        "recall": _finite(scores["recall"]),  # nan khi nhóm không có câu phải từ chối
        "f1": _finite(scores["f1"]),
        "n_abstained": scores["n_abstained"],
        "answered_wrongly": answered_wrongly,
    }


def _retrieval(answerable: Sequence[tuple[EvalCase, dict]]) -> dict:
    pairs = [(_ranked_pages(record), case.gold_evidence) for case, record in answerable]
    n = len(pairs)
    return {
        "recall_at_5": _mean([recall_at_k(r, g, k=5) for r, g in pairs]),
        "mrr": _mean([reciprocal_rank(r, g) for r, g in pairs]),
        "ndcg_at_10": _mean([ndcg_at_k(r, g, k=10) for r, g in pairs]),
        "hit_at_5": rate(sum(hit_at_k(r, g, k=5) for r, g in pairs), n),
    }


def _ranked_pages(record: dict) -> list[PageKey]:
    passages = sorted(record["passages"], key=lambda p: p["rank"])
    return [(p["source_id"], int(p["page"])) for p in passages]


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _finite(value: float) -> float | None:
    """JSON không có NaN: số không xác định ghi thành `null`."""
    return None if math.isnan(value) else value


# --- report.md -------------------------------------------------------------


def _number(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def _rate_text(value: dict | None) -> str:
    if value is None:
        return "—"
    return f"{_number(value['value'])} [{_number(value['ci_low'])}–{_number(value['ci_high'])}]"


def _abstention_field(name: str) -> Callable[[dict], str]:
    def get(section: dict) -> str:
        abstention = section["abstention"]
        if abstention is None:
            return "—"
        value = abstention[name]
        return str(value) if isinstance(value, int) else _number(value)

    return get


_FULL_METRICS: list[tuple[str, Callable[[dict], str]]] = [
    ("N", lambda s: str(s["n"])),
    ("Tỷ lệ đúng", lambda s: _rate_text(s["accuracy"])),
    ("decision-critical error rate", lambda s: _rate_text(s["critical_error_rate"])),
    ("Lỗi nghiêm trọng: slot số", lambda s: str(s["critical_error_kinds"]["number"])),
    ("Lỗi nghiêm trọng: chỉ slot chữ", lambda s: str(s["critical_error_kinds"]["text"])),
    ("Coverage", lambda s: _rate_text(s["coverage"])),
    ("Từ chối: precision", _abstention_field("precision")),
    ("Từ chối: recall", _abstention_field("recall")),
    ("Từ chối: F1", _abstention_field("f1")),
    ("Trả lời câu phải từ chối", _abstention_field("answered_wrongly")),
]

_RETRIEVAL_METRICS: list[tuple[str, Callable[[dict], str]]] = [
    ("R@5", lambda s: _number(s["retrieval"]["recall_at_5"])),
    ("MRR", lambda s: _number(s["retrieval"]["mrr"])),
    ("nDCG@10", lambda s: _number(s["retrieval"]["ndcg_at_10"])),
    ("hit@5", lambda s: _rate_text(s["retrieval"]["hit_at_5"])),
]


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def render_markdown(report: dict) -> str:
    """Báo cáo đọc được: dòng nhãn phát triển, bảng tổng, bảng theo `task_type`, lỗi chạy."""
    lines = [
        "Số phát triển: bộ câu hỏi nháp, kho "
        + ", ".join(report["sources"])
        + "; không dùng để báo cáo."
    ]
    if report["missing"] > 0:
        lines += ["", f"**Lượt chưa chạy xong:** {report['missing']} câu chưa có kết quả."]
    lines += [
        "",
        (
            f"Lượt `{report['run_id']}`, chế độ `{report['mode']}`. N là số câu trả lời được có "
            "`status = ok`; tỷ lệ kèm khoảng Wilson 95%."
        ),
    ]

    full = report["mode"] == "full"
    metrics = (_FULL_METRICS if full else _FULL_METRICS[:1]) + _RETRIEVAL_METRICS
    overall = report["overall"]
    by_type = report["by_task_type"]

    lines += ["", "## Tổng", ""]
    lines += _table(["Số", "Giá trị"], [[label, get(overall)] for label, get in metrics])

    if full:
        lines += ["", "## Nhóm kết quả", ""]
        groups = [("Tổng", overall), *by_type.items()]
        lines += _table(
            ["Nhóm câu", *(_OUTCOME_LABELS[o] for o in OUTCOMES)],
            [[name, *(str(s["outcomes"][o]) for o in OUTCOMES)] for name, s in groups],
        )

    if full:
        lines += ["", "## Lỗi nghiêm trọng ở slot chữ (đọc tay)", ""]
        text_ids = overall["critical_error_text_ids"]
        lines.append(", ".join(f"`{i}`" for i in text_ids) if text_ids else "Không có.")

    lines += ["", "## Theo task_type", ""]
    lines += _table(
        ["task_type", *(label for label, _ in metrics)],
        [[name, *(get(s) for _, get in metrics)] for name, s in by_type.items()],
    )

    lines += ["", "## Execution error", ""]
    if report["execution_errors"]:
        lines += _table(
            ["cause", "Số câu"], [[c, str(k)] for c, k in report["execution_errors"].items()]
        )
    else:
        lines.append("Không có.")
    return "\n".join(lines) + "\n"


def write_report(run_dir: Path, report: dict) -> None:
    """Ghi `report.json` (UTF-8, giữ dấu tiếng Việt, indent 2) và `report.md` vào `run_dir`."""
    run_dir = Path(run_dir)
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
