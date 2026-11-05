"""Hàng đợi quét còn dở (`frontier.jsonl`): link đã thấy mà chưa tải xong, để lần quét bị dừng
(Ctrl-C, SIGTERM, chết giữa chừng) chạy lại không sót. Trạng thái vận hành: không commit.

Mỗi dòng một mục JSON; file ghi đè nguyên tử. Lần quét chạy hết hàng đợi thì xoá file."""

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)


class Frontier:
    def __init__(self, path: Path):
        self._path = Path(path)

    def load(self) -> list[dict]:
        """Dòng hỏng (ghi dở, sửa tay) bị bỏ kèm cảnh báo, không chặn lần quét."""
        if not self._path.exists():
            return []
        rows: list[dict] = []
        text = self._path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("frontier_line_dropped %s:%d: %s", self._path, number, exc)
                continue
            if not isinstance(row, dict):
                logger.warning("frontier_line_dropped %s:%d: không phải object", self._path, number)
                continue
            rows.append(row)
        return rows

    def save(self, rows: Iterable[dict]) -> None:
        payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".tmp-frontier-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
