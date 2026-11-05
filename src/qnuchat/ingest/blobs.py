"""Kho blob theo nội dung (spec §6.4): `blobs/A/<sha256>` (commit qua LFS),
`blobs/B/<sha256>` (chỉ trên đĩa), `quarantine/<sha256>` (chờ OCR để kiểm PII;
không index, không commit)."""

import hashlib
import os
import tempfile
import threading
from pathlib import Path

TIERS = ("A", "B")


class BlobStore:
    def __init__(self, root: Path):
        self._root = Path(root)
        self._lock = threading.Lock()

    def quarantine_dir(self) -> Path:
        return self._root / "quarantine"

    def _dest(self, sha: str, tier: str, quarantine: bool) -> Path:
        return self.quarantine_dir() / sha if quarantine else self._root / "blobs" / tier / sha

    def put(self, data: bytes, *, tier: str, quarantine: bool = False) -> str:
        if tier not in TIERS:
            raise ValueError(f"tier phải là A hoặc B, nhận {tier!r}")
        sha = hashlib.sha256(data).hexdigest()
        dest = self._dest(sha, tier, quarantine)
        with self._lock:
            if not quarantine:
                a_copy = self._dest(sha, "A", False)
                if tier == "A":
                    other = self._dest(sha, "B", False)
                    if other.exists() and not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(other, dest)
                elif a_copy.exists():
                    return sha
            if dest.exists():
                return sha
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, dest)
            finally:
                # Ghi lỗi giữa chừng thì không để lại file tạm; ghi xong thì tmp đã thành dest.
                Path(tmp).unlink(missing_ok=True)
        return sha

    def path(self, sha: str) -> Path | None:
        for candidate in (
            self._dest(sha, "A", False),
            self._dest(sha, "B", False),
            self._dest(sha, "A", True),
        ):
            if candidate.exists():
                return candidate
        return None

    def delete(self, sha: str) -> None:
        with self._lock:
            for candidate in (
                self._dest(sha, "A", False),
                self._dest(sha, "B", False),
                self._dest(sha, "A", True),
            ):
                candidate.unlink(missing_ok=True)
