"""Lần kiểm cuối của từng URL và cờ "hub" (spec §6.2 bước 2). Trạng thái vận hành: không commit."""

import json
import logging
import os
import tempfile
import threading
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


class CheckState:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = self._read()

    def _read(self) -> dict[str, dict]:
        """File hỏng (ghi dở, sửa tay) không chặn lần quét: chỉ mất lịch kiểm, bắt đầu lại từ {}."""
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("last_checked_corrupt_starting_empty %s: %s", self._path, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning("last_checked_corrupt_starting_empty %s: không phải object", self._path)
            return {}
        return data

    def due(self, url: str, today: date, days: int) -> bool:
        with self._lock:
            row = self._data.get(url)
        return row is None or (today - date.fromisoformat(row["checked"])).days >= days

    def is_hub(self, url: str) -> bool:
        with self._lock:
            return bool(self._data.get(url, {}).get("hub"))

    def known(self, url: str) -> bool:
        """URL đã từng được kiểm (có dòng trong state)."""
        with self._lock:
            return url in self._data

    def mark(self, url: str, today: date, *, hub: bool | None = None) -> None:
        """Ghi một lần kiểm có kết quả; xoá đếm `misses` (lần kiểm này không thấy trang lỗi mềm)."""
        with self._lock:
            row = self._data.setdefault(url, {"hub": False})
            row["checked"] = today.isoformat()
            row.pop("misses", None)
            if hub is not None:
                row["hub"] = hub

    def forget(self, url: str) -> None:
        """Bỏ lịch kiểm của URL: lần quét sau tải lại ngay (`prune` dùng để suy lại ngày đăng)."""
        with self._lock:
            self._data.pop(url, None)

    def miss(self, url: str, today: date) -> int:
        """Ghi một lần kiểm thấy trang lỗi mềm; trả số lần thấy liên tiếp. Giữ cờ hub."""
        with self._lock:
            row = self._data.setdefault(url, {"hub": False})
            row["checked"] = today.isoformat()
            row["misses"] = row.get("misses", 0) + 1
            return row["misses"]

    def save(self) -> None:
        # Giữ khoá suốt lúc ghi: hai lần lưu đồng thời (lưu định kỳ của crawler) không đè nhau
        # bằng bản cũ hơn.
        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False, sort_keys=True)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self._path)
            finally:
                Path(tmp).unlink(missing_ok=True)
