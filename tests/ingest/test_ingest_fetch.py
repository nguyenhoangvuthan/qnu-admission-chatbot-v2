from datetime import UTC, datetime

import httpx
import pytest

from qnuchat.ingest.fetch import Fetcher, FetchError


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.t += seconds


def make(handler, *, max_bytes=1000, retries=2, rps=1, now=None):
    clock, events = FakeClock(), []
    fetcher = Fetcher(
        user_agent="QNU-bot (lien he a@b.vn)",
        rps_per_host=rps,
        timeout_s=5,
        max_bytes=max_bytes,
        retries=retries,
        transport=httpx.MockTransport(handler),
        clock=clock.now,
        sleep=clock.sleep,
        on_fetch=events.append,
        **({} if now is None else {"now": now}),
    )
    return fetcher, clock, events


def ok(request):
    return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>ok</html>")


def test_sends_the_user_agent_and_reports_an_event_with_sha():
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return ok(request)

    fetcher, _, events = make(handler)
    response = fetcher.get("https://www.qnu.edu.vn/vi/a")
    assert response.status == 200 and response.content == b"<html>ok</html>"
    assert seen == ["QNU-bot (lien he a@b.vn)"]
    (event,) = events
    assert event.http_status == 200 and event.error_cause is None and event.source == "crawl"
    assert event.bytes == 15 and len(event.sha256) == 64


def test_same_host_waits_one_second_other_hosts_do_not():
    fetcher, clock, _ = make(ok)
    fetcher.get("https://www.qnu.edu.vn/a")
    fetcher.get("https://kcntt.qnu.edu.vn/a")
    fetcher.get("https://www.qnu.edu.vn/b")
    assert clock.sleeps == [1.0]


def test_5xx_is_retried_with_backoff_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else ok(request)

    fetcher, clock, events = make(handler, rps=1000)
    assert fetcher.get("https://www.qnu.edu.vn/a").status == 200
    assert len(calls) == 2 and clock.sleeps == [1.0]
    assert [e.http_status for e in events] == [200]


def test_5xx_after_all_retries_raises_web_http_5xx():
    fetcher, _, events = make(lambda r: httpx.Response(500))
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/a")
    assert info.value.cause == "web_http_5xx" and info.value.status == 500
    assert events[-1].error_cause == "web_http_5xx"


@pytest.mark.parametrize(
    ("status", "cause"),
    [(404, "web_http_4xx"), (403, "web_auth_required"), (401, "web_auth_required")],
)
def test_4xx_is_not_retried(status, cause):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    fetcher, _, _ = make(handler)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/a")
    assert info.value.cause == cause and info.value.status == status and len(calls) == 1


def test_timeout_and_network_errors_have_their_own_causes():
    def timeout(request):
        raise httpx.ReadTimeout("chậm", request=request)

    def network(request):
        raise httpx.ConnectError("không kết nối", request=request)

    for handler, cause in ((timeout, "web_timeout"), (network, "web_network")):
        fetcher, _, _ = make(handler, retries=0)
        with pytest.raises(FetchError) as info:
            fetcher.get("https://www.qnu.edu.vn/a")
        assert info.value.cause == cause


def test_body_over_the_limit_is_refused():
    fetcher, _, _ = make(lambda r: httpx.Response(200, content=b"x" * 2000), max_bytes=1000)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/big.pdf")
    assert info.value.cause == "web_too_large"


def test_post_form_sends_urlencoded_fields():
    bodies = []

    def handler(request):
        bodies.append((request.method, request.headers["content-type"], request.content))
        return ok(request)

    fetcher, _, _ = make(handler)
    fetcher.post_form(
        "https://www.qnu.edu.vn/vi/cat", {"__EVENTTARGET": "ctl$lbtNext", "__VIEWSTATE": "a b"}
    )
    method, ctype, body = bodies[0]
    assert method == "POST" and ctype.startswith("application/x-www-form-urlencoded")
    assert b"__EVENTTARGET=ctl%24lbtNext" in body and b"__VIEWSTATE=a+b" in body


def test_redirects_are_followed_and_final_url_reported():
    def handler(request):
        if request.url.path == "/vi/quan-tri":
            return httpx.Response(302, headers={"location": "https://www.qnu.edu.vn/Login.aspx"})
        return ok(request)

    fetcher, _, _ = make(handler)
    response = fetcher.get("https://www.qnu.edu.vn/vi/quan-tri")
    assert response.final_url == "https://www.qnu.edu.vn/Login.aspx"


