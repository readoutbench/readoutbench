import json
import math

from tdcb.trials import numbers as tnum
from tdcb.trials import operations as tops
from tdcb.trials import round as tround
from tdcb.trials.packets import render

from test_round import META, _build, _jsonl
from test_round_cards import _card

IDS = ["NCT00000011", "NCT00000012", "NCT00000013", "NCT00000014", "NCT00000015"]
LAUNCH = "2026-10-27"


def _none_card(nid, why="the primary outcomes are safety or drug levels only"):
    c = {k: None for k in tnum.CARD_KEYS}
    c.update(nct_id=nid, endpoint="adverse events", design="none", numbers="no", numbers_reason=why)
    return c


def _equiv_card(nid):
    return _card(nid, "responder", numbers="no", design="equivalence", better=None, alpha_two_sided=None,
                 effect_measure="ratio of objective response rates, test over reference",
                 numbers_reason="equivalence trial")


CARDS = [_card(IDS[0], "time_to_event"), _card(IDS[1], "responder", numbers="no"), _equiv_card(IDS[2]),
         _none_card(IDS[3]), _none_card(IDS[4], "no comparison group")]
RECS = [{"nct_id": IDS[0], "status": "ACTIVE_NOT_RECRUITING", "primary_completion_date": "2026-09-15"},
        {"nct_id": IDS[1], "status": "RECRUITING", "primary_completion_date": "2027-01"},
        {"nct_id": IDS[2], "status": "RECRUITING", "primary_completion_date": "2026-12-15"},
        {"nct_id": IDS[3], "status": "ACTIVE_NOT_RECRUITING", "primary_completion_date": "2027-02-01"},
        {"nct_id": IDS[4], "status": "RECRUITING", "primary_completion_date": "2027-03-01"}]


def _round(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    cards = _jsonl(tmp_path / "cards.jsonl", CARDS)
    ops = _jsonl(tmp_path / "ops.jsonl", [tops.launch_row(r, LAUNCH) for r in RECS])
    r = tmp_path / "round"
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-10", cards=cards, deadline="2027-06-30",
                      operations=ops)
    return key, b, r, m


def test_launch_rows():
    rows = [tops.launch_row(r, LAUNCH) for r in RECS]
    assert rows[0]["questions"] == ["p_stopped", "p_posted"]                 # the date has passed: no p_late
    assert all(r["questions"] == list(tops.REGISTRY_QUESTIONS) for r in rows[1:])   # p_public: added by the export
    assert tops.launch_row({"nct_id": "N", "status": "TERMINATED", "primary_completion_date": "2027-01"}, LAUNCH) is None
    assert tops.launch_row({"nct_id": "N", "status": "COMPLETED", "has_results": True,
                            "primary_completion_date": "2026-08"}, LAUNCH) is None
    assert tops.parse_date("2027-02") .isoformat() == "2027-02-28"


def test_resolve_rules():
    row = tops.launch_row(RECS[1], LAUNCH)                                   # registered 2027-01 = 31 January
    r = lambda **k: tops.resolve(row, dict({"nct_id": IDS[1], "status": "COMPLETED"}, **k))
    assert r(primary_completion_date="2027-06-15")["late"] == 1             # moved 135 days
    assert r(primary_completion_date="2027-03-31")["late"] == 0             # moved 59 days
    assert r(primary_completion_date="2027-01-31", status="RECRUITING")["late"] == 1   # still recruiting long after
    assert r(primary_completion_date="2027-01-31", status="ACTIVE_NOT_RECRUITING")["late"] == 0
    o = r(primary_completion_date="2027-02-20", status="TERMINATED")
    assert o["late"] is None and o["stopped"] == 1 and o["posted"] == 0
    assert r(primary_completion_date="2027-01-31", has_results=True)["posted"] == 1
    assert tops.resolve(row, None) == {"nct_id": IDS[1], "late": None, "stopped": None, "posted": None,
                                       "read_date": tops.OPS_READ_DATE}
    row0 = tops.launch_row(RECS[0], LAUNCH)
    assert tops.resolve(row0, {"status": "COMPLETED", "primary_completion_date": "2027-08-01"})["late"] is None


def test_cards_for_new_designs():
    assert tnum.check_card(_none_card("N")) == []
    assert tnum.check_card(_equiv_card("N")) == []
    bad = _none_card("N")
    bad["numbers"] = "yes"
    assert tnum.check_card(bad)
    assert not tnum.has_p_met(_none_card("N")) and tnum.has_p_met(_equiv_card("N")) and tnum.has_p_met(None)
    assert tnum.implied_p_met({"effect": {"median": 1, "low80": 0.9, "high80": 1.1}, "variability": 100},
                              _equiv_card("N")) is None


