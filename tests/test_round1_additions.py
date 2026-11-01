"""The Round 1 additions of 30 October 2026: three passes, the number tiers, and the safety, key secondary, subgroup,
next-step and amendment questions; assumptions; the rationale the Models board needs; the Open board's method."""
import json

import pytest

from tdcb.trials import numbers as tnum
from tdcb.trials import operations as tops
from tdcb.trials import round as tround
from tdcb.trials.packets import card_section, ops_section

from test_round import META, _build, _jsonl
from test_round_cards import CTL, EFF, _card

IDS = ["NCT00000021", "NCT00000022", "NCT00000023", "NCT00000024", "NCT00000025"]
LAUNCH = "2026-10-27"
KS = {"endpoint": "overall survival", "basis": "first listed"}
AGE = {"id": "age", "name": "age", "groups": {"under_65": "younger than 65", "65_plus": "65 or older"},
       "basis": "commonly reported"}


def _cards():
    c0 = _card(IDS[0], "time_to_event", key_secondary=KS, next_step="application", subgroups=[tnum.SEX_SUBGROUP, AGE])
    c1 = _card(IDS[1], "responder", key_secondary=KS, next_step="phase 3")
    c2 = _card(IDS[2], "continuous", next_step="phase 3")
    c3 = _card(IDS[3], "responder", numbers="no", design="equivalence", better=None, alpha_two_sided=None,
               numbers_reason="equivalence trial", next_step="application")
    c4 = {k: None for k in tnum.CARD_KEYS}
    c4.update(nct_id=IDS[4], endpoint="adverse events", design="none", numbers="no", numbers_reason="safety only")
    return [c0, c1, c2, c3, c4]


RECS = [{"nct_id": n, "status": "ACTIVE_NOT_RECRUITING", "primary_completion_date": d}
        for n, d in zip(IDS, ("2026-09-15", "2027-01", "2026-12-15", "2027-02-01", "2027-03-01"))]


def _round(tmp_path, early="2027-03-31"):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    ops = _jsonl(tmp_path / "ops.jsonl", [tops.launch_row(r, LAUNCH) for r in RECS])
    r = tmp_path / "round"
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-10", cards=_jsonl(tmp_path / "c.jsonl", _cards()),
                      deadline="2027-06-30", final_deadline="2027-12-31", early_deadline=early, operations=ops)
    return key, b, r, m


def _rng(m, lo, hi):
    return {"median": m, "low80": lo, "high80": hi}


def _full():
    """A line for every trial, every block answered."""
    rows = []
    for i, n in enumerate(IDS):
        o = {"nct_id": n, "p_late": 0.2, "p_stopped": 0.05, "p_posted": 0.1, "p_amended": 0.1}
        if i < 4:
            o.update(p_met=0.6, p_met_mar=0.7, p_met_dec=0.55, p_public_mar=0.2, p_public=0.5, p_public_dec=0.8,
                     p_next_step=0.4, rationale="Earlier trials of the class worked.")
        if i < 3:
            o.update(control=_rng(*CTL[i]), effect=_rng(*EFF[i]),
                     safety={"experimental": _rng(8, 4, 14), "control": _rng(5, 2, 9)})
        if i < 2:
            o["p_key_secondary"] = 0.45
        if i == 0:
            o["subgroups"] = {"sex": {"women": _rng(0.75, 0.6, 0.95), "men": _rng(0.75, 0.6, 0.95)},
                              "age": {"under_65": _rng(0.75, 0.6, 0.95), "65_plus": _rng(0.75, 0.6, 0.95)}}
            o["assumptions"] = [{"claim": "Docetaxel's median OS in 2L NSCLC is about 9 months.",
                                 "source": "REVEL, 2014"}]
        rows.append(o)
    return rows


def _drop(rows, field, at=0):
    rows = [dict(o) for o in rows]
    rows[at].pop(field)
    return rows


def test_export_asks_the_new_questions(tmp_path):
    _, _, r, m = _round(tmp_path)
    assert m["early_deadline"] == "2027-03-31" and m["n_safety_questions"] == 3
    assert m["n_key_secondary_questions"] == 2 and m["n_next_step_questions"] == 4
    assert m["n_subgroup_questions"] == 1 and m["n_subgroups"] == 2
    q = m["n_operations_questions"]
    assert q["p_public_mar"] == q["p_public"] == q["p_public_dec"] == 4 and q["p_amended"] == 5
    assert "early pass" in m["scoring"] and "number tier" in m["scoring"] and "p_amended" in m["scoring"]
    with pytest.raises(ValueError):                         # an early pass after the first deadline makes no sense
        _round(tmp_path / "x", early="2027-07-31")
    rows = [json.loads(x) for x in (r / "operations.jsonl").read_text().splitlines()]
    assert rows[4]["questions"][-1] == "p_amended" and "p_public" not in rows[4]["questions"]


