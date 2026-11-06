"""Một lần quét web trường (spec §6.2): BFS theo link trong `*.qnu.edu.vn`, lật trang postback,
tải đính kèm, lọc danh sách người TRƯỚC khi lưu, ghi blob + manifest chỉ-thêm.

Song song theo host: tối đa `hosts_parallel` luồng, mỗi host chỉ một luồng tại một thời điểm,
nên `rps_per_host` của Fetcher giữ đúng nhịp với site. Lỗi tạm (timeout, 5xx, mạng) chỉ đếm
`errors` và vào `fetch_log` qua callback của Fetcher; manifest chỉ ghi trạng thái tài liệu
(lệch spec L4 trong plan 1).
"""

import hashlib
import logging
import re
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.robotparser import RobotFileParser

from qnuchat.ingest import drive, extract, favicon, pii
from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.config import CrawlConfig
from qnuchat.ingest.dating import infer_year, is_before
from qnuchat.ingest.fetch import Fetcher, FetchError, Response
from qnuchat.ingest.frontier import Frontier
from qnuchat.ingest.html_page import ParsedPage, parse_page
from qnuchat.ingest.manifest import Manifest, ManifestEntry
from qnuchat.ingest.state import CheckState
from qnuchat.ingest.topic import TopicFilter
from qnuchat.ingest.urls import (
    canonicalize,
    classify_link,
    drive_canonical,
    drive_file_id,
    host_of,
    in_scope,
    is_child,
    source_id_for,
    tier_for,
)

logger = logging.getLogger(__name__)

HUB_MIN_CHILDREN = 3
MIN_IMAGE_SIDE = 200
_LOGIN_URL = re.compile(r"(login|dang-?nhap|sign-?in|servicelogin)", re.IGNORECASE)
_COUNTED = frozenset({"page", "file", "image"})
_ERROR_PAGE_URL = re.compile(r"genericerrorpage", re.IGNORECASE)
ROBOTS_AGENT = "QNU-admission-chatbot"  # token đầu của user_agent trong configs/crawl/qnu.yaml
# Lưu last_checked.json và frontier.jsonl sau mỗi chừng ấy lần ghi kiểm (chết giữa chừng).
SAVE_STATE_EVERY = 200
JOIN_POLL_S = 0.2  # luồng chính chờ worker theo nhịp này để kịp xử lý SIGINT/SIGTERM
SOFT_404_MISSES = 2  # trang luôn tải chỉ coi là đã gỡ khi thấy trang lỗi mềm ngần ấy lần liền
# Đính kèm Drive chuyển giữa các host này là bình thường (uc → usercontent), không phải ra ngoài.
_DRIVE_HOSTS = frozenset({"drive.google.com", "drive.usercontent.google.com", "docs.google.com"})
# …và file Drive có thể được phục vụ từ doc-*-docs.googleusercontent.com.
_DRIVE_HOST_SUFFIX = ".googleusercontent.com"


def _is_drive_host(host: str) -> bool:
    return host in _DRIVE_HOSTS or host.endswith(_DRIVE_HOST_SUFFIX)


@dataclass
class CrawlStats:
    pages_new: int = 0
    pages_changed: int = 0
    files_new: int = 0
    files_changed: int = 0
    skipped_pii: int = 0
    auth_required: int = 0
    needs_ocr: int = 0
    errors: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Page:
    url: str
    published: date | None = None


@dataclass(frozen=True)
class _Asset:
    url: str
    kind: str  # file | image | drive_file
    page_url: str
    tier: str
    title: str | None
    published: date | None


def _item_to_row(item: _Page | _Asset) -> dict:
    published = item.published.isoformat() if item.published else None
    if isinstance(item, _Page):
        return {"type": "page", "url": item.url, "published": published}
    return {
        "type": "asset",
        "url": item.url,
        "kind": item.kind,
        "page_url": item.page_url,
        "tier": item.tier,
        "title": item.title,
        "published": published,
    }


def _item_from_row(row: dict) -> _Page | _Asset:
    """Ném KeyError/ValueError/TypeError với dòng thiếu trường hay sai kiểu."""
    published = date.fromisoformat(row["published"]) if row.get("published") else None
    if row["type"] == "page":
        return _Page(str(row["url"]), published)
    if row["type"] == "asset":
        return _Asset(
            str(row["url"]),
            str(row["kind"]),
            str(row["page_url"]),
            str(row["tier"]),
            row.get("title"),
            published,
        )
    raise ValueError(f"loại mục lạ: {row['type']!r}")


