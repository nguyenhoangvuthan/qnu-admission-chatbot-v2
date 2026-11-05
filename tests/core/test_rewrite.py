"""Bảng hành vi của query_rewrite (spec chat nhiều lượt §4, §10, §11)."""

from pathlib import Path

import pytest

from qnuchat.core.catalog import load_catalog
from qnuchat.core.contracts import Clarification, Turn
from qnuchat.core.rewrite import CatalogMatcher, rewrite
from tests.support.catalogs import SMALL_MAJORS, make_catalog
from tests.support.fakes import make_query

ROOT = Path(__file__).resolve().parents[2]
M = CatalogMatcher(make_catalog())
REAL = CatalogMatcher(load_catalog(ROOT / "configs/catalog/qnu-2025.yaml")[0])  # có "chuyên ngành"
KTPM, CNTT = "ky-thuat-phan-mem", "cong-nghe-thong-tin"
ASK_MAJOR = Clarification(slot="major", prompt="Bạn muốn hỏi học phí của ngành nào?", options=[])
ASK_YEAR = Clarification(slot="year", prompt="Bạn muốn hỏi thông tin của năm nào?", options=[])


def turn(question, clarification=None):
    return Turn(question=question, answer="", abstain=False, clarification=clarification)


def run(text, *history, matcher=M):
    return rewrite(make_query(text, history=list(history)), matcher)


# --- nhận diện ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Ngành Kỹ thuật phần mềm học mấy năm?",
        "nganh ky thuat phan mem hoc may nam",
        "KTPM học mấy năm?",
        "ktpm hoc may nam",
        "Mã 7480103 học mấy năm?",
    ],
)
def test_detects_the_major_by_name_alias_or_code_with_or_without_accents(text):
    detected = M.detect(text)
    assert detected.majors == (KTPM,)
    assert detected.major_topic == "học mấy năm"


def test_detects_the_year_and_school_topic():
    detected = M.detect("Ký túc xá năm 2024 có không?")
    assert (detected.year, detected.school_topic, detected.majors) == (2024, True, ())


def test_longest_match_wins_over_a_shared_alias():
    detected = M.detect("Sư phạm tiếng Anh học mấy năm?")
    assert detected.majors == ("su-pham-tieng-anh",) and detected.ambiguous == ()


def test_shared_alias_is_ambiguous():
    detected = M.detect("Học phí tiếng Anh?")
    assert detected.majors == ()
    assert detected.ambiguous == ("ngon-ngu-anh", "su-pham-tieng-anh")
    assert detected.ambiguous_term == "tiếng Anh"


# --- quyết định một lượt -----------------------------------------------------


def test_single_turn_with_major_proceeds_unchanged_with_default_year():
    r = run("Học phí ngành CNTT?")
    assert (r.decision, r.standalone, r.majors, r.major_source) == (
        "proceed", "Học phí ngành CNTT?", (CNTT,), "current",
    )
    assert (r.year, r.year_source) == (2025, "default")


def test_missing_major_asks_with_suggestions():
    r = run("Học phí bao nhiêu?")
    assert r.decision == "clarify" and r.standalone is None
    assert r.clarification == Clarification(
        slot="major",
        prompt="Bạn muốn hỏi học phí của ngành nào?",
        options=["Kỹ thuật phần mềm", "Công nghệ thông tin"],
    )


@pytest.mark.parametrize("text", ["Học mấy năm?", "Ra trường làm gì?"])
def test_verb_phrase_topic_asks_about_the_major_grammatically(text):
    """Review F3: "hỏi ra trường của ngành nào" sai ngữ pháp."""
    assert run(text).clarification.prompt == "Bạn muốn hỏi về ngành nào?"


def test_number_outside_the_year_range_is_not_a_year():
    """Review F5: "2000" là số lượng, không phải năm."""
    r = run("Chỉ tiêu ngành KTPM có 2000 không?")
    assert (r.year, r.year_source) == (2025, "default")


def test_ambiguous_alias_asks_between_exactly_those_majors():
    r = run("Học phí tiếng Anh bao nhiêu?")
    assert r.clarification.options == ["Ngôn ngữ Anh", "Sư phạm Tiếng Anh"]
    assert "tiếng Anh" in r.clarification.prompt


def test_three_or_fewer_majors_never_asks():
    r = run("Học phí bao nhiêu?", matcher=CatalogMatcher(make_catalog(majors=SMALL_MAJORS)))
    assert (r.decision, r.standalone, r.majors) == ("proceed", "Học phí bao nhiêu?", ())


def test_question_without_topic_does_not_ask():
    r = run("Cho mình hỏi chút")
    assert (r.decision, r.needs_major) == ("proceed", False)


def test_school_question_with_a_short_major_word_is_not_rewritten():
    """Review Focus 1: "pháp luật" chứa tên ngành "Luật"; câu cấp trường vẫn đi nguyên văn."""
    r = run("Ký túc xá có theo quy định pháp luật không?")
    assert (r.decision, r.needs_major, r.standalone) == (
        "proceed", False, "Ký túc xá có theo quy định pháp luật không?",
    )


