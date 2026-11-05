import pytest
import yaml

from qnuchat.core.catalog import CatalogError, load_catalog
from tests.support.catalogs import KTPM, MAJORS, make_catalog


def write(tmp_path, data, name="catalog.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def valid():
    return make_catalog().model_dump(mode="json")


def test_loads_and_hashes_the_validated_content(tmp_path):
    catalog, digest = load_catalog(write(tmp_path, valid()))
    assert [m.id for m in catalog.majors][:2] == ["ky-thuat-phan-mem", "cong-nghe-thong-tin"]
    assert len(digest) == 64


def test_hash_ignores_yaml_formatting_but_follows_content(tmp_path):
    a = write(tmp_path, valid(), "a.yaml")
    b = tmp_path / "b.yaml"
    b.write_text("# chú thích\n" + a.read_text(encoding="utf-8"), encoding="utf-8")
    changed = valid()
    changed["majors"][0]["aliases"] = ["KTPM", "SE"]
    c = write(tmp_path, changed, "c.yaml")
    assert load_catalog(a)[1] == load_catalog(b)[1]
    assert load_catalog(a)[1] != load_catalog(c)[1]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(unexpected=1), "unexpected"),
        (lambda d: d["majors"].append(dict(KTPM)), "id ngành trùng"),
        (lambda d: d["majors"].append({**KTPM, "id": "khac"}), "tên chuẩn trùng"),
        (lambda d: d.update(suggested=["khong-co"]), "suggested"),
        (lambda d: d.update(suggested=[m["id"] for m in MAJORS] * 2), "suggested"),
        (lambda d: d["majors"][1].update(aliases=["Kỹ thuật phần mềm"]), "trùng tên chuẩn"),
        (lambda d: d["majors"][0].update(aliases=["!!!"]), "rỗng"),
        (lambda d: d.update(years=[2025, 2025]), "năm trùng"),
        (lambda d: d.update(years=[]), "years"),
        (lambda d: d["majors"][0].update(pages=[]), "pages"),
        (lambda d: d["majors"][0].update(id="Có Dấu"), "id"),
    ],
)
def test_invalid_catalog_is_refused(tmp_path, mutate, message):
    data = valid()
    mutate(data)
    with pytest.raises(CatalogError, match=message):
        load_catalog(write(tmp_path, data))


def test_missing_file_is_a_catalog_error_naming_the_path(tmp_path):
    with pytest.raises(CatalogError, match="khong-co.yaml"):
        load_catalog(tmp_path / "khong-co.yaml")


def test_broken_yaml_is_a_catalog_error(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("majors: [\n", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(path)


def test_non_utf8_file_is_a_catalog_error(tmp_path):
    """Review F6: file không phải UTF-8 không được lọt ra thành UnicodeDecodeError."""
    path = tmp_path / "latin1.yaml"
    path.write_bytes("version: 1 # chú thích".encode("latin-1", errors="replace") + b"\xff\xfe")
    with pytest.raises(CatalogError, match="latin1.yaml"):
        load_catalog(path)
