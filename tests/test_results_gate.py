"""results_gate: the bar a trial's check must meet to stay in the round."""
import json
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pilot", "round1_rebuild"))
from results_gate import classify  # noqa: E402

GOOD = {"nct_id": "N1", "reported": "no", "stop_announced": "no", "checked_on": "2026-10-30",
        "queries": ["drug x topline", "sponsor x news"], "pages_checked": ["opened: https://sponsor.com/news"]}
BAR = dict(min_queries=2, min_opened=1, checked_from="2026-10-29")


def one(row, record=None):
    return classify([[row]], {"N1": record} if record else None, ["N1"], **BAR)["N1"][0]


def test_a_good_row_is_clean():
    assert one(GOOD) == "clean"


def test_registry_pages_unclear_stop_old_date_and_missing_language_are_not_clean():
    assert one(dict(GOOD, pages_checked=["opened: https://clinicaltrials.gov/study/N1"])) == "shallow"
    assert one(dict(GOOD, pages_checked=["opened: https://ichgcp.net/clinical-trials-registry/N1"])) == "shallow"
    assert one(dict(GOOD, stop_announced="unclear")) == "shallow"
    assert one(dict(GOOD, checked_on="2025-01-01")) == "shallow"
    assert one(dict(GOOD, queries=["a", "a "])) == "shallow"
    assert one(GOOD, {"countries": ["China"]}) == "shallow"
    assert one(dict(GOOD, queries=["drug x topline", "恒瑞 结果"]), {"countries": ["China"]}) == "clean"
    assert one(dict(GOOD, reported="unchecked")) == "missing"


def test_a_finding_sticks_over_a_later_no():
    found = dict(GOOD, reported="yes")
    assert classify([[found], [GOOD]], None, ["N1"], **BAR)["N1"][0] == "finding"


def test_search_pages_aggregators_bad_dates_and_padded_queries_are_not_clean():
    for page in ("opened: https://www.google.com/search?q=x", "opened: https://synapse.patsnap.com/drug/x",
                 "opened: https://trialsearch.who.int/Trial2.aspx?TrialID=x", "opened: https://www.bing.com/search?q=x"):
        assert one(dict(GOOD, pages_checked=[page])) == "shallow", page
    assert one(dict(GOOD, checked_on="20261030")) == "shallow"
    assert one(dict(GOOD, queries=["drug x topline", "Drug X, topline!"])) == "shallow"
    assert one(dict(GOOD, queries=["drug x topline", "x 的"]), {"countries": ["China"]}) == "shallow"


def test_flagged_rows_need_a_sign_off_and_failure_words_are_read_after_the_url():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    row = {"nct_id": "NCT1", "reported": "no", "stop_announced": "no", "queries": ["drug x phase 3", "sponsor y news"],
           "pages_checked": ["opened: https://sponsor.example.com/news/error-free-empty-launch"],
           "notes": "UNSURE: a sister trial read out", "checked_on": "2026-10-30"}
    assert g.why_not_clean(row) == "flagged for review by the checking agent, not signed off"
    assert g.why_not_clean(row, signed_off={"NCT1"}) is None          # "error"/"empty" inside the URL do not reject it
    row2 = dict(row, notes="", pages_checked=["opened: https://sponsor.example.com/news (access denied)"])
    assert g.why_not_clean(row2) == "no page opened beyond the registry and its mirrors"
    for u in ("https://web.archive.org/web/2026/https://clinicaltrials.gov/study/NCT1",
              "https://www.marketscreener.com/news/x", "https://finance.yahoo.com/news/x"):
        assert g.why_not_clean(dict(row2, pages_checked=["opened: " + u])) is not None
    assert g.why_not_clean(dict(row2, pages_checked=["opened: https://mtech-pharma.com/news/1"])) is None


def test_trial_listings_and_quote_sites_do_not_count():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    row = {"nct_id": "NCT1", "reported": "no", "stop_announced": "no", "queries": ["drug x phase 3", "sponsor y news"],
           "notes": "", "checked_on": "2026-10-30"}
    for u in ("https://www.whichtrial.com/trial/NCT1", "https://www.astrazenecaclinicaltrials.com/study/D1/",
              "https://ctis.eu/trial/2023-1", "https://www.tipranks.com/news/x", "https://m.gelonghui.com/p/1",
              "https://pdf.dfcfw.com/pdf/H2_AN202610.pdf"):
        assert g.why_not_clean(dict(row, pages_checked=["opened: " + u])) is not None, u
    assert g.why_not_clean(dict(row, pages_checked=["opened: https://www.astrazeneca.com/media-centre/press-releases/x"])) is None


