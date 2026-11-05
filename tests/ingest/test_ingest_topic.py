import pytest
from pydantic import ValidationError

from qnuchat.ingest.config import TopicGate
from qnuchat.ingest.topic import TopicFilter, topic_key

SITE = "https://www.qnu.edu.vn"
GATE = TopicGate(
    include=["tuyen-?sinh", "diem-chuan"],
    exclude=["sau-dai-hoc", "(^|-)tu-xa(-|$)"],
    trusted=[f"{SITE}/vi/dai-hoc-chinh-quy-1764"],
)


def test_key_drops_accents_so_one_pattern_serves_titles_and_slugs():
    assert topic_key("Điểm chuẩn  ĐẠI HỌC") == "diem-chuan-dai-hoc"
    assert topic_key("/vi/diem-chuan_2026.pdf", None) == "vi-diem-chuan-2026-pdf"


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    [
        (f"{SITE}/vi/thong-bao/tb1-diem-chuan-2026", None, True),
        (f"{SITE}/vi/thong-bao/tb1", "Điểm chuẩn năm 2026", True),
        # Thư mục cha không đủ: `/tuyen-sinh-1763` thật ra là chuyên mục thông báo chung.
        (f"{SITE}/vi/tuyen-sinh-1763/tb2338-tuyen-dung", "Tuyển dụng lao động", False),
        (f"{SITE}/vi/sau-dai-hoc-1765/tuyen-sinh-2026", None, False),
        (f"{SITE}/vi/tb1", "Tuyển sinh đào tạo từ xa", False),
        (f"{SITE}/vi/dai-hoc-chinh-quy-1764", None, True),
        (f"{SITE}/vi/dai-hoc-chinh-quy-1764/tb121-nguong", "TB121 - Ngưỡng", True),
        (f"{SITE}/vi/dai-hoc-chinh-quy-1764/tb9", "Tuyển sinh sau đại học", False),
        (f"{SITE}/", "Thông tin tuyển sinh", False),
    ],
)
def test_allows(url, title, expected):
    assert TopicFilter(GATE, {}).allows(url, title) is expected


def test_without_a_gate_everything_passes():
    topic = TopicFilter(None, {})
    assert topic.allows(f"{SITE}/", None) and not topic.excluded(f"{SITE}/vi/x", "sau đại học")


def test_a_broken_pattern_is_rejected_when_the_config_loads():
    with pytest.raises(ValidationError):
        TopicGate(include=["("])
