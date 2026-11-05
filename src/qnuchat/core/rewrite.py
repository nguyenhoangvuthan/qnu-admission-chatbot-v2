"""Hiểu câu hỏi nối tiếp bằng quy tắc trên danh mục (spec chat nhiều lượt §4). Không gọi LLM.

Hàm thuần: cùng lịch sử + cùng danh mục → cùng kết quả, nên replay và test được. Trạng thái hội
thoại tính lại từ `Query.history` mỗi lượt, không lưu ở đâu khác (quyết định M7).
"""

import re
from dataclasses import dataclass
from typing import Any

from qnuchat.core.catalog import Catalog
from qnuchat.core.contracts import Clarification, Query
from qnuchat.core.text import fold

MAX_OPTIONS = 6
LIST_THRESHOLD = 3  # ≤ 3 ngành: trả lời liệt kê thay vì hỏi (quyết định M4)
_YEAR = re.compile(r"\b(20\d\d)\b")
YEAR_RANGE = range(2015, 2036)  # ngoài khoảng này là số lượng ("chỉ tiêu 2000"), không phải năm
# Thông tin không có sẵn trong câu nền thì ghép vào câu độc lập (§4 bước 8).
_APPENDED = ("inherited", "clarification")
# Câu có dấu hiệu hỏi (sau fold, khớp trọn từ) là câu hỏi mới, không phải câu trả lời câu treo.
QUESTION_MARKERS = ("nao", "gi", "dau", "sao", "ai", "bao nhieu", "the nao", "may")
# "không" chỉ là dấu hỏi khi đứng cuối ("… không?"): "không biết nữa" vẫn là câu trả lời.
TRAILING_QUESTION_MARKER = "khong"
REPLY_MAX_TOKENS = 4  # câu trả lời câu hỏi lại thường ngắn; dài hơn coi là câu hỏi mới
_MARKER_KEYS = tuple(tuple(marker.split()) for marker in QUESTION_MARKERS)
# Chủ đề là cụm động từ: "hỏi ra trường của ngành nào" sai ngữ pháp → hỏi "về ngành nào".
VERB_TOPICS = frozenset({"hoc may nam", "ra truong"})
# Câu hỏi giữa các ngành ("Ngành nào …", "Những ngành …") hoặc về cả trường ("Trường có …") không
# thuộc riêng ngành nào: không hỏi ngành, không kế thừa. Không đặt cờ school_topic.
ACROSS_MAJOR_MARKERS = ("nganh nao", "nhung nganh", "cac nganh")
ACROSS_LEADING_WORD = "truong"
# "chuyên ngành nào" hỏi chuyên ngành bên trong một ngành, không phải giữa các ngành.
MAJOR_WORD, SPECIALTY_WORD = "nganh", "chuyen"
_ACROSS_KEYS = tuple(tuple(marker.split()) for marker in ACROSS_MAJOR_MARKERS)


@dataclass(frozen=True)
class Detected:
    """Những gì nhận ra được trong MỘT câu, chưa xét lịch sử."""

    majors: tuple[str, ...] = ()  # id ngành khớp chắc, theo thứ tự xuất hiện
    ambiguous: tuple[str, ...] = ()  # các ngành của cụm đầu tiên khớp nhiều ngành ngang nhau
    ambiguous_term: str | None = None  # cụm đó, đúng như viết trong danh mục
    year: int | None = None
    major_topic: str | None = None  # chủ đề cần ngành chạm đầu tiên, như viết trong danh mục
    school_topic: bool = False
    across_majors: bool = False  # câu hỏi giữa các ngành hoặc về cả trường: không cần một ngành

    @property
    def touches_topic(self) -> bool:
        return self.major_topic is not None or self.school_topic


def _occurrences(tokens: list[str], key: tuple[str, ...]) -> list[int]:
    n = len(key)
    return [i for i in range(len(tokens) - n + 1) if tuple(tokens[i : i + n]) == key]