def test_a_safety_statement_on_a_safety_primary_needs_a_sign_off():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    rec = {"countries": ["United States"], "primary_outcomes": [{"measure": "Number of participants with TEAEs"}]}
    eff = {"countries": ["United States"], "primary_outcomes": [{"measure": "Change in HbA1c at week 26"}]}
    row = {"nct_id": "NCT1", "reported": "no", "stop_announced": "no", "queries": ["drug x phase 2", "sponsor y news"],
           "pages_checked": ["opened: https://www.sponsor.com/news/x"], "notes": "The sponsor said the drug was well tolerated.",
           "checked_on": "2026-10-30"}
    assert "safety statement" in g.why_not_clean(row, rec)
    assert g.why_not_clean(row, rec, signed_off={"NCT1"}) is None
    assert g.why_not_clean(row, eff) is None


def test_a_safety_statement_is_reported_before_any_depth_reason():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    rec = {"countries": ["United States"], "primary_outcomes": [{"measure": "Incidence of TEAEs"}]}
    base = {"nct_id": "NCT1", "reported": "no", "stop_announced": "no", "queries": ["drug x phase 2", "sponsor y news"],
            "pages_checked": ["opened: https://www.sponsor.com/news/x"], "checked_on": "2026-10-30",
            "notes": "The sponsor said the drug was well tolerated."}
    for broken in ({"queries": ["drug x"]}, {"pages_checked": []}, {"notes": base["notes"] + " UNSURE"},
                   {"checked_on": "2026-01-01"}, {"reported": "unchecked"}, {"stop_announced": "unchecked"}):
        assert "safety statement" in g.why_not_clean(dict(base, **broken), rec, checked_from="2026-10-29"), broken


def test_a_safety_statement_in_the_quote_snippets_or_an_earlier_row_is_not_masked():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    rec = {"countries": ["United States"], "primary_outcomes": [{"measure": "Incidence of TEAEs"}]}
    clean = {"nct_id": "NCT1", "reported": "no", "stop_announced": "no", "queries": ["drug x phase 2", "sponsor y news"],
             "pages_checked": ["opened: https://www.sponsor.com/news/x"], "checked_on": "2026-10-30", "notes": "Nothing found."}
    assert g.why_not_clean(clean, rec) is None
    for where in ({"quote": "No new safety signals were seen."}, {"result": "well tolerated"},
                  {"pages_checked": clean["pages_checked"] + ["snippet: sponsor says drug x was well tolerated"]}):
        assert "safety statement" in g.why_not_clean(dict(clean, **where), rec), where
    # a safety row in an earlier file, then a later clean row: the trial is not clean
    early = dict(clean, quote="favourable safety profile")
    out = g.classify([[early], [clean]], {"NCT1": rec}, ["NCT1"])
    assert out["NCT1"][0] == "shallow" and "safety statement" in out["NCT1"][1]
    out = g.classify([[early], [clean]], {"NCT1": rec}, ["NCT1"], signed_off={"NCT1"})
    assert out["NCT1"] == ("clean", None)


def test_a_safety_statement_in_chinese_japanese_or_korean_is_caught():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    rec = {"countries": ["China"], "primary_outcomes": [{"measure": "Incidence of adverse events"}]}
    clean = {"nct_id": "NCT1", "reported": "no", "stop_announced": "no", "queries": ["药物X 研究结果 III期", "drug x phase 3"],
             "pages_checked": ["opened: https://www.sponsor.cn/news/1"], "checked_on": "2026-10-31", "notes": "Nothing found."}
    assert g.why_not_clean(clean, rec) is None
    for words in ("该药物安全性良好，耐受性良好", "未发现新的安全信号", "安全性は良好であった", "안전성이 우수한 것으로 나타났다"):
        assert "safety statement" in g.why_not_clean(dict(clean, quote=words), rec), words


