"""Sổ quyết định lọc chủ đề `data/web/topic.jsonl` (spec knowledge base §5.1).

Chỉ ghi thêm như manifest; dòng mới nhất theo (`url`, `sha256`) là quyết định hiện hành.
`prune` đọc sổ này nên chạy được không cần DB.
"""

import dataclasses
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

Label = Literal["giu", "loai", "khong_chac"]


@dataclass(frozen=True)
class TopicDecision:
    url: str
    sha256: str
    pass_: int  # lần lọc 1 (tiêu đề/URL/trang chứa) hay 2 (chữ OCR); JSON ghi là "pass"
    label: Label | None  # None = execution error, xem error_cause
    group: str | None
    reason: str | None
    note: str
    prompt_hash: str
    # Phiên bản bộ lọc: prompt + model + revision + giới hạn đầu vào/ra + lần lọc. Duyệt và chạy
    # tiếp theo khoá này, không chỉ theo prompt (§5.1 ghim revision; §7.5).
    filter_id: str
    model: str
    model_revision: str
    error_cause: str | None
    decided_by: Literal["model", "kent"]
    at: str


def _to_json(decision: TopicDecision) -> str:
    row = dataclasses.asdict(decision)
    row["pass"] = row.pop("pass_")
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _from_json(row: dict) -> TopicDecision:
    row = dict(row)
    row["pass_"] = row.pop("pass")
    return TopicDecision(**row)


class TopicLedger:
    """`repair=True` chỉ cho người ghi duy nhất (`classify`): cắt dòng ghi dở ở cuối file trước khi
    ghi tiếp, như `Manifest`. Người chỉ đọc (`prune`, `topic-score`) bỏ qua dòng dở, file giữ
    nguyên."""

    def __init__(self, path: Path, *, repair: bool = False):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._entries: list[TopicDecision] = []
        self._current: dict[tuple[str, str], TopicDecision] = {}
        self._done: set[tuple[str, str, str]] = set()
        self._repair = repair
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        data = self._path.read_bytes()
        # Dòng ghi dở ở cuối (tiến trình chết giữa lúc ghi): người ghi cắt bỏ, người đọc bỏ qua.
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            if self._repair:
                with self._path.open("r+b") as fh:
                    fh.truncate(cut)
            data = data[:cut]
        for number, raw in enumerate(data.split(b"\n"), start=1):
            if not raw.strip():
                continue
            try:
                self._remember(_from_json(json.loads(raw.decode("utf-8"))))
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                raise ValueError(f"{self._path} dòng {number} hỏng: {exc}") from exc

    def _remember(self, decision: TopicDecision) -> None:
        self._entries.append(decision)
        self._current[(decision.url, decision.sha256)] = decision
        if decision.error_cause is None and decision.label is not None:
            self._done.add((decision.url, decision.sha256, decision.filter_id))

    def append(self, decision: TopicDecision) -> None:
        if not self._repair:
            raise RuntimeError("TopicLedger mở chỉ đọc (repair=False): không ghi được")
        line = _to_json(decision)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._remember(decision)

    def entries(self) -> list[TopicDecision]:
        return list(self._entries)

    def current(self, url: str, sha256: str) -> TopicDecision | None:
        return self._current.get((url, sha256))

    def done(self, url: str, sha256: str, *, filter_id: str) -> bool:
        """Đã có quyết định không lỗi cho đúng phiên bản nội dung và phiên bản bộ lọc."""
        return (url, sha256, filter_id) in self._done


def prompt_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def filter_id(
    *,
    prompt_hash: str,
    model: str,
    model_revision: str,
    max_chars: int,
    max_tokens: int,
    pass_: int,
) -> str:
    """Khoá phiên bản bộ lọc: đổi bất kỳ thành phần nào là bộ lọc mới, phải đo lại."""
    parts = {
        "prompt_hash": prompt_hash,
        "model": model,
        "model_revision": model_revision,
        "max_chars": max_chars,
        "max_tokens": max_tokens,
        "pass": pass_,
    }
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class TopicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_chars: int
    max_tokens: int
    sample_size: int
    sample_seed: int
    host_groups: dict[str, list[str]]


def load_topic_config(path: Path) -> TopicConfig:
    try:
        return TopicConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise ValueError(f"{path}: {exc}") from exc


@dataclass(frozen=True)
class TopicPolicy:
    """Quyết định nào của sổ được `prune` áp: của Kent, hoặc của phiên bản bộ lọc (`filter_id`) đã
    có `score.json` đạt."""

    ledger: TopicLedger
    approved_filters: frozenset[str]

    def withdraws(self, url: str, sha256: str | None) -> bool:
        decision = self.ledger.current(url, sha256) if sha256 else None
        return (
            decision is not None
            and decision.label == "loai"
            and (decision.decided_by == "kent" or decision.filter_id in self.approved_filters)
        )

    def keeps(self, url: str, sha256: str | None) -> bool:
        decision = self.ledger.current(url, sha256) if sha256 else None
        return decision is not None and decision.label == "giu"


def load_topic_policy(ledger_path: Path, filter_dir: Path) -> TopicPolicy | None:
    """None khi chưa có sổ: `prune` chạy như trước khi có bộ lọc chủ đề."""
    if not Path(ledger_path).exists():
        return None
    approved = set()
    for score_file in Path(filter_dir).glob("*/score.json"):
        result = json.loads(score_file.read_text(encoding="utf-8"))
        if result.get("passed") is True and result.get("filter_id"):
            approved.add(result["filter_id"])
    return TopicPolicy(TopicLedger(ledger_path), frozenset(approved))
