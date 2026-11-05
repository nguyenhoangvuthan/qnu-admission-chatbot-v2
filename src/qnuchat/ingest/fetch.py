"""Client HTTP lịch sự cho crawler và tầng C: giới hạn tốc độ theo host, thử lại, chặn kích thước.

Mỗi request (sau mọi lần thử) báo đúng một `FetchEvent` qua `on_fetch`; job ghi sự kiện vào
`app.fetch_log` (spec §18). Lỗi trả về là `FetchError` với `cause` thuộc tập của spec §17.1.
"""

import hashlib
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx


@dataclass(frozen=True)
class Response:
    url: str
    final_url: str
    status: int
    content_type: str
    content: bytes
    retry_after: str | None = None


@dataclass(frozen=True)
class FetchEvent:
    url: str
    method: str
    source: str
    http_status: int | None
    error_cause: str | None
    duration_ms: int
    sha256: str | None
    bytes: int | None
    at: datetime


class FetchError(Exception):
    def __init__(self, url: str, cause: str, status: int | None = None, detail: str | None = None):
        super().__init__(f"[{cause}] {url}" + (f" ({detail})" if detail else ""))
        self.url, self.cause, self.status, self.detail = url, cause, status, detail


class _TooLarge(Exception):
    pass


class _TooManyRedirects(Exception):
    pass


_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_MAX_REDIRECTS = 10
_TRANSIENT_4XX = (408, 429)
_MAX_RETRY_AFTER_S = 30.0


def _retry_after(value: str | None) -> float | None:
    """Số giây server xin chờ (chặn ở 30); dạng ngày HTTP hay rác thì None để dùng backoff."""
    if value is None or not value.strip().isdigit():
        return None
    return min(float(value.strip()), _MAX_RETRY_AFTER_S)


class Fetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        rps_per_host: float,
        timeout_s: float,
        max_bytes: int,
        retries: int,
        source: str = "crawl",
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        on_fetch: Callable[[FetchEvent], None] | None = None,
    ):
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
            follow_redirects=False,
            transport=transport,
        )
        self._interval = 1.0 / rps_per_host
        self._max_bytes = max_bytes
        self._retries = retries
        self._source = source
        self._clock, self._sleep, self._now = clock, sleep, now
        self._on_fetch = on_fetch
        self._next_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, url: str) -> Response:
        return self._request("GET", url)

    def post_form(self, url: str, data: Mapping[str, str]) -> Response:
        return self._request("POST", url, dict(data))

    def close(self) -> None:
        self._client.close()

    def _wait_turn(self, host: str) -> None:
        with self._lock:
            now = self._clock()
            at = max(now, self._next_at.get(host, 0.0))
            self._next_at[host] = at + self._interval
        if at > now:
            self._sleep(at - now)

    def _request(self, method: str, url: str, data: dict[str, str] | None = None) -> Response:
        host = urlsplit(url).hostname or ""
        started, started_at = self._clock(), self._now()
        error: FetchError | None = None
        wait: float | None = None
        for attempt in range(self._retries + 1):
            if attempt:
                delay = 2.0 ** (attempt - 1) if wait is None else wait
                if delay > 0:
                    self._sleep(delay)
            wait = None
            self._wait_turn(host)
            try:
                response = self._once(method, url, data)
            except httpx.TimeoutException:
                error = FetchError(url, "web_timeout")
                continue
            except httpx.TransportError as exc:
                error = FetchError(url, "web_network", detail=type(exc).__name__)
                continue
            except httpx.RequestError as exc:
                error = FetchError(url, "web_network", detail=type(exc).__name__)
                continue
            except _TooLarge:
                error = FetchError(url, "web_too_large")
                break
            except _TooManyRedirects:
                error = FetchError(url, "web_network", detail="too_many_redirects")
                break
            if response.status >= 500:
                error = FetchError(url, "web_http_5xx", response.status)
                continue
            if response.status in _TRANSIENT_4XX:
                error = FetchError(url, "web_http_4xx", response.status)
                wait = _retry_after(response.retry_after)
                continue
            if response.status in (401, 403):
                error = FetchError(url, "web_auth_required", response.status)
                break
            if response.status >= 400:
                error = FetchError(url, "web_http_4xx", response.status)
                break
            self._emit(method, url, started, started_at, response=response)
            return response
        assert error is not None
        self._emit(method, url, started, started_at, error=error)
        raise error

    def _once(self, method: str, url: str, data: dict[str, str] | None) -> Response:
        """Gửi một request và tự theo redirect; mỗi chặng đi qua giới hạn tốc độ của host đích."""
        current, redirects = url, 0
        while True:
            with self._client.stream(method, current, data=data) as raw:
                location = raw.headers.get("location")
                if raw.status_code in _REDIRECT_STATUSES and location:
                    if redirects == _MAX_REDIRECTS:
                        raise _TooManyRedirects
                    redirects += 1
                    if raw.status_code in (301, 302, 303) and method == "POST":
                        method, data = "GET", None
                    current = urljoin(current, location)
                    self._wait_turn(urlsplit(current).hostname or "")
                    continue
                if raw.status_code >= 400:  # quyết theo mã trạng thái, không đọc thân trang lỗi
                    return Response(
                        url=url,
                        final_url=current,
                        status=raw.status_code,
                        content_type=raw.headers.get("content-type", "").lower(),
                        content=b"",
                        retry_after=raw.headers.get("retry-after"),
                    )
                declared = raw.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self._max_bytes:
                    raise _TooLarge
                chunks, size = [], 0
                for chunk in raw.iter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise _TooLarge
                    chunks.append(chunk)
                return Response(
                    url=url,
                    final_url=current,
                    status=raw.status_code,
                    content_type=raw.headers.get("content-type", "").lower(),
                    content=b"".join(chunks),
                )

    def _emit(self, method, url, started, started_at, *, response=None, error=None) -> None:
        if self._on_fetch is None:
            return
        self._on_fetch(
            FetchEvent(
                url=url,
                method=method,
                source=self._source,
                http_status=response.status if response else error.status,
                error_cause=None if response else error.cause,
                duration_ms=int((self._clock() - started) * 1000),
                sha256=hashlib.sha256(response.content).hexdigest() if response else None,
                bytes=len(response.content) if response else None,
                at=started_at,
            )
        )
