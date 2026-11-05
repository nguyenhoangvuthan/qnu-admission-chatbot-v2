import pytest

from qnuchat.ingest.config import CrawlConfig, Limits
from qnuchat.ingest.urls import (
    canonicalize,
    classify_link,
    drive_canonical,
    drive_file_id,
    drive_folder_id,
    in_scope,
    is_child,
    source_id_for,
    tier_for,
)

BASE = "https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb141"
CFG = CrawlConfig(
    seeds=["https://www.qnu.edu.vn/"],
    host_suffix=".qnu.edu.vn",
    host_aliases={"qnu.edu.vn": "www.qnu.edu.vn"},
    blocklist_hosts=["eoffice.qnu.edu.vn"],
    blocklist_url_patterns=["/tim-kiem"],
    tier_a=["https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764"],
    limits=Limits(rps_per_host=1, hosts_parallel=1, max_file_mb=1, timeout_s=1),
    user_agent="UA {contact}",
)


def test_relative_link_resolves_and_drops_the_fragment():
    assert canonicalize("/vi/a#muc-2", base=BASE) == "https://www.qnu.edu.vn/vi/a"


def test_scheme_host_case_default_port_and_tracking_params_are_normalised():
    url = "HTTP://WWW.QNU.EDU.VN:443/vi/a?utm_source=fb&id=3"
    assert canonicalize(url) == "https://www.qnu.edu.vn/vi/a?id=3"


def test_raw_and_percent_encoded_paths_are_the_same_url():
    raw = "/Resources/Docs/2026/Thang 8/Thong bao dai học.pdf"
    encoded = "/Resources/Docs/2026/Thang%208/Thong%20bao%20dai%20h%E1%BB%8Dc.pdf"
    assert canonicalize(raw, base=BASE) == canonicalize(encoded, base=BASE)
    assert " " not in canonicalize(raw, base=BASE)


def test_host_alias_merges_bare_domain_into_www():
    assert canonicalize("https://qnu.edu.vn/vi/a", aliases=CFG.host_aliases) == (
        "https://www.qnu.edu.vn/vi/a"
    )


@pytest.mark.parametrize(
    "href", ["", "#", "javascript:__doPostBack('a','')", "mailto:a@b.vn", "tel:0256"]
)
def test_non_navigational_links_are_dropped(href):
    assert canonicalize(href, base=BASE) is None


def test_scope_is_the_suffix_minus_blocklist():
    assert in_scope("https://kcntt.qnu.edu.vn/vi/x", CFG)
    assert in_scope("https://qnu.edu.vn/", CFG)
    assert not in_scope("https://evilqnu.edu.vn/", CFG)
    assert not in_scope("https://eoffice.qnu.edu.vn/", CFG)
    assert not in_scope("https://www.qnu.edu.vn/vi/tim-kiem?k=a", CFG)
    assert not in_scope("https://www.facebook.com/qnu", CFG)


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/file/d/1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW/view",
        "https://drive.google.com/open?id=1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW",
        "https://drive.google.com/uc?export=download&id=1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW",
    ],
)
def test_drive_file_ids(url):
    assert drive_file_id(canonicalize(url)) == "1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW"
    assert classify_link(canonicalize(url), CFG) == "drive_file"


def test_drive_folder():
    url = canonicalize("https://drive.google.com/drive/folders/1LHkr_g_EiUs-H5fT-LNh4YfkgxMSobIO")
    assert drive_folder_id(url) == "1LHkr_g_EiUs-H5fT-LNh4YfkgxMSobIO"
    assert classify_link(url, CFG) == "drive_folder"


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://www.qnu.edu.vn/Resources/Docs/TB141.PDF", "file"),
        ("https://www.qnu.edu.vn/Resources/Docs/a.docx", "file"),
        ("https://www.qnu.edu.vn/Resources/Docs/a.xlsx", "file"),
        ("https://www.qnu.edu.vn/Resources/Images/bang%201.png", "image"),
        ("https://www.qnu.edu.vn/Resources/Images/a.JPG", "image"),
        ("https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb141", "page"),
        ("https://www.qnu.edu.vn/Resources/a.zip", None),
        ("https://www.facebook.com/qnu", None),
    ],
)
def test_classify_link(url, kind):
    assert classify_link(url, CFG) == kind


def test_source_id_is_stable_and_short():
    sid = source_id_for("https://www.qnu.edu.vn/vi/a")
    assert sid == source_id_for("https://www.qnu.edu.vn/vi/a")
    assert sid.startswith("w-") and len(sid) == 18
    assert sid != source_id_for("https://www.qnu.edu.vn/vi/b")


def test_tier_a_covers_the_category_and_its_children_only():
    tier_a = [canonicalize(u) for u in CFG.tier_a]
    assert tier_for("https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764", tier_a) == "A"
    assert tier_for("https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb141", tier_a) == "A"
    assert tier_for("https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-17640", tier_a) == "B"
    assert tier_for("https://kcntt.qnu.edu.vn/", tier_a) == "B"


def test_is_child():
    assert is_child("https://a.vn/vi/cat/x", "https://a.vn/vi/cat")
    assert is_child("https://a.vn/vi/cat/x", "https://a.vn/vi/cat/")
    assert not is_child("https://a.vn/vi/cat", "https://a.vn/vi/cat")
    assert not is_child("https://a.vn/vi/catx", "https://a.vn/vi/cat")


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/file/d/1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW/view?usp=sharing",
        "https://drive.google.com/file/d/1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW/view?usp=drive_link",
        "https://drive.google.com/file/d/1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW/edit",
        "https://drive.google.com/open?id=1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW&usp=sharing",
        "https://drive.google.com/uc?export=download&id=1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW",
    ],
)
def test_drive_file_links_share_one_canonical_url(url):
    canonical = "https://drive.google.com/file/d/1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW/view"
    assert drive_canonical(canonicalize(url)) == canonical


def test_drive_canonical_is_none_for_other_urls():
    assert drive_canonical("https://www.qnu.edu.vn/Resources/Docs/a.pdf") is None
    assert (
        drive_canonical("https://drive.google.com/drive/folders/1LHkr_g_EiUs-H5fT-LNh4Yf") is None
    )


def test_query_parameter_order_does_not_matter():
    assert canonicalize("https://www.qnu.edu.vn/vi/a?b=2&a=1") == canonicalize(
        "https://www.qnu.edu.vn/vi/a?a=1&b=2"
    )
    assert canonicalize("https://www.qnu.edu.vn/a?b=2&a=1") == "https://www.qnu.edu.vn/a?a=1&b=2"


def test_tier_ignores_the_query_string():
    tier_a = [canonicalize(u) for u in CFG.tier_a]
    assert tier_for("https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764?page=2", tier_a) == "A"
    assert tier_for("https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb141?x=1", tier_a) == "A"
    assert tier_for("https://www.qnu.edu.vn/vi/khac?page=2", tier_a) == "B"