def test_cards_with_the_additions_are_checked():
    c0 = _cards()[0]
    assert tnum.check_card(c0) == []
    assert tnum.check_card(dict(c0, next_step="phase 4"))
    assert tnum.check_card(dict(c0, key_secondary={"basis": "named"}))                     # no endpoint
    assert tnum.check_card(dict(_cards()[3], key_secondary=KS))                             # not on an equivalence card
    assert tnum.check_card(dict(c0, subgroups=[dict(AGE, id="Age group")]))                 # ids are short keys
    assert tnum.key_secondary(_cards()[2]) is None and tnum.next_step(_cards()[4]) is None
    assert tnum.has_safety(_cards()[0]) and not tnum.has_safety(_cards()[3])


def test_validate_blocks_monotone_public_and_assumptions(tmp_path):
    _, _, r, _ = _round(tmp_path)
    v = tround.validate(str(r), _jsonl(tmp_path / "f.jsonl", _full()))
    assert v["ok"], v["errors"]
    assert (v["n_safety_answers"], v["n_key_secondary_answers"], v["n_next_step_answers"]) == (3, 2, 4)
    assert (v["n_p_public_mar_answers"], v["n_p_public_dec_answers"], v["n_p_amended_answers"]) == (4, 4, 5)
    assert v["n_subgroup_answers"] == 1 and v["n_assumptions"] == 1
    for field, at in (("safety", 1), ("p_key_secondary", 1), ("p_next_step", 2), ("p_public_mar", 0),
                      ("p_public_dec", 3), ("p_amended", 4)):
        v = tround.validate(str(r), _jsonl(tmp_path / f"no_{field}.jsonl", _drop(_full(), field, at)))
        assert not v["ok"] and any(e.startswith(field) for e in v["errors"]), (field, v["errors"])
    for field in ("p_met_mar", "p_met_dec", "rationale", "assumptions"):            # trial by trial: may be left out
        assert tround.validate(str(r), _jsonl(tmp_path / f"opt_{field}.jsonl", _drop(_full(), field)))["ok"]
    bad = _full()
    bad[0]["p_public_mar"] = 0.9                                                   # above p_public: incoherent
    v = tround.validate(str(r), _jsonl(tmp_path / "mono.jsonl", bad))
    assert not v["ok"] and any("p_public_mar <= p_public" in e for e in v["errors"])
    bad = _full()
    bad[1]["p_met_mar"] = 1.5
    bad[2]["safety"] = {"experimental": _rng(8, 4, 140), "control": _rng(5, 2, 9)}
    bad[0]["assumptions"] = [{"claim": "x", "source": "javascript:alert(1)"}]
    bad[3]["assumptions"] = [{"claim": "x", "source": "y"}] * 4
    v = tround.validate(str(r), _jsonl(tmp_path / "bad.jsonl", bad))
    errs = " | ".join(v["errors"])
    assert "p_met_mar must be a number" in errs and "safety experimental is a percentage" in errs
    assert "links must be http" in errs and "at most 3" in errs


def test_rationale_needed_on_the_models_board_only(tmp_path):
    _, _, r, m = _round(tmp_path)
    rows = _drop(_full(), "rationale", at=1)
    closed = tmp_path / "closed.json"
    closed.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=["model-x"],
                                      model_version="model-x-2026-09-01", provider="Example AI",
                                      prompt_sha256="0" * 64)))
    v = tround.validate(str(r), _jsonl(tmp_path / "f.jsonl", rows), str(closed))
    assert not v["ok"] and any("rationale" in e and IDS[1] in e for e in v["errors"])
    opn = tmp_path / "open.json"
    opn.write_text(json.dumps(META))
    assert tround.validate(str(r), _jsonl(tmp_path / "g.jsonl", rows), str(opn))["ok"]


def test_packets_show_the_new_questions():
    text = "\n".join(card_section(_cards()[0]))
    assert "Safety question" in text and "Key secondary endpoint: overall survival" in text
    assert "marketing application" in text and "`65_plus` = 65 or older" in text
    assert "phase 3 trial of the experimental drug" in "\n".join(card_section(_cards()[1]))
    eq = "\n".join(card_section(_cards()[3]))
    assert "Safety question" not in eq and "Next step" in eq                    # equivalence: the next step only
    row = {"nct_id": IDS[0], "status": "ACTIVE_NOT_RECRUITING", "primary_completion_date": "2026-09-15",
           "questions": ["p_stopped", "p_posted", "p_public_mar", "p_public", "p_public_dec", "p_amended"]}
    ops = "\n".join(ops_section(row, "2027-08-31", "2027-06-30", "2027-03-31", "2027-12-31"))
    assert "`p_public_mar`" in ops and "`p_amended`" in ops and "record frozen in the round" in ops
    assert "by 31 March 2027 (`p_public_mar`)" in ops and "by 31 December 2027 (`p_public_dec`)" in ops
    later = "\n".join(ops_section(row, "2028-08-31", "2028-06-30", "2028-02-29", "2028-12-31"))   # dates follow the round
    assert "by 29 February 2028 (`p_public_mar`)" in later


