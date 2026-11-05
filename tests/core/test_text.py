import pytest

from qnuchat.core.text import fold


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("Ngành Kỹ thuật phần mềm học mấy năm?", "nganh ky thuat phan mem hoc may nam"),
        ("ĐIỂM CHUẨN", "diem chuan"),
        ("Tài chính - Ngân hàng", "tai chinh ngan hang"),
        ("  KTPM!!  ra   trường 🙂 ", "ktpm ra truong"),
        ("Công nghệ kỹ thuật hoá học", "cong nghe ky thuat hoa hoc"),
        ("", ""),
    ],
)
def test_fold(raw, folded):
    assert fold(raw) == folded
