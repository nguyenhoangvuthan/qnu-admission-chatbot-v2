import pathlib

import pytest
import yaml

from experiments.sources import REGISTRY, source_path

TOPICS = {"tuyen-sinh-dai-hoc-chinh-quy", "hoc-phi", "ky-tuc-xa", "giao-duc-quoc-phong"}


def registry() -> list[dict]:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["sources"]


def test_source_path_finds_the_file_in_its_topic_folder(tmp_path):
    (tmp_path / "hoc-phi").mkdir()
    (tmp_path / "tuyen-sinh-dai-hoc-chinh-quy").mkdir()
    (tmp_path / "hoc-phi" / "TB1.pdf").write_bytes(b"x")
    assert source_path("TB1.pdf", tmp_path) == tmp_path / "hoc-phi" / "TB1.pdf"


@pytest.mark.parametrize("copies", [0, 2])
def test_source_path_refuses_missing_or_duplicate_names(tmp_path, copies):
    for topic in sorted(TOPICS)[:copies]:
        (tmp_path / topic).mkdir()
        (tmp_path / topic / "TB1.pdf").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match=f"thấy {copies}"):
        source_path("TB1.pdf", tmp_path)


def test_registry_files_sit_in_a_topic_folder_with_unique_names():
    files = [pathlib.PurePosixPath(s["file"]) for s in registry()]
    assert {f.parent.as_posix() for f in files} <= TOPICS
    names = [f.name for f in files]
    assert len(names) == len(set(names))


def test_registry_files_exist_with_the_recorded_size():
    data = REGISTRY.parent
    for s in registry():
        path = data / s["file"]
        assert path.is_file(), s["file"]
        if path.stat().st_size < 1024 and path.read_bytes().startswith(b"version https://git-lfs"):
            pytest.skip("file LFS chưa tải (git lfs pull)")
        assert path.stat().st_size == s["bytes"], s["file"]