def test_passes_score_their_own_fields_and_number_tiers(tmp_path):
    key, b, r, m = _round(tmp_path)
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=[])))
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    ref = _full()
    tround.register(str(r), "ref-opus-5-5", _jsonl(tmp_path / "ref.jsonl", ref), str(meta), "2026-10-31",
                    kind="reference")
    b1 = [{"nct_id": n, "p_met": 0.5, "p_met_mar": 0.6} for n in IDS[:4]]
    tround.register(str(r), "ref-b1", _jsonl(tmp_path / "b1.jsonl", b1), str(base), "2026-10-31", kind="reference")
    tround.register(str(r), "ref-b0", _jsonl(tmp_path / "b0.jsonl", b1), str(base), "2026-10-31", kind="reference")
    sharp = _full()                                    # the same, with medians on the results and narrower ranges
    for o in sharp[:3]:
        o["control"] = _rng(o["control"]["median"], o["control"]["median"] - 0.1, o["control"]["median"] + 0.1)
        o["effect"] = _rng(o["effect"]["median"], o["effect"]["median"] * 0.99, o["effect"]["median"] * 1.01)
    no_mar = [{k: v for k, v in o.items() if k != "p_met_mar"} for o in _full()]
    tround.register(str(r), "team-sharp", _jsonl(tmp_path / "s.jsonl", sharp), str(meta), "2026-11-20")
    tround.register(str(r), "team-plain", _jsonl(tmp_path / "p.jsonl", no_mar), str(meta), "2026-11-21")
    for k, d, met in zip(key[:4], ("2027-02-01", "2027-03-15", "2027-05-01", "2027-09-01"), (1, 0, 1, 1)):
        k.update(set="post_cutoff", met=met, first_public_date=d)
    for k, (c, e) in zip(key[:3], zip(CTL, EFF)):
        k.update(control_value=c[0], effect_value=e[0], safety_experimental=8, safety_control=5)
    key[0].update(key_secondary_met=1, subgroup_effects={"age": {"65_plus": 0.75}})
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    early = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1, scoring_pass="early",
                               labels_as_of="2027-04-30")
    interim = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1, min_numbers_scored=2)
    assert not interim["status"]["tiers_shown"] and not interim["status"]["ranked"]      # labels not complete yet
    assert all("tier" not in x and "number_tier" not in x for x in interim["entries"])
    first = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1, min_numbers_scored=2,
                               labels_as_of="2027-07-15")
    final = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1, scoring_pass="final")
    assert early["status"]["n_scored"] == 2 and first["status"]["n_scored"] == 3 and final["status"]["n_scored"] == 4
    assert early["status"]["early_look"] and early["status"]["tiers_shown"] and not early["status"]["ranked"]
    assert first["status"]["ranked"] and not final["status"]["tiers_shown"]
    e = {x["id"]: x for x in early["entries"] + early["references"]}
    # the early pass scores p_met_mar (0.7 against outcomes 1, 0) and falls back to p_met (0.6) where it is missing
    assert abs(e["team-sharp"]["brier"] - (0.3 ** 2 + 0.7 ** 2) / 2) < 1e-9
    assert abs(e["team-plain"]["brier"] - (0.4 ** 2 + 0.6 ** 2) / 2) < 1e-9
    assert abs(e["ref-b1"]["brier"] - (0.4 ** 2 + 0.6 ** 2) / 2) < 1e-9                 # B1's p_met_mar
    assert e["team-sharp"]["p_public"]["n_resolved"] == 4                       # p_public_mar, from the early labels
    f = {x["id"]: x for x in first["entries"] + first["references"]}
    assert f["team-sharp"]["number_tier"] in (1, 2, 3) and "number_tier" not in f["ref-opus-5-5"]
    assert f["team-sharp"]["number_tier_test"]["score_minus_reference"] < 0
    assert f["team-sharp"]["safety"]["n_scored"] == 6 and f["team-sharp"]["key_secondary"]["n_resolved"] == 1
    sg = f["team-sharp"]["subgroups"]                 # a commonly reported subgroup: shown apart, as experimental
    assert sg["n_scored"] == 0 and sg["by_kind"]["experimental"]["n_scored"] == 1
    d = {x["id"]: x for x in final["entries"]}
    assert abs(d["team-plain"]["brier"] - ((0.45) ** 2 + 0.55 ** 2 + 0.45 ** 2 + 0.45 ** 2) / 4) < 1e-9   # p_met_dec


def test_open_board_method_and_no_cost_cap(tmp_path):
    _, _, r, _ = _round(tmp_path)
    fc = _jsonl(tmp_path / "f.jsonl", _full())
    p = tmp_path / "m.json"
    p.write_text(json.dumps(dict(META, cost_usd_per_trial=1000)))
    assert tround.validate(str(r), fc, str(p))["ok"]
    for k in ("retrieval", "human_in_the_loop", "fine_tuned", "ensemble"):
        p.write_text(json.dumps({x: v for x, v in META.items() if x != k}))
        assert any(k in e for e in tround.validate(str(r), fc, str(p))["errors"])
    p.write_text(json.dumps(dict(META, ensemble="yes")))
    assert not tround.validate(str(r), fc, str(p))["ok"]