def test_export_and_validate_with_operations(tmp_path):
    key, b, r, m = _round(tmp_path)
    assert m["n_trials"] == 5 and m["n_p_met_questions"] == 3 and m["n_number_questions"] == 1
    assert m["n_operations_questions"] == {"p_late": 4, "p_stopped": 5, "p_posted": 5, "p_public": 3,
                                           "p_public_mar": 0, "p_public_dec": 0, "p_amended": 0}   # no early pass
    assert m["operations_read_date"] == tops.OPS_READ_DATE and m["operations_sha256"]
    q = {o["nct_id"]: o for o in map(json.loads, (r / "questions.jsonl").read_text().splitlines())}
    assert q[IDS[3]]["p_met"] is False and q[IDS[0]]["operations"] == ["p_stopped", "p_posted", "p_public"]
    assert q[IDS[3]]["operations"] == ["p_late", "p_stopped", "p_posted"]          # no p_met: no p_public
    assert "p_public (every trial with p_met; its own all-or-none block)" in m["scoring"]
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    ctl, eff = {"median": 12, "low80": 9, "high80": 15}, {"median": 0.75, "low80": 0.6, "high80": 0.95}
    pm_only = [{"nct_id": IDS[0], "p_met": 0.6, "control": ctl, "effect": eff},
               {"nct_id": IDS[1], "p_met": 0.5}, {"nct_id": IDS[2], "p_met": 0.9}]
    v = tround.validate(str(r), _jsonl(tmp_path / "a.jsonl", pm_only), str(meta))
    assert v["ok"], v["errors"]
    assert v["n_operations_answers"] == 0 and any("operations" in w for w in v["warnings"])

    ops = {IDS[0]: {"p_stopped": 0.02, "p_posted": 0.3, "p_public": 0.8}}
    full = [dict(o, **ops.get(o["nct_id"], {"p_late": 0.3, "p_stopped": 0.05, "p_posted": 0.2, "p_public": 0.7}))
            for o in pm_only]
    full += [{"nct_id": IDS[3], "p_late": 0.4, "p_stopped": 0.05, "p_posted": 0.1},
             {"nct_id": IDS[4], "p_late": 0.5, "p_stopped": 0.1, "p_posted": 0.1, "p_met": 0.5}]
    v = tround.validate(str(r), _jsonl(tmp_path / "b.jsonl", full), str(meta))
    assert v["ok"], v["errors"]
    assert v["n_operations_answers"] == 5 and any("no p_met question" in w for w in v["warnings"])

    pub_only = [dict(o, p_public=0.7) for o in pm_only]                     # p_public alone: its own block
    v = tround.validate(str(r), _jsonl(tmp_path / "p.jsonl", pub_only), str(meta))
    assert v["ok"], v["errors"]
    assert v["n_p_public_answers"] == 3 and v["n_operations_answers"] == 0
    v = tround.validate(str(r), _jsonl(tmp_path / "p2.jsonl", pub_only[:2] + pm_only[2:]), str(meta))
    assert not v["ok"] and any("p_public: give it for all 3" in e for e in v["errors"])

    partial = full[:4]                                                       # one operations-only trial missing
    v = tround.validate(str(r), _jsonl(tmp_path / "c.jsonl", partial))
    assert not v["ok"] and any("all 5 trials or of none" in e for e in v["errors"])

    bad = [dict(o) for o in full]
    bad[1]["p_late"] = 1.4
    del bad[2]["p_posted"]
    bad[0]["p_late"] = 0.2                                                   # not asked: ignored with a warning
    del bad[3]["p_stopped"]
    bad = [o for o in bad if o["nct_id"] != IDS[1]] + [{k: v for k, v in bad[1].items() if k != "p_met"}]
    v = tround.validate(str(r), _jsonl(tmp_path / "d.jsonl", bad))
    assert not v["ok"]
    assert sum("p_met must be" in e for e in v["errors"]) == 1
    assert sum("p_late must be" in e for e in v["errors"]) == 1
    assert sum("is missing" in e for e in v["errors"]) == 2
    assert any("p_late is not asked" in w for w in v["warnings"])


