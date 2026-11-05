"""Log các lần quét, ghi vào file trong kho web; không cần database.

`<kho>/crawl_runs.jsonl` chỉ ghi thêm: một dòng lúc bắt đầu, một dòng lúc đóng run. Dòng mới nhất
theo `id` là trạng thái hiện hành. `<kho>/fetch_log/<id>.jsonl` ghi từng request, mỗi run một file
nên xoá log cũ chỉ là xoá file.

Lỗi ghi fetch log không được ném vào luồng crawler: giữ dòng lại, lần sau thử tiếp, quá
`MAX_BUFFER` thì bỏ dòng cũ nhất. `pending()` báo số dòng chưa ghi để job đánh dấu run `warning`.
"""

import dataclasses
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from qnuchat.ingest.crawl import CrawlStats
from qnuchat.ingest.fetch import FetchEvent

logger = logging.getLogger(__name__)

MAX_BUFFER = 5000

_COUNTERS = (
    "pages_new",
    "pages_changed",
    "files_new",
    "files_changed",
    "skipped_pii",
    "auth_required",
    "needs_ocr",
    "errors",
)


class CrawlLog(Protocol):
    def start_run(self, *, trigger: str, config_hash: str) -> UUID: ...
    def log_fetch(self, run_id: UUID, event: FetchEvent) -> None: ...
    def flush(self) -> None: ...
    def finish_run(
        self,
        run_id: UUID,
        *,
        status: str,
        stats: CrawlStats,
        note: str | None = None,
        snapshot_id: str | None = None,
    ) -> None: ...
    def prune_fetch_log(self, before: datetime) -> int: ...
    def pending(self) -> int: ...
    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]: ...


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class FileCrawlLog:
    def __init__(self, data_dir: Path, *, batch: int = 200):
        self._runs = Path(data_dir) / "crawl_runs.jsonl"
        self._fetch_dir = Path(data_dir) / "fetch_log"
        self._batch = batch
        self._buffer: list[tuple[UUID, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def pending(self) -> int:
        with self._lock:
            return len(self._buffer)

    def _append_run(self, row: dict[str, Any]) -> None:
        self._runs.parent.mkdir(parents=True, exist_ok=True)
        with self._runs.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read_runs(self) -> dict[str, dict[str, Any]]:
        """Dòng mới nhất theo `id`; dòng ghi dở ở cuối file (máy tắt ngang) bị bỏ qua."""
        runs: dict[str, dict[str, Any]] = {}
        if not self._runs.exists():
            return runs
        for line in self._runs.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            runs[row["id"]] = {**runs.get(row["id"], {}), **row}
        return runs

    def start_run(self, *, trigger: str, config_hash: str) -> UUID:
        run_id = uuid4()
        self._append_run(
            {
                "id": str(run_id),
                "trigger": trigger,
                "status": "running",
                "config_hash": config_hash,
                "started_at": _now(),
            }
        )
        return run_id

    def log_fetch(self, run_id: UUID, event: FetchEvent) -> None:
        row = {k: v for k, v in dataclasses.asdict(event).items() if k != "method"}
        row["at"] = event.at.isoformat(timespec="seconds")
        with self._lock:
            self._buffer.append((run_id, row))
            if len(self._buffer) < self._batch:
                return
        self.flush()

    def flush(self) -> None:
        with self._lock:
            rows, self._buffer = self._buffer, []
        if not rows:
            return
        try:
            self._fetch_dir.mkdir(parents=True, exist_ok=True)
            for run_id in {run_id for run_id, _ in rows}:
                lines = [json.dumps(r, ensure_ascii=False) for i, r in rows if i == run_id]
                with (self._fetch_dir / f"{run_id}.jsonl").open("a", encoding="utf-8") as file:
                    file.write("\n".join(lines) + "\n")
        except OSError as exc:
            logger.warning("fetch_log_write_failed rows=%d: %s", len(rows), exc)
            with self._lock:
                self._buffer = rows + self._buffer
                overflow = len(self._buffer) - MAX_BUFFER
                if overflow > 0:
                    del self._buffer[:overflow]
                    logger.warning("fetch_log_buffer_overflow dropped=%d", overflow)

    def finish_run(
        self,
        run_id: UUID,
        *,
        status: str,
        stats: CrawlStats,
        note: str | None = None,
        snapshot_id: str | None = None,
    ) -> None:
        if str(run_id) not in self._read_runs():
            raise RuntimeError(f"finish_run: không có run {run_id} để đóng")
        self._append_run(
            {
                "id": str(run_id),
                "status": status,
                "finished_at": _now(),
                "snapshot_id": snapshot_id,
                "note": note,
                **{name: getattr(stats, name) for name in _COUNTERS},
            }
        )

    def prune_fetch_log(self, before: datetime) -> int:
        """Xoá file fetch log sửa lần cuối trước `before`; trả về số dòng đã xoá."""
        removed = 0
        if not self._fetch_dir.exists():
            return removed
        for path in self._fetch_dir.glob("*.jsonl"):
            if path.stat().st_mtime < before.timestamp():
                removed += sum(1 for _ in path.open(encoding="utf-8"))
                path.unlink()
        return removed

    def _fetch_totals(self, run_id: str) -> tuple[int, int, int]:
        """(số request, số request lỗi, tổng byte tải về) của một run."""
        path = self._fetch_dir / f"{run_id}.jsonl"
        fetches = failed = size = 0
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fetches += 1
                failed += row.get("error_cause") is not None
                size += row.get("bytes") or 0
        return fetches, failed, size

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        runs = sorted(self._read_runs().values(), key=lambda r: r["started_at"], reverse=True)
        out = []
        for run in runs[:limit]:
            n_fetch, n_errors, n_bytes = self._fetch_totals(run["id"])
            row = {name: run.get(name, 0) for name in _COUNTERS}
            row.update(
                run,
                started_at=datetime.fromisoformat(run["started_at"]),
                finished_at=(
                    datetime.fromisoformat(run["finished_at"]) if run.get("finished_at") else None
                ),
                note=run.get("note"),
                n_fetch=n_fetch,
                n_fetch_errors=n_errors,
                n_bytes=n_bytes,
            )
            out.append(row)
        return out