def test_unknown_year_is_used_not_questioned():
    r = run("Học phí KTPM 2023?")
    assert (r.decision, r.year, r.year_source, r.standalone) == (
        "proceed", 2023, "current", "Học phí KTPM 2023?",
    )


# --- kế thừa -------------------------------------------------------------------


def test_follow_up_inherits_the_major():
    r = run("Ra trường làm gì?", turn("Ngành Kỹ thuật phần mềm học mấy năm?"))
    assert (r.majors, r.major_source) == ((KTPM,), "inherited")
    assert r.standalone == "Ra trường làm gì? ngành Kỹ thuật phần mềm"


def test_school_question_does_not_inherit():
    r = run("Trường có ký túc xá không?", turn("Ngành KTPM học mấy năm?"))
    assert (r.majors, r.standalone) == ((), "Trường có ký túc xá không?")


def test_major_survives_a_school_question_in_between():
    r = run("Ra trường làm gì?", turn("KTPM học mấy năm?"), turn("Trường có ký túc xá không?"))
    assert r.majors == (KTPM,)


def test_school_question_with_a_major_word_does_not_change_the_inherited_major():
    """Review I1: "pháp luật" chứa tên ngành "Luật"; câu cấp trường không được đổi ngành kế thừa."""
    r = run(
        "Ra trường làm gì?",
        turn("KTPM học mấy năm?"),
        turn("Ký túc xá có theo quy định pháp luật không?"),
    )
    assert (r.majors, r.major_source) == ((KTPM,), "inherited")


def test_ambiguous_alias_beats_an_unrelated_inherited_major():
    """Review I2: alias khớp nhiều ngành thì hỏi lại, ngành kế thừa không liên quan không nuốt."""
    r = run("Học phí tiếng Anh bao nhiêu?", turn("KTPM học mấy năm?"))
    assert r.decision == "clarify"
    assert r.clarification.options == ["Ngôn ngữ Anh", "Sư phạm Tiếng Anh"]


def test_ambiguous_alias_keeps_an_inherited_major_it_covers():
    r = run("Học phí tiếng Anh bao nhiêu?", turn("Ngôn ngữ Anh học mấy năm?"))
    assert (r.decision, r.majors, r.major_source) == ("proceed", ("ngon-ngu-anh",), "inherited")


def test_two_majors_are_kept_and_inherited_together():
    first = run("So sánh học phí KTPM và CNTT")
    assert (first.majors, first.major_source, first.decision) == (
        (KTPM, CNTT), "current", "proceed",
    )
    r = run("Ra trường làm gì?", turn("So sánh học phí KTPM và CNTT"))
    assert r.standalone == "Ra trường làm gì? ngành Kỹ thuật phần mềm và Công nghệ thông tin"


def test_new_major_replaces_the_inherited_one():
    r = run("Còn CNTT học mấy năm?", turn("KTPM học mấy năm?"))
    assert (r.majors, r.major_source, r.standalone) == (
        (CNTT,), "current", "Còn CNTT học mấy năm?",
    )


def test_inherited_year_is_appended():
    r = run("Ra trường làm gì?", turn("Học phí KTPM 2024?"))
    assert (r.year, r.year_source) == (2024, "inherited")
    assert r.standalone == "Ra trường làm gì? ngành Kỹ thuật phần mềm năm 2024"


# --- câu hỏi giữa các ngành ----------------------------------------------------


def test_question_across_majors_does_not_ask_for_a_major():
    """Review F2: "Ngành nào …" so sánh các ngành, không hỏi "của ngành nào?"."""
    r = run("Ngành nào ra trường dễ xin việc nhất?")
    assert (r.decision, r.needs_major, r.majors) == ("proceed", False, ())


def test_question_across_majors_does_not_inherit_the_major():
    r = run("Ngành nào có học phí thấp nhất?", turn("KTPM học mấy năm?"))
    assert (r.standalone, r.majors) == ("Ngành nào có học phí thấp nhất?", ())


def test_school_question_about_the_number_of_specialties_proceeds():
    """"chuyên ngành" là chủ đề của ngành, nhưng "Trường có …" hỏi cả trường."""
    r = run("Trường có bao nhiêu chuyên ngành?", matcher=REAL)
    assert (r.decision, r.needs_major, r.majors) == ("proceed", False, ())


def test_school_question_naming_a_major_still_updates_the_inherited_major():
    """Câu "Trường có …" không đặt cờ school_topic: ngành nêu trong câu vẫn được kế thừa."""
    r = run("Học phí bao nhiêu?", turn("Trường có ngành KTPM không?"))
    assert (r.majors, r.major_source) == ((KTPM,), "inherited")


def test_specialty_question_still_inherits_the_major_being_discussed():
    """"chuyên ngành nào" hỏi chuyên ngành bên trong ngành đang nói, không phải giữa các ngành."""
    r = run("Có những chuyên ngành nào?", turn("CNTT có bao nhiêu tín chỉ?"), matcher=REAL)
    assert (r.majors, r.major_source) == ((CNTT,), "inherited")
    assert r.standalone == "Có những chuyên ngành nào? ngành Công nghệ thông tin"


