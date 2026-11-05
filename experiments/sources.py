"""Tìm file nguồn trong data/ theo tên (data/sources.yaml).

File nằm trong một thư mục chủ đề dưới data/ (danh sách ở đầu sources.yaml); manifest các run vẫn
băm theo tên file trần, nên code giữ tên làm khoá và chỉ tra đường dẫn ở đây.
"""

import pathlib

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
REGISTRY = DATA / "sources.yaml"


def source_path(name: str, data: pathlib.Path = DATA) -> pathlib.Path:
    """Đường dẫn của file `name` trong đúng một thư mục chủ đề dưới `data`."""
    hits = [d / name for d in sorted(data.iterdir()) if d.is_dir() and (d / name).is_file()]
    if len(hits) != 1:
        raise FileNotFoundError(f"cần đúng một file {name!r} trong data/*/, thấy {len(hits)}")
    return hits[0]
