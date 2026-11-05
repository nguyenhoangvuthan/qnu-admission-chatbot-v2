"""Tiến độ cho lệnh chạy lâu: thanh tqdm trong terminal, dòng log định kỳ khi không có terminal.

systemd không có terminal: thanh tqdm ở đó chỉ làm rác journal, nên đổi sang một dòng mỗi 30 giây.
"""

import logging
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Self, TextIO

from tqdm import tqdm

LOG_EVERY_S = 30.0
say = tqdm.write  # in một dòng mà không làm vỡ thanh tiến độ đang chạy


class _BarSafeHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        tqdm.write(self.format(record), file=sys.stderr)


def setup_logging(name: str, log_dir: Path = Path("artifacts/logs")) -> None:
    """Log INFO của `apps`, `qnuchat` ra terminal và `logs/<name>.log`; gọi lặp lại không sao."""
    root = logging.getLogger("apps")
    if root.handlers:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers: list[logging.Handler] = [
        _BarSafeHandler(),
        logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8"),
    ]
    for handler in handlers:
        handler.setFormatter(fmt)
    for logger in (root, logging.getLogger("qnuchat")):
        logger.setLevel(logging.INFO)
        for handler in handlers:
            logger.addHandler(handler)


class Progress:
    def __init__(
        self,
        desc: str,
        *,
        total: int | None = None,
        stream: TextIO | None = None,
        every_s: float = LOG_EVERY_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.desc, self.total, self.done = desc, total, 0
        self.stream = stream or sys.stderr
        self.every_s, self._clock = every_s, clock
        self._start = self._last = clock()
        self._bar = (
            tqdm(total=total, desc=desc, file=self.stream, dynamic_ncols=True)
            if self.stream.isatty()
            else None
        )

    def update(self, n: int = 1, *, total: int | None = None, note: str = "") -> None:
        self.done += n
        if total is not None:
            self.total = total
        if self._bar is not None:
            if total is not None:
                self._bar.total = total
            if note:
                self._bar.set_postfix_str(note, refresh=False)
            self._bar.update(n)
            return
        now = self._clock()
        if now - self._last >= self.every_s:
            self._last = now
            self._line(f"{self._count()} ({int(now - self._start)} giây) {note}".rstrip())

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
        else:
            self._line(f"xong {self._count()} ({int(self._clock() - self._start)} giây)")

    def _count(self) -> str:
        return f"{self.done}/{self.total}" if self.total is not None else str(self.done)

    def _line(self, text: str) -> None:
        print(f"{self.desc}: {text}", file=self.stream, flush=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def track[T](items: Iterable[T], desc: str, **kwargs) -> Iterator[T]:
    items = list(items)
    with Progress(desc, total=len(items), **kwargs) as bar:
        for item in items:
            yield item
            bar.update()