def _is_across_majors(tokens: list[str]) -> bool:
    if tokens[:1] == [ACROSS_LEADING_WORD]:
        return True
    for key in _ACROSS_KEYS:
        for start in _occurrences(tokens, key):
            at = start + key.index(MAJOR_WORD)  # vị trí chữ "ngành" trong cụm khớp
            if at == 0 or tokens[at - 1] != SPECIALTY_WORD:
                return True
    return False


class CatalogMatcher:
    """Khớp tên/alias/mã ngành và chủ đề trên chữ đã chuẩn hoá, theo ranh giới từ."""

    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        order = {m.id: i for i, m in enumerate(catalog.majors)}
        terms: dict[tuple[str, ...], tuple[set[str], str]] = {}
        for major in catalog.majors:
            for raw in (major.name, *major.aliases, *([major.code] if major.code else [])):
                ids, _display = terms.setdefault(tuple(fold(raw).split()), (set(), raw))
                ids.add(major.id)
        # Dài trước, rồi không chồng lấn: "sư phạm tiếng anh" thắng "tiếng anh".
        self._terms = sorted(
            (
                (key, tuple(sorted(ids, key=order.__getitem__)), display)
                for key, (ids, display) in terms.items()
            ),
            key=lambda term: -len(term[0]),
        )
        self._major_topics = [(tuple(fold(t).split()), t) for t in catalog.major_topics]
        self._school_topics = [tuple(fold(t).split()) for t in catalog.school_topics]
        self._names = {m.id: m.name for m in catalog.majors}

    def name(self, major_id: str) -> str:
        return self._names[major_id]

    def detect(self, text: str) -> Detected:
        tokens = fold(text).split()
        taken = [False] * len(tokens)
        hits: list[tuple[int, tuple[str, ...], str]] = []
        for key, ids, display in self._terms:
            for start in _occurrences(tokens, key):
                span = range(start, start + len(key))
                if any(taken[i] for i in span):
                    continue
                for i in span:
                    taken[i] = True
                hits.append((start, ids, display))
        majors: list[str] = []
        ambiguous: tuple[str, ...] = ()
        ambiguous_term: str | None = None
        for _start, ids, display in sorted(hits, key=lambda hit: hit[0]):
            if len(ids) == 1:
                if ids[0] not in majors:
                    majors.append(ids[0])
            elif not ambiguous:
                ambiguous, ambiguous_term = ids, display
        # Chủ đề không tính phần chữ đã là tên ngành ("" không khớp khoá nào).
        free = ["" if taken[i] else token for i, token in enumerate(tokens)]
        found = [
            (start, -len(key), display)
            for key, display in self._major_topics
            for start in _occurrences(free, key)
        ]
        year = next((y for y in map(int, _YEAR.findall(text)) if y in YEAR_RANGE), None)
        return Detected(
            majors=tuple(majors),
            ambiguous=ambiguous,
            ambiguous_term=ambiguous_term,
            year=year,
            major_topic=min(found)[2] if found else None,
            school_topic=any(_occurrences(free, key) for key in self._school_topics),
            across_majors=_is_across_majors(tokens),
        )


@dataclass(frozen=True)
class Pending:
    """Câu hỏi đang chờ người dùng trả lời câu hỏi lại."""

    question: str
    slot: str


@dataclass(frozen=True)
class DialogState:
    majors: tuple[str, ...] = ()  # ngành gần nhất người dùng đã nói tới (trực tiếp hoặc qua làm rõ)
    year: int | None = None  # năm người dùng đã nói tới; năm mặc định không tính
    pending: Pending | None = None


