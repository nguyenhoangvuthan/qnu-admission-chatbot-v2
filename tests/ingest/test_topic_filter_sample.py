import json
from collections import Counter

import pytest

from qnuchat.ingest.manifest import ManifestEntry
from qnuchat.ingest.topic_filter.ledger import TopicConfig
from qnuchat.ingest.topic_filter.sample import draw_sample, host_group, make_sample
from tests.support.webstore import W, WebStore, html_page, png_bytes

GROUPS = {"www": ["www"], "tuyensinh": ["tuyensinh"], "khoa": ["kcntt", "fba"]}
CFG = TopicConfig(max_chars=1500, max_tokens=256, sample_size=20, sample_seed=7, host_groups=GROUPS)


def entry(url: str, kind: str) -> ManifestEntry:
    return ManifestEntry(
        url=url,
        source_id="w-0",
        page_url=None,
        kind=kind,
        title=None,
        published=None,
        retrieved_at="2026-10-13T08:00:00+07:00",
        sha256="s" * 64,
        mime=None,
        bytes=1,
        host=url.split("/")[2],
        tier="B",
        text_status="text",
        reason=None,
        crawl_run="t",
        config_hash="c",
        sources_yaml_ref=None,
    )


def pool() -> list[ManifestEntry]:
    items = []
    for host, counts in {
        "www.qnu.edu.vn": {"page": 300, "file": 40, "image": 600},
        "tuyensinh.qnu.edu.vn": {"page": 60, "file": 20, "image": 30},
        "kcntt.qnu.edu.vn": {"page": 80, "file": 10, "image": 90},
        "ns.qnu.edu.vn": {"page": 50, "file": 5, "image": 70},
    }.items():
        for kind, count in counts.items():
            items += [entry(f"https://{host}/{kind}/{i:04d}", kind) for i in range(count)]
    return items


def test_host_group_uses_short_names_and_falls_back_to_khac():
    assert host_group("www.qnu.edu.vn", GROUPS) == "www"
    assert host_group("fba.qnu.edu.vn", GROUPS) == "khoa"
    assert host_group("ns.qnu.edu.vn", GROUPS) == "khac"


def test_sample_is_deterministic_and_has_n_items():
    first = draw_sample(pool(), groups=GROUPS, n=200, seed=20261022)
    second = draw_sample(pool(), groups=GROUPS, n=200, seed=20261022)
    assert [e.url for e in first] == [e.url for e in second]
    assert len(first) == 200 and len({e.url for e in first}) == 200
    other = draw_sample(pool(), groups=GROUPS, n=200, seed=1)
    assert [e.url for e in other] != [e.url for e in first]


def test_each_host_group_gets_an_equal_share_and_each_kind_at_least_3():
    sample = draw_sample(pool(), groups=GROUPS, n=200, seed=20261022)
    by_group = Counter(host_group(e.host, GROUPS) for e in sample)
    assert by_group == {"www": 50, "tuyensinh": 50, "khoa": 50, "khac": 50}
    by_stratum = Counter((host_group(e.host, GROUPS), e.kind) for e in sample)
    assert min(by_stratum.values()) >= 3
    # Trong nhóm chia theo tỉ lệ kind: www có 600 ảnh / 940 mục.
    assert by_stratum[("www", "image")] > by_stratum[("www", "page")] > by_stratum[("www", "file")]


def test_small_group_gives_its_unused_share_to_the_others():
    small = [e for e in pool() if not e.host.startswith("tuyensinh")]
    small += [entry(f"https://tuyensinh.qnu.edu.vn/page/{i}", "page") for i in range(10)]
    sample = draw_sample(small, groups=GROUPS, n=200, seed=3)
    by_group = Counter(host_group(e.host, GROUPS) for e in sample)
    assert by_group["tuyensinh"] == 10 and sum(by_group.values()) == 200


def test_top_up_excludes_previous_rounds_and_only_draws_tuyensinh_and_khoa():
    first = draw_sample(pool(), groups=GROUPS, n=200, seed=20261022)
    extra = draw_sample(
        pool(),
        groups=GROUPS,
        n=50,
        seed=20261024,
        exclude={e.url for e in first},
        only_groups={"tuyensinh", "khoa"},
    )
    assert len(extra) == 50
    assert not {e.url for e in extra} & {e.url for e in first}
    assert {host_group(e.host, GROUPS) for e in extra} <= {"tuyensinh", "khoa"}


@pytest.fixture
def web(tmp_path):
    store = WebStore(tmp_path / "web")
    for i in range(8):
        store.put(f"{W}/vi/tin/bai-{i}", title=f"Bài {i}", data=html_page(f"Bài {i}", "tuyển sinh"))
    for i in range(8):
        store.put(
            f"https://kcntt.qnu.edu.vn/anh-{i}.jpg",
            kind="image",
            data=png_bytes(30 + i, 20),
            quarantine=True,
        )
    return store


def sample_for(web, out_dir, **kwargs):
    current = web.current()
    return make_sample(
        out_dir,
        list(current.values()),
        current=current,
        blobs=web.blobs,
        cfg=CFG,
        seed=CFG.sample_seed,
        out=lambda line: None,
        **kwargs,
    )


def test_round_file_has_item_ids_urls_and_shas(web, tmp_path):
    out_dir = tmp_path / "sample-7"
    assert sample_for(web, out_dir) == 0
    rows = [json.loads(line) for line in (out_dir / "round-1.jsonl").read_text().splitlines()]
    assert [r["item_id"] for r in rows] == [f"S{i:03d}" for i in range(1, 17)]
    assert set(rows[0]) == {"item_id", "url", "sha256", "kind", "host_group", "round", "page_url"}


def test_form_has_no_model_labels_and_exports_the_csv_columns(web, tmp_path):
    out_dir = tmp_path / "sample-7"
    sample_for(web, out_dir)
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "item_id,url,sha256,label,reviewer,at" in html
    assert "khong_chac" not in html and "prompt" not in html.lower()
    assert html.count("data:image/jpeg;base64,") == 8
    assert 'value="giu"' in html and 'value="loai"' in html


def test_second_sample_without_top_up_is_refused(web, tmp_path):
    out_dir = tmp_path / "sample-7"
    assert sample_for(web, out_dir) == 0
    assert sample_for(web, out_dir) == 2


def test_top_up_without_a_first_round_is_refused(web, tmp_path):
    assert sample_for(web, tmp_path / "sample-7", top_up=5) == 2


def test_top_up_writes_round_2_and_the_form_lists_both_rounds(web, tmp_path):
    out_dir = tmp_path / "sample-7"
    small = TopicConfig(**{**CFG.model_dump(), "sample_size": 6})
    current = web.current()
    kwargs = {"current": current, "blobs": web.blobs, "seed": 7, "out": lambda line: None}
    assert make_sample(out_dir, list(current.values()), cfg=small, **kwargs) == 0
    assert make_sample(out_dir, list(current.values()), cfg=small, top_up=3, **kwargs) == 0
    second = [json.loads(x) for x in (out_dir / "round-2.jsonl").read_text().splitlines()]
    assert [r["item_id"] for r in second] == ["S007", "S008", "S009"]
    assert {r["host_group"] for r in second} <= {"tuyensinh", "khoa"}
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "S009" in html and "S001" in html
