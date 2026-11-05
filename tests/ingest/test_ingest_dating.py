"""Suy năm của trang/tài liệu web để giữ kho từ `min_year` trở đi (quyết định 13/10/2026)."""

from datetime import date

import pytest

from qnuchat.ingest.dating import infer_year, is_before, year_from_text, year_from_url

TODAY = date(2026, 10, 13)


@pytest.mark.parametrize(
    ("url", "title", "year"),
    [
        # Năm giữa tên: tin được.
        ("https://k.qnu.edu.vn/vi/a/ban-tin-thang-12-nam-2022-so-3", None, 2022),
        ("https://k.qnu.edu.vn/vi/a/nam-hoc-2022-2023-ke-hoach", None, 2023),
        ("https://www.qnu.edu.vn/Resources/Images/2019-144232.jpg", None, 2019),
        # Đuôi -YYYY: đứng sau "nam-", trong khoảng năm, hoặc tiêu đề xác nhận.
        ("https://k.qnu.edu.vn/vi/a/tuyen-dung-vien-chuc-nam-2019", None, 2019),
        ("https://k.qnu.edu.vn/vi/a/giai-thuong-bao-son-2017-2018", None, 2018),
        ("https://k.qnu.edu.vn/vi/a/to-hop-xet-tuyen-2020", "Tổ hợp xét tuyển 2020", 2020),
        # Đuôi -YYYY không có gì xác nhận: có thể là ID của CMS.
        ("https://k.qnu.edu.vn/vi/sinh-vien-2016", None, None),
        ("https://k.qnu.edu.vn/vi/a/nguong-dau-vao-dkxt-2019", "Ngưỡng đầu vào", None),
        # Chỉ xét đoạn cuối: chuyên mục cha mang số có thể là ID.
        ("https://www.qnu.edu.vn/vi/de-an-tuyen-sinh-2019/chi-tieu-tuyen-sinh", None, None),
        ("https://k.qnu.edu.vn/vi/co-cau-to-chuc-1117", None, None),
        # Tên URL mã hoá %, khoảng trắng.
        ("https://k.qnu.edu.vn/Resources/Docs/CONG%20KHAI%20CTDT%202022-2023.pdf", None, 2023),
    ],
)
def test_year_from_url(url, title, year):
    assert year_from_url(url, title=title, today=TODAY) == year


@pytest.mark.parametrize(
    ("text", "year"),
    [
        ("Thông báo tuyển sinh thạc sĩ đợt 2 năm 2022", 2022),
        ("Kỷ niệm 50 năm (1975 – 2025)", 2025),
        ("Lịch học kỳ 2 năm học 2019-2020", 2020),
        ("Hội thảo khoa học", None),
        ("Năm 2031 sẽ có", None),  # quá xa trong tương lai: không phải năm đăng
        (None, None),
    ],
)
def test_year_from_text(text, year):
    assert year_from_text(text, today=TODAY) == year


def test_published_date_wins_over_url_and_title():
    # Bài đăng 2024 nhắc đề án 2019: giữ (ngày đăng trước, năm URL sau).
    year = infer_year(
        url="https://www.qnu.edu.vn/vi/a/nhin-lai-de-an-tuyen-sinh-nam-2019",
        title="Nhìn lại đề án 2019",
        published=date(2024, 3, 1),
        today=TODAY,
    )
    assert year == 2024


def test_implausible_published_date_falls_back_to_the_url():
    # Ngày bắt nhầm trong thân bài (27/3/1946) không phải ngày đăng.
    year = infer_year(
        url="https://k.qnu.edu.vn/vi/a/ban-tin-nam-2020-so-1",
        title=None,
        published=date(1946, 3, 27),
        today=TODAY,
    )
    assert year == 2020


def test_asset_uses_its_page_publish_date_before_its_own_name():
    # File tên "TB 2019" đính kèm bài đăng 2025: theo ngày đăng của bài.
    year = infer_year(
        url="https://www.qnu.edu.vn/Resources/Docs/tb-diem-chuan-nam-2019.pdf",
        title=None,
        published=None,
        parent_published=date(2025, 7, 1),
        today=TODAY,
    )
    assert year == 2025


def test_asset_falls_back_to_its_own_name_then_to_its_page():
    own = infer_year(
        url="https://www.qnu.edu.vn/Resources/Docs/ke-hoach-nam-2021.pdf",
        title=None,
        published=None,
        parent_url="https://www.qnu.edu.vn/vi/a/bai-nam-2024",
        today=TODAY,
    )
    assert own == 2021
    parent = infer_year(
        url="https://www.qnu.edu.vn/Temp/ArticleImage/29dc3684.jpg",
        title=None,
        published=None,
        parent_url="https://www.qnu.edu.vn/vi/a/bai-nam-2021",
        parent_title=None,
        today=TODAY,
    )
    assert parent == 2021


def test_unknown_year_is_none_and_is_never_before_the_floor():
    year = infer_year(
        url="https://www.qnu.edu.vn/vi/gioi-thieu", title="Giới thiệu", published=None, today=TODAY
    )
    assert year is None
    assert not is_before(year, 2023)
    assert is_before(2022, 2023)
    assert not is_before(2023, 2023)
    assert not is_before(2019, None)  # không đặt mốc: không lọc
