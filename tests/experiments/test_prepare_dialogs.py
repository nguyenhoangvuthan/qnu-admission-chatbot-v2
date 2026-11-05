"""Hồ sơ duyệt hội thoại nhiều lượt của gold v2."""

import copy
import re

import pytest

from experiments.prepare_dialogs import (
    V2_DIALOGS,
    dialog_packet,
    read_dialogs,
    validate_dialogs,
)
from experiments.prepare_gold import digest


@pytest.fixture(scope="module")
def dialogs():
    return read_dialogs(V2_DIALOGS)


def test_v2_dialog_draft_is_valid(dialogs):
    assert validate_dialogs(dialogs) == []
    assert len(dialogs) >= 50


def test_unknown_major_id_is_rejected(dialogs):
    altered = copy.deepcopy(dialogs)
    altered[0]["turns"][0]["expect"]["majors"] = ["nganh-khong-co"]
    assert any("nganh-khong-co" in e for e in validate_dialogs(altered))


def test_unknown_decision_is_rejected(dialogs):
    altered = copy.deepcopy(dialogs)
    altered[0]["turns"][0]["expect"]["decision"] = "maybe"
    assert any("decision" in e for e in validate_dialogs(altered))


def test_duplicate_dialog_id_is_rejected(dialogs):
    assert any("duplicate" in e for e in validate_dialogs([dialogs[0], dialogs[0]]))


def test_dialog_packet_has_one_tickbox_form_per_dialog(dialogs, tmp_path):
    dialog_packet(dialogs, tmp_path)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    forms = dict(re.findall(r'data-item="([^"]+)" data-hash="([0-9a-f]{64})"', index))
    assert forms == {d["id"]: digest(d) for d in dialogs}
    first_turn = dialogs[0]["turns"][0]["user"]
    assert first_turn in index
    assert (tmp_path / "reviews.csv").exists()


def test_standalone_ref_is_accepted_and_shown_as_reference(dialogs, tmp_path):
    altered = copy.deepcopy(dialogs)
    altered[0]["turns"][-1]["expect"]["standalone_ref"] = "Câu tham khảo"
    assert validate_dialogs(altered) == []
    dialog_packet(altered, tmp_path)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "câu viết lại tham khảo (không chấm): &#x27;Câu tham khảo&#x27;" in index