def test_any_cjk_safety_mention_counts_judgement_or_not():
    """No phrase list for Chinese, Japanese and Korean: every safety or adverse-event mention counts (on a trial with a
    safety primary it then needs a sign-off), so no judgement wording can slip through."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    every_probe = [  # judgements found in four review rounds, and neutral protocol text: all count now
        "忍容性良好", "安全性に問題なし", "未發現新的安全信號", "耐受性佳", "不良反应可控", "안전성 프로파일이 양호", "내약성이 좋았다",
        "未观察到新的安全信号", "安全性特征与既往研究一致", "不良事件多为轻中度", "安全性数据令人满意", "安全性、良好",
        "未见非预期的安全性事件", "不良反应发生率低", "治疗相关不良事件发生率较低且可逆", "患者对药物普遍耐受", "未觀察到新的安全性訊號",
        "有害事象の多くは軽度であった", "安全性プロファイルは既存の報告と一致していた", "이상반응은 대부분 경증이었다", "부작용은 경미했다",
        "评价安全性和优效性的III期研究", "若安全性良好，则进入II期", "안전성이 양호한지 평가한다", "安全性の評価、及び良好なQOLの維持"]
    assert [w for w in every_probe if not g.has_safety_words(w)] == []
    for words in ("주요 평가변수는 무진행 생존기간", "ORR 45% vs 27.5%", "无进展生存期显著延长", "全生存期の延長", "safety analysis set"):
        assert not g.has_safety_words(words), words


def test_every_string_in_a_row_is_scanned_except_our_queries():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    row = {"nct_id": "NCT1", "queries": ["drug x well tolerated"], "notes": "nothing found"}
    assert not g.safety_text(row)                         # our own search words do not count
    for extra in ({"summary": "The drug was well tolerated."}, {"evidence": {"text": "安全性良好"}},
                  {"sources": ["https://news.example/drug-x-well-tolerated"]}, {"stop_reason": "no new safety signals"}):
        assert g.safety_text(dict(row, **extra)), extra


def test_cjk_terms_spaces_and_ae_abbreviations_inside_cjk_wording():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    must = ["SAE发生率低", "TEAE均为1级", "发生3例SAE", "AE多为1-2级", "AE发生率", "TRAEs 발생률 낮음", "이상 반응", "이상 사례",
            "유해사례", "副反应", "副反應", "反应原性", "反應原性", "有害反応", "耐容性", "安 全 性 良 好", "안 전 성 양호"]
    assert [w for w in must if not g.has_safety_words(w)] == []
    for words in ("耐药性", "Primary outcomes are TEAEs; the sponsor (美貝克) site was opened", "TEAEs were not reported",
                  "无进展生存期显著延长"):
        assert not g.has_safety_words(words), words


def test_sign_offs_need_a_reason_and_date_and_cover_only_rows_up_to_that_date(tmp_path):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pilot", "round1_rebuild"))
    import results_gate as g
    f = tmp_path / "signed_off.jsonl"
    ok = {"nct_id": "nct1", "decision": "keep", "reason": "the words are in a URL about another study", "date": "2026-10-30"}
    f.write_text(json.dumps(ok) + "\n")
    assert g.load_signed_off(str(f), ["NCT1"]) == {"NCT1": "2026-10-30"}
    for bad, msg in ((dict(ok, nct_id="NCT9"), "not a trial"), (dict(ok, reason=""), "needs a reason"),
                     ({k: v for k, v in ok.items() if k != "date"}, "needs a date")):
        f.write_text(json.dumps(bad) + "\n")
        with pytest.raises(ValueError, match=msg):
            g.load_signed_off(str(f), ["NCT1"])
    rec = {"countries": ["United States"], "primary_outcomes": [{"measure": "Incidence of TEAEs"}]}
    row = {"nct_id": "NCT1", "reported": "no", "stop_announced": "no", "queries": ["drug x phase 2", "sponsor y news"],
           "pages_checked": ["opened: https://www.sponsor.com/news/x"], "checked_on": "2026-10-30",
           "notes": "Nothing found.", "quote": "well tolerated"}
    so = {"NCT1": "2026-10-30"}
    assert g.why_not_clean(row, rec, signed_off=so) is None                       # the row the sign-off was about
    newer = dict(row, checked_on="2026-11-02", quote="安全性良好")
    assert "safety statement" in g.why_not_clean(newer, rec, signed_off=so)      # a newer mention needs a new one
    out = g.classify([[row], [dict(newer, quote=None)]], {"NCT1": rec}, ["NCT1"], signed_off=so)
    assert out["NCT1"] == ("clean", None)                                         # newer row clean: still covered
    out = g.classify([[row], [newer], [dict(newer, quote=None, checked_on="2026-11-03")]], {"NCT1": rec}, ["NCT1"],
                     signed_off=so)
    assert "safety statement" in out["NCT1"][1]                                   # a newer mention, then a clean row
