"""Danh mục giả lập nhỏ cho test core: kiểm soát được số ngành, số năm, alias mơ hồ."""

from qnuchat.core.catalog import Catalog

KTPM = {
    "id": "ky-thuat-phan-mem",
    "name": "Kỹ thuật phần mềm",
    "aliases": ["KTPM"],
    "code": "7480103",
    "pages": [72],
}
CNTT = {
    "id": "cong-nghe-thong-tin",
    "name": "Công nghệ thông tin",
    "aliases": ["CNTT"],
    "pages": [74],
}
NNA = {"id": "ngon-ngu-anh", "name": "Ngôn ngữ Anh", "aliases": ["tiếng Anh"], "pages": [36]}
SPTA = {
    "id": "su-pham-tieng-anh",
    "name": "Sư phạm Tiếng Anh",
    "aliases": ["tiếng Anh"],
    "pages": [20],
}
LUAT = {"id": "luat", "name": "Luật", "pages": [62]}

MAJORS = [KTPM, CNTT, NNA, SPTA, LUAT]  # 5 ngành > 3: thiếu ngành thì hỏi
SMALL_MAJORS = [KTPM, CNTT, LUAT]  # ≤ 3: thiếu ngành thì trả lời liệt kê


def make_catalog(*, years=(2025,), majors=None) -> Catalog:
    majors = MAJORS if majors is None else majors
    return Catalog.model_validate(
        {
            "version": 1,
            "years": list(years),
            "majors": majors,
            "suggested": [m["id"] for m in majors][:2],
            "major_topics": ["học phí", "điểm chuẩn", "học mấy năm", "ra trường", "việc làm"],
            "school_topics": ["ký túc xá", "địa chỉ"],
        }
    )