@dataclass(frozen=True)
class CrawlProgress:
    """Ảnh chụp sau mỗi mục, cho `on_progress`: `queued` tăng khi trang mới lộ thêm link."""

    done: int
    queued: int
    pages_new: int
    files_new: int
    errors: int


class Crawler:
    def __init__(
        self,
        cfg: CrawlConfig,
        *,
        config_hash: str,
        run_id: str,
        fetcher: Fetcher,
        manifest: Manifest,
        blobs: BlobStore,
        state: CheckState,
        sources_index: Mapping[str, str],
        today: date,
        now: Callable[[], datetime],
        frontier: Frontier | None = None,
        on_progress: Callable[[CrawlProgress], None] | None = None,
    ):
        self.cfg, self.config_hash, self.run_id = cfg, config_hash, run_id
        self.fetcher, self.manifest, self.blobs, self.state = fetcher, manifest, blobs, state
        self.frontier = frontier
        self.on_progress = on_progress
        self._done = 0
        self.sources_index, self.today, self.now = sources_index, today, now
        self.stats = CrawlStats()
        aliases = cfg.host_aliases
        self._aliases = aliases
        self._topic = TopicFilter(cfg.topic_gate, aliases)
        self._tier_a = [u for u in (canonicalize(x, aliases=aliases) for x in cfg.tier_a) if u]
        self._always = {u for u in (canonicalize(x, aliases=aliases) for x in cfg.seeds) if u}
        self._always |= set(self._tier_a)
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._queues: dict[str, deque] = {}
        self._active: set[str] = set()
        self._inflight: dict[str, _Page | _Asset] = {}  # host → mục đang tải dở
        self._stopping = False
        self._workers: list[threading.Thread] = []
        self._checkpoint_lock = threading.Lock()
        self._last_host: str | None = None  # host được chọn lần trước (con trỏ vòng)
        self._seen: set[tuple[str, str]] = set()
        self._favicon_done: set[str] = set()
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_locks: dict[str, threading.Lock] = {}
        self._marks = 0

    # ------------------------------------------------------------------ điều phối

    def run(self) -> CrawlStats:
        # Hạt giống tầng A vào hàng đợi trước: host của chúng đứng đầu vòng xoay.
        seeds = sorted(self._always, key=lambda u: (tier_for(u, self._tier_a) != "A", u))
        for url in seeds:
            self._enqueue(_Page(url))
        # Hàng đợi của lần quét trước bị dừng: link chỉ thấy trên trang đã tải (bài thường, không
        # phải hub) sẽ không ai tìm lại, vì trang đó chưa tới hạn kiểm lại.
        for item in self._load_frontier():
            self._enqueue(item)
        self._workers = [
            threading.Thread(target=self._worker, name=f"crawl-{i}", daemon=True)
            for i in range(self.cfg.limits.hosts_parallel)
        ]
        for worker in self._workers:
            worker.start()
        try:
            self._wait_workers()
        except BaseException:
            # Ctrl-C (SIGTERM được apps.crawler đổi thành Ctrl-C): ghi điểm dừng rồi ném lại để
            # job đóng run 'failed'. Worker đang tải dở là daemon, chết theo tiến trình; mục của
            # chúng đã nằm trong điểm dừng.
            with self._cv:
                self._stopping = True
                self._cv.notify_all()
            self._checkpoint()
            raise
        self.state.save()
        if self.frontier is not None:
            self.frontier.clear()
        self.stats.warnings.sort()
        return self.stats

    def _wait_workers(self) -> None:
        """join có hạn giờ: luồng chính thức dậy đều đặn để chạy handler tín hiệu, dù kernel
        giao tín hiệu cho luồng nào."""
        for worker in self._workers:
            while worker.is_alive():
                worker.join(JOIN_POLL_S)

    def join_workers(self, timeout: float = 10.0) -> None:
        """Chờ worker thoát sau khi dừng (cho test; tiến trình thật thì thoát luôn)."""
        for worker in self._workers:
            worker.join(timeout)

    def _load_frontier(self) -> list[_Page | _Asset]:
        """Mục không còn hợp lệ với cấu hình hiện tại (đổi phạm vi, blocklist) bị bỏ."""
        if self.frontier is None:
            return []
        items: list[_Page | _Asset] = []
        for row in self.frontier.load():
            try:
                item = _item_from_row(row)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("frontier_line_dropped %r: %s", row, exc)
                continue
            expected = "page" if isinstance(item, _Page) else item.kind
            if classify_link(item.url, self.cfg) != expected:
                logger.warning("frontier_line_dropped %s: ngoài phạm vi cấu hình mới", item.url)
                continue
            items.append(item)
        return items

    def _checkpoint(self) -> None:
        """Lưu state rồi mới chụp hàng đợi. Theo thứ tự này, trang có trong state đã đưa link con
        vào hàng đợi trước khi ghi kiểm, nên link con hoặc nằm trong ảnh chụp (kể cả mục đang tải
        dở), hoặc đã tải xong. Mục xong giữa hai bước chỉ thiếu dấu kiểm: lần sau tải lại, không
        sót."""
        with self._checkpoint_lock:
            self.state.save()
            if self.frontier is None:
                return
            with self._cv:
                items = list(self._inflight.values())
                for queue in self._queues.values():
                    items.extend(queue)
            self.frontier.save(_item_to_row(item) for item in items)

    def _enqueue(self, item: _Page | _Asset) -> None:
        key = (type(item).__name__, item.url)
        with self._cv:
            if key in self._seen:
                return
            self._seen.add(key)
            self._queues.setdefault(host_of(item.url), deque()).append(item)
            self._cv.notify_all()

    def _next_host(self) -> str | None:
        """Xoay vòng: duyệt từ sau host được chọn lần trước để host đứng sau không bị bỏ đói.
        Gọi dưới `self._cv`."""
        hosts = list(self._queues)
        start = hosts.index(self._last_host) + 1 if self._last_host in self._queues else 0
        for host in hosts[start:] + hosts[:start]:
            if self._queues[host] and host not in self._active:
                self._last_host = host
                return host
        return None

    def _worker(self) -> None:
        while True:
            with self._cv:
                host = None if self._stopping else self._next_host()
                while host is None:
                    if self._stopping or (not self._active and not any(self._queues.values())):
                        self._cv.notify_all()
                        return
                    self._cv.wait()
                    host = self._next_host()
                item = self._queues[host].popleft()
                self._active.add(host)
                self._inflight[host] = item
            try:
                if isinstance(item, _Page):
                    self._crawl_page(item)
                else:
                    self._crawl_asset(item)
            except Exception:
                logger.exception("crawl_item_failed %s", item.url)
                with self._lock:
                    self.stats.errors += 1
            finally:
                with self._cv:
                    self._active.discard(host)
                    self._inflight.pop(host, None)
                    self._done += 1
                    self._report_progress()
                    self._cv.notify_all()

    def _report_progress(self) -> None:
        """Gọi dưới `self._cv`: `done` tăng đúng thứ tự dù nhiều worker."""
        if self.on_progress is None:
            return
        self.on_progress(
            CrawlProgress(
                done=self._done,
                queued=sum(map(len, self._queues.values())),
                pages_new=self.stats.pages_new,
                files_new=self.stats.files_new,
                errors=self.stats.errors,
            )
        )

    # ------------------------------------------------------------------ robots.txt

    def _robots_allow(self, url: str) -> bool:
        """robots.txt của host thuộc site trường (spec §6.2 bước 1): đọc một lần mỗi host mỗi
        lần quét, tuân theo luật cho `ROBOTS_AGENT` và `*`. Không có, lỗi, hay trả trang HTML
        (trang lỗi mềm) thì cho phép hết. Host ngoài site (Drive) không xét: file trường đã
        link vẫn tải (spec §4.1)."""
        host = host_of(url)
        if not in_scope(f"https://{host}/", self.cfg):
            return True
        with self._lock:
            host_lock = self._robots_locks.setdefault(host, threading.Lock())
        with host_lock:
            if host not in self._robots:
                self._robots[host] = self._load_robots(host)
            rules = self._robots[host]
        return rules is None or rules.can_fetch(ROBOTS_AGENT, url)

    def _load_robots(self, host: str) -> RobotFileParser | None:
        try:
            response = self.fetcher.get(f"https://{host}/robots.txt")
        except FetchError:
            return None
        # Text thuần mới là robots.txt; trang HTML (lỗi mềm), PDF, ảnh… thì coi như không có.
        if response.content_type.startswith("text/html") or extract.sniff(response.content) != (
            "unknown"
        ):
            return None
        rules = RobotFileParser()
        rules.parse(response.content.decode("utf-8", errors="replace").splitlines())
        return rules

    # ------------------------------------------------------------------ trang

    def _crawl_page(self, item: _Page) -> None:
        url = item.url
        if not self._robots_allow(url):
            self._robots_blocked(url)
            return
        if self._off_topic(url):
            return
        always = url in self._always or self.state.is_hub(url)
        # Mọi URL đã ghi kiểm (kể cả không lưu gì: chuyển ra ngoài, link hỏng…) chờ recheck_days.
        if not always and not self.state.due(url, self.today, self.cfg.limits.recheck_days):
            return
        try:
            response = self.fetcher.get(url)
        except FetchError as exc:
            self._fetch_failed(url, exc, kind="page", page_url=None, title=None)
            return
        if _ERROR_PAGE_URL.search(response.final_url):
            # Site chuyển bài đã gỡ tới trang lỗi chung (dù URL đó bị chặn, ngoài phạm vi quét).
            self._not_found(url, always=always)
            return
        if self._redirected_away(url, response, kind="page", page_url=None, title=None):
            return
        if extract.sniff(response.content) != "html":
            if not always and self._too_old(url, None, item.published):
                self._out_of_range(url)
                return
            asset = _Asset(url, "file", url, tier_for(url, self._tier_a), None, item.published)
            self._store_asset(asset, response)
            self._mark(url)
            return
        # Link tương đối tính theo URL sau chuyển hướng; khoá manifest vẫn là URL đã yêu cầu.
        base = response.final_url
        page = parse_page(response.content, base, aliases=self._aliases)
        if page.login_form:
            self._record(
                url, kind="page", page_url=None, status="auth_required", reason="password_form"
            )
            self._mark(url)
            return
        tier = tier_for(url, self._tier_a)
        children = [link for link in page.links if is_child(link.url, base)]
        hub = len(children) >= HUB_MIN_CHILDREN or page.pager_next is not None
        if page.main_text_len == 0 and not page.links:
            # Trang lỗi mềm (HTTP 200, không có <body>) hay trang trắng: như 404.
            self._not_found(url, always=always)
            return
        published = item.published or page.published
        # Hạt giống và trang hub (chuyên mục) không bị loại theo năm: chúng dẫn tới bài mới.
        if not always and not hub and self._too_old(url, page.title, published):
            self._out_of_range(url)
            return
        # Chỉ cảnh báo khi trang mới trống: lần đầu thấy, hoặc lần kiểm trước nó còn là hub.
        if (
            url in self._tier_a
            and not children
            and (not self.state.known(url) or self.state.is_hub(url))
        ):
            with self._lock:
                self.stats.warnings.append(f"tier_a_empty:{url}")
        reason = pii.title_skip(page.title, self.cfg.pii_title_skip)
        reason = reason or pii.detect(extract.extract_html(page.main_html), today=self.today)
        if reason:
            # Danh sách người: không khám phá link, ảnh, đính kèm hay lật trang của nó (W3).
            self._record(
                url,
                kind="page",
                page_url=None,
                status="skipped_pii",
                reason=reason,
                title=page.title,
            )
            self._mark(url)
            return
        # Trang ngoài chủ đề chỉ đến được khi là hạt giống: đọc link rồi thôi, không lưu.
        wanted = self._topic.allows(url, page.title)
        self._discover(url, page, published=published, wanted=wanted, hub=hub)
        if not wanted:
            self._mark(url, hub=hub)
            return
        self._paginate(url, page, base=base)
        self._store_bytes(
            url,
            kind="page",
            page_url=None,
            data=page.main_html.encode("utf-8"),
            mime="text/html",
            title=page.title,
            published=published,
            text_status="text",
            tier=tier,
        )
        # Ghi kiểm (và cờ hub) trước favicon: lỗi ở favicon không làm mất cờ hub.
        self._mark(url, hub=hub)
        self._favicon(url, page)

    def _discover(
        self,
        page_url: str,
        page: ParsedPage,
        *,
        published: date | None,
        wanted: bool = True,
        hub: bool = False,
    ) -> None:
        page_tier = tier_for(page_url, self._tier_a)
        # Thân bài đạt cổng: đính kèm và ảnh của nó thuộc chủ đề dù tên file chung chung. Trang
        # danh sách thì không: ảnh ở đó là thumbnail, file ở đó phải tự đạt cổng theo tiêu đề.
        article = wanted and not (hub and self._topic.active)
        blocked: set[str] = set()
        for link in page.links:
            if classify_link(link.url, self.cfg) != "page" or not link.text:
                continue
            reason = pii.title_skip(link.text, self.cfg.pii_title_skip)
            if reason:
                blocked.add(link.url)
                self._record(
                    link.url,
                    kind="page",
                    page_url=page_url,
                    status="skipped_pii",
                    reason=reason,
                    title=link.text,
                )
        for link in page.links:
            kind = classify_link(link.url, self.cfg)
            if kind == "page":
                if link.url in blocked:  # `blocked` chỉ có URL loại "page" (vòng trên)
                    continue
                latest = self.manifest.latest(link.url)
                if latest is not None and latest.text_status == "skipped_pii":
                    continue
                if link.url not in self._always and self._too_old(link.url, link.text, link.date):
                    continue
                if link.url not in self._always and not self._topic.allows(link.url, link.text):
                    continue
                self._enqueue(_Page(link.url, link.date))
            elif kind in ("file", "drive_file"):
                # Một file Drive một URL, dù link mang `usp=sharing`, `usp=drive_link`…
                url = drive_canonical(link.url) if kind == "drive_file" else link.url
                if self._too_old(url, link.text, link.date or published, parent_url=page_url):
                    continue
                if self._topic.excluded(url, link.text) or not (
                    (article and link.in_main) or self._topic.allows(url, link.text)
                ):
                    continue
                tier = "A" if "A" in (page_tier, tier_for(url, self._tier_a)) else "B"
                self._enqueue(
                    _Asset(url, kind, page_url, tier, link.text or None, link.date or published)
                )
            elif kind == "drive_folder":
                self._record(
                    link.url,
                    kind="file",
                    page_url=page_url,
                    status="auth_required",
                    reason="drive_folder",
                    title=link.text or None,
                )
        for src in page.images if article else ():
            if self._topic.excluded(src):
                continue
            if classify_link(src, self.cfg) == "image" and not self._too_old(
                src, None, published, parent_url=page_url
            ):
                self._enqueue(_Asset(src, "image", page_url, page_tier, None, published))

    def _paginate(self, url: str, page: ParsedPage, *, base: str) -> None:
        """`base`: URL sau chuyển hướng của chuyên mục — gốc để nhận bài con.

        Dừng khi một trang không có bài con nào mới so với các trang đã lật của chính chuyên mục
        này và manifest. Không dùng `_seen` chung: luồng/trang khác enqueue trước một bài ở trang
        sau không được làm dừng lật sớm."""
        pager, pages = page.pager_next, 1
        seen = {link.url for link in page.links}
        while pager is not None and pages < self.cfg.limits.max_listing_pages:
            form = {**pager.fields, "__EVENTTARGET": pager.target, "__EVENTARGUMENT": ""}
            try:
                response = self.fetcher.post_form(pager.action, form)
            except FetchError:
                with self._lock:
                    self.stats.errors += 1
                return
            following = parse_page(response.content, response.final_url, aliases=self._aliases)
            new = [
                link
                for link in following.links
                if is_child(link.url, base)
                and classify_link(link.url, self.cfg) == "page"
                and link.url not in seen
                and self.manifest.latest(link.url) is None
            ]
            seen.update(link.url for link in following.links)
            self._discover(url, following, published=None, hub=True)
            if not new:
                return
            # Danh sách xếp mới trước: cả trang toàn bài cũ hơn mốc thì các trang sau cũng vậy.
            if all(self._too_old(link.url, link.text, link.date) for link in new):
                return
            pager, pages = following.pager_next, pages + 1

    # ------------------------------------------------------------------ đính kèm

    def _crawl_asset(self, item: _Asset) -> None:
        if not self._robots_allow(item.url):
            self._robots_blocked(item.url)
            return
        if self._off_topic(item.url):
            return
        if not self.state.due(item.url, self.today, self.cfg.limits.recheck_days):
            return
        # Mục từ hàng đợi đã lưu hay từ trang chưa có ngày: xét lại năm trước khi tải.
        if self._too_old(item.url, item.title, item.published, parent_url=item.page_url):
            self._out_of_range(item.url)
            return
        try:
            if item.kind == "drive_file":
                response = drive.fetch_file(self.fetcher, drive_file_id(item.url))
            else:
                response = self.fetcher.get(item.url)
        except FetchError as exc:
            self._fetch_failed(item.url, exc, kind="file", page_url=item.page_url, title=item.title)
            return
        if self._redirected_away(
            item.url, response, kind="file", page_url=item.page_url, title=item.title
        ):
            return
        self._store_asset(item, response)
        self._mark(item.url)

    def _store_asset(self, item: _Asset, response: Response) -> None:
        data = response.content
        kind = extract.sniff(data)
        common = {"page_url": item.page_url, "title": item.title}
        if kind == "html":
            # File đã có mà nay trả trang HTML (trang lỗi mềm của site): file đã bị gỡ.
            latest = self.manifest.latest(item.url)
            reason = "gone" if latest is not None and latest.usable else "not_a_file"
            self._record(item.url, kind="file", status="failed", reason=reason, **common)
            return
        if kind == "unknown":
            self._record(
                item.url, kind="file", status="failed", reason="unsupported_format", **common
            )
            return
        if kind == "image":
            if min(extract.image_size(data)) < MIN_IMAGE_SIDE:
                return
            self._store_bytes(
                item.url,
                kind="image",
                data=data,
                mime=extract.mime_of(data, kind),
                published=item.published,
                text_status="needs_ocr",
                tier=item.tier,
                quarantine=True,
                **common,
            )
            return
        try:
            extracted = extract.extract(kind, data)
        except extract.ExtractError:
            self._record(item.url, kind="file", status="failed", reason="extract_failed", **common)
            return
        reason = pii.title_skip(item.title or "", self.cfg.pii_title_skip)
        reason = reason or pii.detect(extracted, today=self.today)
        if reason:
            self._record(item.url, kind="file", status="skipped_pii", reason=reason, **common)
            return
        needs_ocr = bool(extracted.scanned_pages)
        self._store_bytes(
            item.url,
            kind="file",
            data=data,
            mime=extract.mime_of(data, kind),
            published=item.published,
            text_status="needs_ocr" if needs_ocr else "text",
            tier=item.tier,
            quarantine=needs_ocr,
            **common,
        )

    def _favicon(self, url: str, page: ParsedPage) -> None:
        host = host_of(url)
        with self._lock:
            if host in self._favicon_done:
                return
            self._favicon_done.add(host)
        if self.manifest.favicon(host) is not None and not self.state.due(
            f"favicon:{host}", self.today, self.cfg.limits.recheck_days
        ):
            return
        for candidate in favicon.candidates(page.icon_href, url):
            if not self._robots_allow(candidate):
                continue
            try:
                response = self.fetcher.get(candidate)
            except FetchError:
                continue
            png = favicon.to_png(response.content)
            if png is None:
                continue
            self._store_bytes(
                candidate,
                kind="favicon",
                page_url=url,
                data=png,
                mime="image/png",
                title=None,
                published=None,
                text_status="text",
                tier="A",
                host=host,
            )
            self._mark(f"favicon:{host}")
            return

    # ------------------------------------------------------------------ mốc năm

    def _off_topic(self, url: str) -> bool:
        """Bộ lọc chủ đề, lọc ảnh người hay người vận hành (`apps.cli.ocr remove`) đã rút
        mục này: không tải lại để lưu lại rồi lại bị rút ở mỗi chu kỳ kiểm. Muốn đưa về kho thì sửa
        quyết định trong sổ tương ứng."""
        latest = self.manifest.latest(url)
        removed = ("off_topic", "people_photo", "operator_removed")
        return latest is not None and latest.reason in removed

    def _too_old(
        self,
        url: str,
        title: str | None,
        published: date | None,
        *,
        parent_url: str | None = None,
    ) -> bool:
        """Biết chắc năm < `min_year` (spec §6.5). `published` của ảnh/file đã là ngày của
        trang chứa nó khi không có ngày riêng. Không suy được năm thì giữ."""
        if self.cfg.min_year is None:
            return False
        year = infer_year(
            url=url, title=title, published=published, today=self.today, parent_url=parent_url
        )
        return is_before(year, self.cfg.min_year)

    def _out_of_range(self, url: str) -> None:
        """Không lưu; bản đã lưu thì rút khỏi kho (blob xoá bằng lệnh `prune`). Ghi kiểm để
        chờ `recheck_days`, không tải lại mỗi lần quét."""
        latest = self.manifest.latest(url)
        if latest is not None and latest.usable:
            self._record(
                url,
                kind=latest.kind,
                page_url=latest.page_url,
                status="failed",
                reason="out_of_range",
                title=latest.title,
            )
        self._mark(url)

    # ------------------------------------------------------------------ ghi kho

    def _mark(self, url: str, *, hub: bool | None = None) -> None:
        self.state.mark(url, self.today, hub=hub)
        self._count_mark()

    def _count_mark(self) -> None:
        """Lưu state và hàng đợi định kỳ: tiến trình chết giữa lần quét dài không mất hết lịch
        kiểm, cũng không mất link đã thấy mà chưa tải."""
        with self._lock:
            self._marks += 1
            save = self._marks % SAVE_STATE_EVERY == 0
        if save:
            self._checkpoint()

    def _redirected_away(
        self, url: str, response: Response, *, kind: str, page_url: str | None, title: str | None
    ) -> bool:
        """Xử lý chuyển hướng không dùng được nội dung; True nếu đã xử lý xong `url`.

        Sang trang đăng nhập → `auth_required`/`login_redirect`. Ra ngoài phạm vi (Fetcher không
        kiểm phạm vi; đính kèm được phép đi giữa các host Drive) → không lưu, không tính lỗi.
        Sang URL trong phạm vi mà robots.txt chặn → như URL bị chặn."""
        final = response.final_url
        if final == response.url:
            return False
        # Đính kèm: tên file có chữ "dang-nhap" (huong-dan-dang-nhap-xet-tuyen.pdf) không phải
        # trang đăng nhập; chỉ HTML mới tính.
        login_url = bool(_LOGIN_URL.search(final)) and (
            kind == "page" or extract.sniff(response.content) == "html"
        )
        if login_url or host_of(final) == "accounts.google.com":
            self._record(
                url,
                kind=kind,
                page_url=page_url,
                status="auth_required",
                reason="login_redirect",
                title=title,
            )
        elif not in_scope(final, self.cfg):
            if kind != "page" and _is_drive_host(host_of(final)):
                return False
            logger.info("redirect_out_of_scope %s -> %s", url, final)
        elif self._robots_allow(final):
            return False
        else:
            self._robots_blocked(url)
        self._mark(url)
        return True

    def _robots_blocked(self, url: str) -> None:
        """URL robots.txt chặn: đã có bản dùng được thì ghi `failed`/`robots_disallowed` để rút
        khỏi kho; chưa có thì bỏ qua, không tính lỗi."""
        latest = self.manifest.latest(url)
        if latest is not None and latest.usable:
            self._record(
                url,
                kind=latest.kind,
                page_url=latest.page_url,
                status="failed",
                reason="robots_disallowed",
            )

    def _not_found(self, url: str, *, always: bool) -> None:
        """Trang không còn (trang lỗi mềm hoặc trang lỗi chung): đã có bản dùng được thì ghi
        `failed`/`gone` để rút khỏi kho; chưa có thì bỏ qua, không tính lỗi.

        Trang luôn tải (hạt giống, tier A, hub) hay chập chờn trả trang lỗi mềm: chỉ ghi `gone`
        khi thấy `SOFT_404_MISSES` lần quét liền; lần trước đó chỉ đếm trong state."""
        if always:
            misses = self.state.miss(url, self.today)
            self._count_mark()
            if misses < SOFT_404_MISSES:
                return
        else:
            self._mark(url)
        latest = self.manifest.latest(url)
        if latest is not None and latest.usable:
            self._record(
                url, kind=latest.kind, page_url=latest.page_url, status="failed", reason="gone"
            )

    def _fetch_failed(
        self, url: str, exc: FetchError, *, kind: str, page_url: str | None, title: str | None
    ) -> None:
        """Lỗi vĩnh viễn (cần đăng nhập, 404/410, quá lớn) ghi kiểm để chờ `recheck_days`; 404/410
        của URL chưa từng lưu là link hỏng của site, không tính lỗi. Lỗi tạm (timeout, 5xx,
        mạng…) đếm `errors` và không ghi kiểm, lần quét sau thử lại."""
        latest = self.manifest.latest(url)
        if exc.cause == "web_auth_required":
            reason = exc.detail or f"http_{exc.status}"
            self._record(
                url,
                kind=kind,
                page_url=page_url,
                status="auth_required",
                reason=reason,
                title=title,
            )
        elif exc.cause == "web_http_4xx" and exc.status in (404, 410):
            if latest is not None and latest.usable:
                self._record(
                    url, kind=kind, page_url=page_url, status="failed", reason="gone", title=title
                )
        elif exc.cause == "web_too_large":
            self._record(
                url, kind=kind, page_url=page_url, status="failed", reason="too_large", title=title
            )
        else:
            with self._lock:
                self.stats.errors += 1
            return
        self._mark(url)

    def _entry(
        self,
        url: str,
        *,
        kind: str,
        page_url: str | None,
        title: str | None,
        published: date | None,
        sha256: str | None,
        mime: str | None,
        size: int | None,
        tier: str,
        text_status: str,
        reason: str | None,
        host: str | None = None,
    ) -> ManifestEntry:
        return ManifestEntry(
            url=url,
            source_id=source_id_for(url),
            page_url=page_url,
            kind=kind,
            title=title,
            published=published.isoformat() if published else None,
            retrieved_at=self.now().isoformat(timespec="seconds"),
            sha256=sha256,
            mime=mime,
            bytes=size,
            host=host or host_of(url),
            tier=tier,
            text_status=text_status,
            reason=reason,
            crawl_run=self.run_id,
            config_hash=self.config_hash,
            sources_yaml_ref=self.sources_index.get(sha256) if sha256 else None,
        )

    def _record(
        self,
        url: str,
        *,
        kind: str,
        page_url: str | None,
        status: str,
        reason: str,
        title: str | None = None,
    ) -> None:
        with self._lock:
            latest = self.manifest.latest(url)
            if latest is not None and latest.text_status == status and latest.reason == reason:
                return
            tier = tier_for(page_url or url, self._tier_a)
            self.manifest.append(
                self._entry(
                    url,
                    kind=kind,
                    page_url=page_url,
                    title=title,
                    published=None,
                    sha256=None,
                    mime=None,
                    size=None,
                    tier=tier,
                    text_status=status,
                    reason=reason,
                )
            )
            if status == "skipped_pii":
                self.stats.skipped_pii += 1
            elif status == "auth_required":
                self.stats.auth_required += 1

    def _store_bytes(
        self,
        url: str,
        *,
        kind: str,
        page_url: str | None,
        data: bytes,
        mime: str,
        title: str | None,
        published: date | None,
        text_status: str,
        tier: str,
        quarantine: bool = False,
        host: str | None = None,
    ) -> None:
        sha = hashlib.sha256(data).hexdigest()
        with self._lock:
            latest = self.manifest.latest(url)
            if latest is not None and latest.sha256 == sha:
                if self.blobs.path(sha) is None:
                    # Blob mất khỏi đĩa (quarantine không commit…): ghi lại, không thêm dòng.
                    self.blobs.put(data, tier=tier, quarantine=quarantine)
                return
            self.blobs.put(data, tier=tier, quarantine=quarantine)
            self.manifest.append(
                self._entry(
                    url,
                    kind=kind,
                    page_url=page_url,
                    title=title,
                    published=published,
                    sha256=sha,
                    mime=mime,
                    size=len(data),
                    tier=tier,
                    text_status=text_status,
                    reason=None,
                    host=host,
                )
            )
            if kind not in _COUNTED:
                return
            new = latest is None or not latest.usable
            if kind == "page":
                self.stats.pages_new += new
                self.stats.pages_changed += not new
            else:
                self.stats.files_new += new
                self.stats.files_changed += not new
            if text_status == "needs_ocr":
                self.stats.needs_ocr += 1