def test_other_httpx_request_errors_become_web_network_with_one_event():
    def handler(request):
        raise httpx.DecodingError("hỏng", request=request)

    fetcher, _, events = make(handler)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/a")
    assert info.value.cause == "web_network" and info.value.detail == "DecodingError"
    assert len(events) == 1 and events[0].error_cause == "web_network"


def test_cross_host_redirect_waits_for_the_target_hosts_slot():
    def handler(request):
        if request.url.host == "www.qnu.edu.vn":
            return httpx.Response(302, headers={"location": "https://drive.google.com/x"})
        return ok(request)

    fetcher, clock, _ = make(handler)
    fetcher.get("https://drive.google.com/first")
    response = fetcher.get("https://www.qnu.edu.vn/a")
    assert clock.sleeps == [1.0]
    assert response.url == "https://www.qnu.edu.vn/a"
    assert response.final_url == "https://drive.google.com/x"


def test_redirect_loop_is_cut_off_after_ten_hops():
    def handler(request):
        return httpx.Response(302, headers={"location": str(request.url)})

    fetcher, _, events = make(handler)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/loop")
    assert info.value.cause == "web_network" and info.value.detail == "too_many_redirects"
    assert len(events) == 1 and events[0].error_cause == "web_network"


def test_post_answered_with_302_is_followed_as_get():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(302, headers={"location": "/vi/ket-qua"})
        return ok(request)

    fetcher, _, _ = make(handler)
    fetcher.post_form("https://www.qnu.edu.vn/vi/cat", {"a": "1"})
    assert seen == [("POST", "/vi/cat"), ("GET", "/vi/ket-qua")]


@pytest.mark.parametrize("status", [429, 408])
def test_429_and_408_are_retried_like_5xx(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status) if len(calls) == 1 else ok(request)

    fetcher, clock, _ = make(handler, rps=1000)
    assert fetcher.get("https://www.qnu.edu.vn/a").status == 200
    assert len(calls) == 2 and clock.sleeps == [1.0]


@pytest.mark.parametrize("status", [429, 408])
def test_429_and_408_after_all_retries_raise_web_http_4xx(status):
    fetcher, _, events = make(lambda r: httpx.Response(status), retries=1)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/a")
    assert info.value.cause == "web_http_4xx" and info.value.status == status
    assert events[-1].error_cause == "web_http_4xx" and events[-1].http_status == status


@pytest.mark.parametrize(("header", "waited"), [("5", 5.0), ("100", 30.0), ("0", 0.001)])
def test_retry_after_seconds_replace_the_backoff_capped_at_30(header, waited):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": header})
        return ok(request)

    fetcher, clock, _ = make(handler, rps=1000)
    assert fetcher.get("https://www.qnu.edu.vn/a").status == 200
    assert clock.sleeps == [waited]  # 0.001 là chờ giới hạn tốc độ, không phải backoff


def test_retry_after_that_is_not_a_number_falls_back_to_backoff():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
        return ok(request)

    fetcher, clock, _ = make(handler, rps=1000)
    fetcher.get("https://www.qnu.edu.vn/a")
    assert clock.sleeps == [1.0]


def test_error_status_is_decided_before_the_body_is_read():
    fetcher, _, _ = make(lambda r: httpx.Response(404, content=b"x" * 5000), max_bytes=1000)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/khong-co")
    assert info.value.cause == "web_http_4xx" and info.value.status == 404


def test_body_without_content_length_is_counted_while_streaming():
    def handler(request):
        return httpx.Response(200, content=iter([b"x" * 600, b"x" * 600]))

    fetcher, _, _ = make(handler, max_bytes=1000)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://www.qnu.edu.vn/big.pdf")
    assert info.value.cause == "web_too_large"


def test_event_carries_the_utc_time_the_request_started():
    stamps = iter(
        [datetime(2026, 10, 12, 1, 0, tzinfo=UTC), datetime(2026, 10, 12, 2, 0, tzinfo=UTC)]
    )
    fetcher, _, events = make(ok, now=lambda: next(stamps))
    fetcher.get("https://www.qnu.edu.vn/a")
    assert events[0].at == datetime(2026, 10, 12, 1, 0, tzinfo=UTC)


def test_default_event_time_is_timezone_aware_utc():
    fetcher, _, events = make(ok)
    fetcher.get("https://www.qnu.edu.vn/a")
    assert events[0].at.utcoffset().total_seconds() == 0