@dataclass(frozen=True)
class Rewrite:
    original: str
    base: str  # câu nền: câu hiện tại, hoặc câu treo khi đang trả lời câu hỏi lại
    standalone: str | None  # None khi decision="clarify"
    majors: tuple[str, ...]
    major_source: str | None  # current | inherited | clarification
    year: int | None
    year_source: str | None  # current | inherited | clarification | default
    needs_major: bool
    school_topic: bool  # câu nền chạm chủ đề cấp trường: không dùng để đổi ngành đang kế thừa
    decision: str  # tập mở: proceed | clarify | proceed_after_clarify
    clarification: Clarification | None

    def trace_data(self, matcher: CatalogMatcher) -> dict[str, Any]:
        return {
            "original": self.original,
            "standalone": self.standalone,
            "slots": {
                "major": {
                    "values": list(self.majors),
                    "names": [matcher.name(m) for m in self.majors],
                    "source": self.major_source,
                },
                "year": {"value": self.year, "source": self.year_source},
            },
            "needs_major": self.needs_major,
            "decision": self.decision,
            "clarification": (
                self.clarification.model_dump(mode="json") if self.clarification else None
            ),
            "catalog_version": matcher.catalog.version,
        }


def _reply_majors(detected: Detected) -> tuple[str, ...]:
    """Ngành mà câu trả lời câu hỏi lại chỉ ra.

    Chỉ nhắc một alias khớp ≤ 3 ngành ("tiếng Anh") thì nhận cả các ngành đó (M4: trả lời liệt
    kê, không hỏi lần hai).
    """
    if detected.majors:
        return detected.majors
    return detected.ambiguous if len(detected.ambiguous) <= LIST_THRESHOLD else ()


def _looks_like_reply(text: str) -> bool:
    """Câu ngắn, không dấu hỏi, không từ để hỏi → coi là câu trả lời (dù không hiểu được)."""
    tokens = fold(text).split()
    if len(tokens) > REPLY_MAX_TOKENS or "?" in text:
        return False
    if tokens and tokens[-1] == TRAILING_QUESTION_MARKER:
        return False
    return not any(_occurrences(tokens, key) for key in _MARKER_KEYS)


def _resolves(detected: Detected, slot: str) -> bool:
    if slot == "major":
        return bool(_reply_majors(detected))
    if slot == "year":
        return detected.year is not None
    return False


def _may_inherit(inherited: tuple[str, ...], base: Detected) -> bool:
    """Câu nhắc alias khớp nhiều ngành thì chỉ kế thừa khi ngành đang kế thừa nằm trong số đó.

    Nếu không, ngành kế thừa không liên quan sẽ nuốt mất câu hỏi làm rõ (spec §10).
    """
    return not base.ambiguous or set(inherited) <= set(base.ambiguous)


def _clarification(
    base: Detected, needs_major: bool, has_major: bool, year: int | None, matcher: CatalogMatcher
) -> Clarification | None:
    """Mỗi lần hỏi đúng MỘT điều: ngành trước, rồi năm."""
    catalog = matcher.catalog
    if needs_major and not has_major:
        if base.ambiguous:
            return Clarification(
                slot="major",
                prompt=f"“{base.ambiguous_term}” ứng với nhiều ngành — bạn muốn hỏi ngành nào?",
                options=[matcher.name(m) for m in base.ambiguous][:MAX_OPTIONS],
            )
        if len(catalog.majors) > LIST_THRESHOLD:
            topic = base.major_topic
            return Clarification(
                slot="major",
                prompt=(
                    "Bạn muốn hỏi về ngành nào?"
                    if topic is None or fold(topic) in VERB_TOPICS
                    else f"Bạn muốn hỏi {topic} của ngành nào?"
                ),
                options=[matcher.name(m) for m in catalog.suggested][:MAX_OPTIONS],
            )
    if needs_major and year is None:
        return Clarification(
            slot="year",
            prompt="Bạn muốn hỏi thông tin của năm nào?",
            options=[str(y) for y in sorted(catalog.years, reverse=True)][:MAX_OPTIONS],
        )
    return None


