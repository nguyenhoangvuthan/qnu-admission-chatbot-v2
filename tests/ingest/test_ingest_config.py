from pathlib import Path

import pytest
from pydantic import ValidationError

from qnuchat.ingest.config import CrawlConfig, load_crawl_config
from qnuchat.ingest.urls import in_scope

SHIPPED = Path("configs/crawl/qnu.yaml")

MINIMAL = """
seeds: [https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764]
host_suffix: .qnu.edu.vn
tier_a: [https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764]
limits: {rps_per_host: 1, hosts_parallel: 4, max_file_mb: 50, timeout_s: 30}
user_agent: "QNU-admission-chatbot/0.1 (lien he {contact})"
"""


def write(tmp_path, text):
    path = tmp_path / "crawl.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_config_loads_and_covers_the_admission_categories():
    cfg, digest = load_crawl_config(SHIPPED)
    assert cfg.host_suffix == ".qnu.edu.vn"
    assert "https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764" in cfg.tier_a
    assert cfg.limits.rps_per_host == 1 and cfg.limits.hosts_parallel == 4
    assert cfg.host_aliases["qnu.edu.vn"] == "www.qnu.edu.vn"
    assert len(digest) == 64


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("https://tuyensinh.qnu.edu.vn/vi/nganh-dao-tao-dai-hoc-2021/giao-duc-mam-non-5439", False),
        ("https://www.qnu.edu.vn/vi/nganh-dao-tao-dai-hoc-2020/toan-hoc", False),
        ("https://tuyensinh.qnu.edu.vn/vi/de-an-tuyen-sinh-2019/phu-luc", False),
        ("https://tuyensinh.qnu.edu.vn/vi/huong-dan-tuyen-sinh-2021-video/bai-1", False),
        ("https://tuyensinh.qnu.edu.vn/vi/vua-lam-vua-hoc-2021/thong-bao", False),
        ("https://www.qnu.edu.vn/Resources/Docs/CONG%20KHAI%20CTDT%202022-2023/DH/a.pdf", False),
        ("https://gioithieu.qnu.edu.vn/wp-content/uploads/2023/06/a.jpg", False),
        ("https://kcntt.qnu.edu.vn/Resources/Images/SubDomain/kcntt/2021_pictures/a.jpg", False),
        ("https://www.qnu.edu.vn/Resources/Docs/SubDomain/HomePage/2023/Thang%208/a.pdf", False),
        # Từ 2024 trở đi và trang ngành không có ngày đăng thì không bị luật này chặn.
        ("https://tuyensinh.qnu.edu.vn/vi/tong-hop-nganh-dao-tao/2-giao-duc-mam-non", True),
        ("https://tuyensinh.qnu.edu.vn/vi/tuyen-sinh-dai-hoc-chinh-quy-2027", True),
        ("https://tuyensinh.qnu.edu.vn/vi/de-an-tuyen-sinh-2025/phu-luc", True),
        ("https://gioithieu.qnu.edu.vn/wp-content/uploads/2024/05/a.jpg", True),
        ("https://kcntt.qnu.edu.vn/Resources/Images/SubDomain/kcntt/2024_pictures/a.jpg", True),
    ],
)
def test_shipped_config_blocks_sections_known_to_predate_2024(url, kept):
    """Kent 04/11/2026: chỉ giữ từ 01/01/2024. Mục con của các chuyên mục này không có ngày và
    `infer_year` không xét đoạn cha của URL, nên phải chặn bằng mẫu URL."""
    cfg, _ = load_crawl_config(SHIPPED)
    assert in_scope(url, cfg) is kept


def test_hash_is_stable_and_changes_with_content(tmp_path):
    _, first = load_crawl_config(write(tmp_path, MINIMAL))
    _, again = load_crawl_config(write(tmp_path, MINIMAL))
    _, other = load_crawl_config(
        write(tmp_path, MINIMAL.replace("max_file_mb: 50", "max_file_mb: 40"))
    )
    assert first == again != other


def test_unknown_keys_are_refused(tmp_path):
    with pytest.raises(ValidationError):
        load_crawl_config(write(tmp_path, MINIMAL + "\nextra_key: 1\n"))


def test_user_agent_must_carry_a_contact_placeholder(tmp_path):
    with pytest.raises(ValidationError, match="contact"):
        load_crawl_config(write(tmp_path, MINIMAL.replace(" {contact}", "")))


def test_user_agent_for_fills_the_contact_and_refuses_empty(tmp_path):
    cfg, _ = load_crawl_config(write(tmp_path, MINIMAL))
    assert cfg.user_agent_for("a@b.vn").endswith("(lien he a@b.vn)")
    with pytest.raises(ValueError, match="QNUCHAT_CRAWL_CONTACT_EMAIL"):
        cfg.user_agent_for("  ")


def test_invalid_regex_is_refused(tmp_path):
    with pytest.raises(ValidationError):
        load_crawl_config(write(tmp_path, MINIMAL + "\nblocklist_url_patterns: ['(']\n"))


def test_host_suffix_must_start_with_a_dot():
    with pytest.raises(ValidationError):
        CrawlConfig.model_validate(
            {
                "seeds": ["https://a.vn/"],
                "host_suffix": "qnu.edu.vn",
                "tier_a": ["https://a.vn/"],
                "limits": {
                    "rps_per_host": 1,
                    "hosts_parallel": 1,
                    "max_file_mb": 1,
                    "timeout_s": 1,
                },
                "user_agent": "x {contact}",
            }
        )


def _raw(**over):
    base = {
        "seeds": ["https://www.qnu.edu.vn/"],
        "host_suffix": ".qnu.edu.vn",
        "tier_a": ["https://www.qnu.edu.vn/vi/a"],
        "limits": {"rps_per_host": 1, "hosts_parallel": 1, "max_file_mb": 1, "timeout_s": 1},
        "user_agent": "x {contact}",
    }
    base.update(over)
    return base


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"seeds": ["ftp://www.qnu.edu.vn/"]}, "seeds"),
        ({"seeds": ["https://example.com/"]}, "seeds"),
        ({"seeds": ["https://evilqnu.edu.vn/"]}, "seeds"),
        ({"tier_a": ["ftp://www.qnu.edu.vn/a"]}, "tier_a"),
        ({"tier_a": ["https://example.com/a"]}, "tier_a"),
        ({"host_suffix": ".."}, "host_suffix"),
        ({"host_suffix": "."}, "host_suffix"),
        ({"host_suffix": ".edu"}, "host_suffix"),
        ({"host_aliases": {"": "www.qnu.edu.vn"}}, "host_aliases"),
        ({"host_aliases": {"qnu.edu.vn": ""}}, "host_aliases"),
        ({"host_aliases": {"Qnu.edu.vn": "www.qnu.edu.vn"}}, "host_aliases"),
        ({"blocklist_hosts": [""]}, "blocklist_hosts"),
        ({"blocklist_hosts": ["a b.qnu.edu.vn"]}, "blocklist_hosts"),
    ],
)
def test_bad_hosts_and_urls_are_refused_with_the_field_name(over, field):
    with pytest.raises(ValidationError, match=field):
        CrawlConfig.model_validate(_raw(**over))


def test_bare_suffix_host_is_accepted_as_seed():
    CrawlConfig.model_validate(_raw(seeds=["https://qnu.edu.vn/"]))