def test_leaderboard_with_operations(tmp_path):
    key, b, r, m = _round(tmp_path)
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    sure = [{"nct_id": IDS[0], "p_met": 0.9, "p_stopped": 0.0, "p_posted": 1.0, "p_public": 1.0},
            {"nct_id": IDS[1], "p_met": 0.2, "p_late": 1.0, "p_stopped": 0.0, "p_posted": 0.0, "p_public": 0.0},
            {"nct_id": IDS[2], "p_met": 0.9, "p_late": 0.0, "p_stopped": 0.0, "p_posted": 0.0, "p_public": 0.0},
            {"nct_id": IDS[3], "p_late": 0.0, "p_stopped": 0.0, "p_posted": 0.0},
            {"nct_id": IDS[4], "p_late": 0.0, "p_stopped": 1.0, "p_posted": 0.0}]
    flat = [{k: (0.5 if k.startswith("p_") else v) for k, v in o.items()} for o in sure]
    tround.register(str(r), "ref-b0", _jsonl(tmp_path / "b0.jsonl", [{"nct_id": i, "p_met": 0.6} for i in IDS[:3]]),
                    str(meta), "2026-10-27", kind="reference")
    tround.register(str(r), "sure", _jsonl(tmp_path / "s.jsonl", sure), str(meta), "2026-12-01")
    tround.register(str(r), "flat", _jsonl(tmp_path / "f.jsonl", flat), str(meta), "2026-12-01")
    later = {IDS[0]: {"status": "COMPLETED", "primary_completion_date": "2026-09-15", "has_results": True},
             IDS[1]: {"status": "RECRUITING", "primary_completion_date": "2027-01"},
             IDS[2]: {"status": "COMPLETED", "primary_completion_date": "2026-12-20"},
             IDS[3]: {"status": "COMPLETED", "primary_completion_date": "2027-02-01"},
             IDS[4]: {"status": "TERMINATED", "primary_completion_date": "2027-01-10"}}
    res = tround.resolve_operations(str(r), later)
    assert res[IDS[1]]["late"] == 1 and res[IDS[4]]["late"] is None and res[IDS[4]]["stopped"] == 1
    out = _jsonl(tmp_path / "outcomes.jsonl", list(res.values()))
    key[0].update(set="post_cutoff", met=1, first_public_date="2027-02-01")
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    early = tround.leaderboard(str(b), str(r), n_boot=0, min_scored=1, ops_outcomes=out, labels_as_of="2027-05-01")
    assert early["status"]["p_public_resolved"] is None and "p_public" not in early["entries"][0]
    lb = tround.leaderboard(str(b), str(r), n_boot=0, min_scored=1, ops_outcomes=out, labels_as_of="2027-07-15")
    st = lb["status"]
    assert st["n_p_met_questions"] == 3 and st["n_scored"] == 1 and st["n_pending"] == 2
    # p_public after the deadline: trial 1 reported (1); trials 2 and 3 still open, so silent at the deadline (0)
    assert st["p_public_resolved"] == 3 and math.isclose(st["share_public_by_deadline"], 1 / 3)
    assert math.isclose(st["share_met_by_deadline"], 1 / 3) and st["labels_as_of"] == "2027-07-15"
    assert st["operations_resolved"] == {"p_late": 3, "p_stopped": 5, "p_posted": 5}
    by = {e["id"]: e for e in lb["entries"] + lb["references"]}
    assert by["sure"]["operations"]["brier"] == 0 and by["sure"]["operations"]["skill"] == 1
    assert math.isclose(by["flat"]["operations"]["brier"], 0.25)
    assert by["ref-b0"]["operations"]["n_scored"] == 0 and by["ref-b0"]["operations"]["brier"] is None
    assert by["sure"]["operations"]["p_late"]["share"] == 1 / 3
    assert "p_public" not in by["sure"]["operations"]                       # scored apart from the registry questions
    assert by["sure"]["p_public"]["brier"] == 0 and math.isclose(by["flat"]["p_public"]["brier"], 0.25)
    assert by["ref-b0"]["p_public"]["n_scored"] == 0
    # the joint score: p_met x p_public against "a statement by the deadline, and met"
    assert math.isclose(by["sure"]["met_by_deadline"]["brier"], 0.01 / 3) and by["ref-b0"]["met_by_deadline"]["n_scored"] == 0
    assert tround.leaderboard(str(b), str(r), n_boot=0, min_scored=1, ops_outcomes=out)["status"]["p_public_resolved"] is None


def test_packets_for_new_designs():
    rec = {"nct_id": "NCT00000019", "title": "A trial", "phase": ["PHASE2"], "fetched_at": "2026-10-25T00:00:00Z",
           "primary_outcomes": [{"measure": "Adverse events", "time_frame": "1 year"}],
           "primary_completion_date": "2027-01"}
    row = tops.launch_row(dict(rec, status="RECRUITING"), LAUNCH)
    none = render(rec, card=_none_card("NCT00000019"), ops=row, ops_read="2027-08-31")
    assert "Forecast how this randomized trial runs" in none and "neither `p_met` nor number" in none
    assert "no efficacy goal to meet (the primary outcomes are safety or drug levels only)" in none
    assert "## Operations questions" in none and "after 2027-05-01" in none and "status recruiting" in none
    assert "`p_public`" not in none
    pub = render(rec, card=_none_card("NCT00000019"), ops=dict(row, questions=row["questions"] + ["p_public"]),
                 ops_read="2027-08-31", deadline="2027-06-30")
    assert "`p_public` (decided by the round's labellers" in pub and "comes out by 2027-06-30" in pub
    eq = render(rec, card=_equiv_card("NCT00000019"))
    assert "An equivalence trial" in eq and "Reference product: C" in eq and "Operations" not in eq
    past = render(rec, card=_card("NCT00000019", "responder"),
                  ops=tops.launch_row(dict(rec, primary_completion_date="2026-09"), LAUNCH), ops_read="2027-08-31")
    assert "`p_late`: not asked" in past