# --- câu treo và chống hỏi vòng -----------------------------------------------


def test_reply_to_the_pending_question_is_merged():
    r = run("Kỹ thuật phần mềm", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert (r.decision, r.major_source) == ("proceed", "clarification")
    assert r.standalone == "Học phí bao nhiêu? ngành Kỹ thuật phần mềm"


def test_reply_by_alias_without_accents_is_merged():
    r = run("ktpm", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert r.standalone == "Học phí bao nhiêu? ngành Kỹ thuật phần mềm"


def test_unresolvable_reply_runs_the_pending_question_without_asking_again():
    r = run("không biết nữa", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert (r.decision, r.clarification, r.standalone) == (
        "proceed_after_clarify", None, "Học phí bao nhiêu?",
    )


def test_new_question_after_a_clarification_is_not_asked_the_same_thing_again():
    r = run("Điểm chuẩn bao nhiêu?", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert (r.decision, r.clarification, r.standalone) == (
        "proceed_after_clarify", None, "Điểm chuẩn bao nhiêu?",
    )


def test_new_school_question_after_a_clarification_just_proceeds():
    r = run("Trường có ký túc xá không?", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert (r.decision, r.standalone) == ("proceed", "Trường có ký túc xá không?")


def test_new_question_without_topic_after_a_clarification_is_answered_as_asked():
    """Review F1: câu hỏi mới không chạm chủ đề không bị thay bằng câu treo."""
    r = run("Trường có những ngành nào?", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert (r.decision, r.standalone) == ("proceed", "Trường có những ngành nào?")


def test_where_question_after_a_clarification_is_answered_as_asked():
    r = run("Trường ở đâu vậy?", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert r.standalone == "Trường ở đâu vậy?"


def test_short_unknown_word_after_a_clarification_runs_the_pending_question():
    r = run("IT", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert (r.decision, r.standalone) == ("proceed_after_clarify", "Học phí bao nhiêu?")


def test_ambiguous_alias_as_the_reply_answers_with_all_its_majors():
    """Review F4: ≤ 3 ngành thì trả lời liệt kê, không hỏi lần hai."""
    r = run("tiếng Anh", turn("Học phí bao nhiêu?", ASK_MAJOR))
    assert (r.decision, r.majors, r.major_source) == (
        "proceed", ("ngon-ngu-anh", "su-pham-tieng-anh"), "clarification",
    )
    assert r.standalone == "Học phí bao nhiêu? ngành Ngôn ngữ Anh và Sư phạm Tiếng Anh"


def test_only_the_last_turn_can_leave_a_pending_question():
    r = run(
        "Kỹ thuật phần mềm", turn("Học phí bao nhiêu?", ASK_MAJOR), turn("Trường ở đâu, địa chỉ?")
    )
    assert (r.decision, r.standalone) == ("proceed", "Kỹ thuật phần mềm")


# --- nhiều năm -----------------------------------------------------------------

TWO_YEARS = CatalogMatcher(make_catalog(years=(2024, 2025)))


def test_two_year_catalog_asks_for_the_year_when_the_question_needs_a_major():
    r = run("Học phí ngành KTPM?", matcher=TWO_YEARS)
    assert r.clarification == Clarification(
        slot="year", prompt="Bạn muốn hỏi thông tin của năm nào?", options=["2025", "2024"]
    )


def test_two_year_catalog_does_not_ask_the_year_for_a_school_question():
    r = run("Trường có ký túc xá không?", matcher=TWO_YEARS)
    assert (r.decision, r.year) == ("proceed", None)


def test_year_reply_is_merged():
    r = run("2024", turn("Học phí ngành KTPM?", ASK_YEAR), matcher=TWO_YEARS)
    assert (r.year, r.year_source) == (2024, "clarification")
    assert r.standalone == "Học phí ngành KTPM? năm 2024"


def test_major_then_year_clarifications_chain_back_to_the_first_question():
    history = [turn("Học phí bao nhiêu?", ASK_MAJOR), turn("KTPM", ASK_YEAR)]
    r = run("2024", *history, matcher=TWO_YEARS)
    assert r.standalone == "Học phí bao nhiêu? ngành Kỹ thuật phần mềm năm 2024"


# --- trace ---------------------------------------------------------------------


def test_trace_data_shape():
    r = run("Ra trường làm gì?", turn("KTPM học mấy năm?"))
    assert r.trace_data(M) == {
        "original": "Ra trường làm gì?",
        "standalone": "Ra trường làm gì? ngành Kỹ thuật phần mềm",
        "slots": {
            "major": {"values": [KTPM], "names": ["Kỹ thuật phần mềm"], "source": "inherited"},
            "year": {"value": 2025, "source": "default"},
        },
        "needs_major": True,
        "decision": "proceed",
        "clarification": None,
        "catalog_version": 1,
    }


def test_same_history_gives_the_same_result():
    history = (turn("Học phí bao nhiêu?", ASK_MAJOR),)
    assert run("KTPM", *history) == run("KTPM", *history)