def _standalone(
    base_text: str,
    majors: tuple[str, ...],
    major_source: str | None,
    year: int | None,
    year_source: str | None,
    matcher: CatalogMatcher,
) -> str:
    parts = [base_text]
    if majors and major_source in _APPENDED:
        parts.append("ngành " + " và ".join(matcher.name(m) for m in majors))
    if year is not None and year_source in _APPENDED:
        # Năm mặc định không ghép: retrieval của câu đơn lượt giữ nguyên.
        parts.append(f"năm {year}")
    return " ".join(parts)


def rewrite_turn(text: str, state: DialogState, matcher: CatalogMatcher) -> Rewrite:
    """Một lượt của §4 bước 2–8, cho trạng thái đã tính từ các lượt trước."""
    catalog = matcher.catalog
    now = matcher.detect(text)
    pending = state.pending
    # Bước 3: trả lời câu treo = giải được đúng loại thông tin đang hỏi và không phải câu hỏi mới.
    answering = pending is not None and not now.touches_topic and _resolves(now, pending.slot)
    # Không giải được mà trông như câu trả lời → chạy câu treo; còn lại là câu hỏi mới.
    stalled = (
        pending is not None and not now.touches_topic and not answering and _looks_like_reply(text)
    )
    base_text = pending.question if pending is not None and (answering or stalled) else text
    base = matcher.detect(base_text) if base_text != text else now
    # Bước 4: không chắc thì coi là không cần ngành (nghiêng về không hỏi).
    needs_major = base.major_topic is not None and not base.school_topic and not base.across_majors
    # Bước 7: không hỏi lại đúng loại thông tin vừa hỏi mà chưa được trả lời.
    blocked = pending.slot if pending is not None and not answering else None

    if answering and _reply_majors(now):
        majors, major_source = _reply_majors(now), "clarification"
    elif base.majors:
        majors, major_source = base.majors, "current"
    elif needs_major and state.majors and _may_inherit(state.majors, base):
        majors, major_source = state.majors, "inherited"
    else:
        majors, major_source = (), None

    if answering and now.year is not None:
        year, year_source = now.year, "clarification"
    elif base.year is not None:
        year, year_source = base.year, "current"
    elif state.year is not None:
        year, year_source = state.year, "inherited"
    elif len(catalog.years) == 1:
        year, year_source = catalog.years[0], "default"
    else:
        year, year_source = None, None

    wanted = _clarification(base, needs_major, bool(majors), year, matcher)
    suppressed = wanted is not None and wanted.slot == blocked
    clarification = None if suppressed else wanted
    if clarification is not None:
        decision, standalone = "clarify", None
    else:
        decision = "proceed_after_clarify" if stalled or suppressed else "proceed"
        standalone = _standalone(base_text, majors, major_source, year, year_source, matcher)
    return Rewrite(
        original=text,
        base=base_text,
        standalone=standalone,
        majors=majors,
        major_source=major_source,
        year=year,
        year_source=year_source,
        needs_major=needs_major,
        school_topic=base.school_topic,
        decision=decision,
        clarification=clarification,
    )


def advance(state: DialogState, result: Rewrite, clarified: Clarification | None) -> DialogState:
    """Trạng thái sau một lượt cũ. `clarified` là câu hỏi lại ĐÃ LƯU của lượt đó (nếu có).

    Câu cấp trường không đổi ngành đang kế thừa: chữ trùng tên ngành trong câu đó ("pháp luật",
    "khách sạn", "du lịch") không phải người dùng đang nói về ngành.
    """
    return DialogState(
        majors=state.majors if result.school_topic else result.majors or state.majors,
        year=result.year if result.year_source in ("current", "clarification") else state.year,
        pending=Pending(result.base, clarified.slot) if clarified is not None else None,
    )


def rewrite(query: Query, matcher: CatalogMatcher) -> Rewrite:
    """§4 bước 1: tính trạng thái từ lịch sử (cũ → mới), rồi xử lý câu hiện tại."""
    state = DialogState()
    for turn in query.history:
        state = advance(state, rewrite_turn(turn.question, state, matcher), turn.clarification)
    return rewrite_turn(query.text, state, matcher)
