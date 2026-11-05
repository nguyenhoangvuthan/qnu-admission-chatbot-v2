"""Gắn mỗi run với đúng dữ liệu đã sinh ra nó.

Toàn bộ pipeline chấm điểm TỪ CACHE (project.md B8.5): `run_pilot` ghi output
thô một lần, `report_pilot` đọc lại và chấm nhiều lần. Điều đó chỉ đúng khi
gold và PDF không đổi giữa hai bước — nếu đổi mà không ai kiểm, cùng một file
raw sẽ cho ra hai bảng kết quả khác nhau, không cái nào tự khai là sai.

Đây là chỗ duy nhất định nghĩa "cùng một run", để runner và reporter không thể
hiểu khác nhau về nó.
"""

import hashlib
import json
import pathlib


class StaleRunError(RuntimeError):
    """Dữ liệu hiện tại không khớp dữ liệu đã sinh ra run này."""


def sha256_file(path: str | pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def run_identity(config: dict, *, gold_sha256: str, pdf_sha256: str) -> str:
    """Vân tay của những thứ PHẢI bất biến trong suốt một `run_id`.

    `arms` bị loại khỏi vân tay có chủ đích: chạy nốt một arm còn thiếu vào cùng
    run là hợp lệ và cần thiết (một arm hỏng giữa chừng không nên bắt chạy lại
    cả bốn). Mọi thứ còn lại — seed, top_k, model, gold, PDF — mà đổi thì đó là
    một run KHÁC, và trộn kết quả hai run dưới một manifest là làm giả số liệu.
    """
    invariant = {key: value for key, value in config.items() if key != "arms"}
    payload = json.dumps(
        {"config": invariant, "gold_sha256": gold_sha256, "pdf_sha256": pdf_sha256},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_corpus_unchanged(
    manifest: dict, *, gold_path: str | pathlib.Path, pdf_path: str | pathlib.Path
) -> None:
    """Chặn việc chấm output thô cũ bằng gold/PDF mới.

    Đổi gold mà không kiểm thì accuracy nhảy từ 1.0 xuống 0.0; đổi PDF thì
    unsupported rate nhảy từ 0.0 lên 1.0. Cả hai đều là con số "hợp lệ" trên
    giấy, nên chúng phải bị chặn ở đây chứ không thể phát hiện ở bảng kết quả.
    """
    expected = {"gold_sha256": gold_path, "pdf_sha256": pdf_path}
    missing = [field for field in expected if not manifest.get(field)]
    if missing:
        raise StaleRunError(
            f"Manifest thiếu {', '.join(missing)} — không thể xác minh nguồn dữ liệu. "
            "Manifest này sinh ra trước khi run có kiểm hash; chạy lại run với run_id mới."
        )
    for field, path in expected.items():
        actual = sha256_file(path)
        if actual != manifest[field]:
            raise StaleRunError(
                f"{field} đã đổi kể từ khi chạy run này: manifest ghi "
                f"{manifest[field][:12]}…, {pathlib.Path(path).name} hiện tại là "
                f"{actual[:12]}…. Chấm output thô cũ bằng dữ liệu mới sẽ cho ra "
                "con số sai mà không có cảnh báo nào. Chạy lại run với run_id mới, "
                "hoặc khôi phục đúng phiên bản dữ liệu."
            )
