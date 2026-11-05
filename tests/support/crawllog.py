"""CrawlLog trong bộ nhớ cho test job (cùng hợp đồng với FileCrawlLog)."""

import dataclasses
import threading
import uuid
from datetime import datetime
from typing import Any

from qnuchat.ingest.crawl import CrawlStats
from qnuchat.ingest.fetch import FetchEvent


class InMemoryCrawlLog:
    def __init__(self):
        self.runs: dict[uuid.UUID, dict[str, Any]] = {}
        self.fetches: list[tuple[uuid.UUID, FetchEvent]] = []
        self.pruned_before: list[datetime] = []
        self._lock = threading.Lock()

    def start_run(self, *, trigger: str, config_hash: str) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self._lock:
            self.runs[run_id] = {
                "id": run_id,
                "trigger": trigger,
                "status": "running",
                "config_hash": config_hash,
            }
        return run_id

    def log_fetch(self, run_id: uuid.UUID, event: FetchEvent) -> None:
        with self._lock:
            self.fetches.append((run_id, event))

    def flush(self) -> None:
        pass

    def pending(self) -> int:
        return 0

    def finish_run(self, run_id, *, status: str, stats: CrawlStats, note=None, snapshot_id=None):
        with self._lock:
            self.runs[run_id].update(
                status=status,
                note=note,
                snapshot_id=snapshot_id,
                **{k: v for k, v in dataclasses.asdict(stats).items() if k != "warnings"},
            )

    def prune_fetch_log(self, before: datetime) -> int:
        self.pruned_before.append(before)
        return 0

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            runs = list(self.runs.values())[-limit:][::-1]
            return [
                {
                    **run,
                    "n_fetch": sum(1 for rid, _ in self.fetches if rid == run["id"]),
                    "n_fetch_errors": sum(
                        1 for rid, e in self.fetches if rid == run["id"] and e.error_cause
                    ),
                }
                for run in runs
            ]
