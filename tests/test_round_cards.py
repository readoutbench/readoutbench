import json
import math

import pytest

from tdcb.trials import numbers as tnum
from tdcb.trials import round as tround

from test_round import META, _build, _jsonl

IDS = ["NCT00000001", "NCT00000002", "NCT00000003", "NCT00000004"]


def _card(nid, kind, numbers="yes", **kw):
    c = {"nct_id": nid, "endpoint": "e", "kind": kind, "better": "lower" if kind == "time_to_event" else "higher",
         "effect_measure": {"time_to_event": "hazard ratio", "responder": "difference in percentage points",
                            "continuous": "difference in means"}[kind],
         "control_measure": {"time_to_event": "median overall survival in the control arm", "responder": "% responding",
                             "continuous": "mean change"}[kind],
         "unit": {"time_to_event": "months", "responder": "%", "continuous": "points"}[kind],
         "experimental_arm": "X", "control_arm": "C", "n_experimental": 200, "n_control": 200,
         "design": "superiority", "margin": None, "alpha_two_sided": 0.05, "numbers": numbers,
         "numbers_reason": None if numbers == "yes" else "arbitrary units", "notes": None}
    c.update(kw)
    return c


CARDS = [_card(IDS[0], "time_to_event"), _card(IDS[1], "responder"), _card(IDS[2], "continuous"),
         _card(IDS[3], "continuous", numbers="no")]


def _round(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    cards = _jsonl(tmp_path / "cards.jsonl", CARDS)
    r = tmp_path / "round"
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=cards, deadline="2027-06-30")
    return key, b, r, m


def _fc(p, ctl=None, eff=None, var=None, risk=None):
    rows = []
    for i, nid in enumerate(IDS):
        o = {"nct_id": nid, "p_met": p[i]}
        if ctl and ctl[i]:
            o["control"] = dict(zip(("median", "low80", "high80"), ctl[i]))
        if eff and eff[i]:
            o["effect"] = dict(zip(("median", "low80", "high80"), eff[i]))
        if var and var[i] is not None:
            o["variability"] = var[i]
        if risk:
            o["main_risk"] = risk
        rows.append(o)
    return rows


CTL = [(12, 9, 15), (30, 20, 40), (-2, -4, 0), None]
EFF = [(0.75, 0.6, 0.95), (15, 5, 25), (3, 1, 5), None]


def test_cards_export_and_validate(tmp_path):
    key, b, r, m = _round(tmp_path)
    assert m["n_number_questions"] == 3 and m["deadline"] == "2027-06-30" and m["cards_sha256"]
    assert (r / "cards.jsonl").exists()
    q = [json.loads(line) for line in (r / "questions.jsonl").read_text().splitlines()]
    assert q[0]["card"]["kind"] == "time_to_event"
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))

    full = _jsonl(tmp_path / "full.jsonl", _fc([0.6, 0.5, 0.7, 0.4], CTL, EFF, [300, None, 8, None], "drug too weak"))
    v = tround.validate(str(r), full, str(meta))
    assert v["ok"], v["errors"]
    assert v["n_number_answers"] == 3

    p_only = _jsonl(tmp_path / "p.jsonl", _fc([0.6, 0.5, 0.7, 0.4]))
    v = tround.validate(str(r), p_only)
    assert v["ok"] and v["n_number_answers"] == 0 and any("p_met only" in w for w in v["warnings"])

    partial = _jsonl(tmp_path / "partial.jsonl", _fc([0.6, 0.5, 0.7, 0.4], CTL[:1] + [None] * 3, EFF[:1] + [None] * 3))
    v = tround.validate(str(r), partial)
    assert not v["ok"] and any("all 3 number questions or for none" in e for e in v["errors"])

    bad = _fc([0.6, 0.5, 0.7, 0.4], CTL, EFF)
    bad[0]["effect"] = {"median": -0.2, "low80": -0.5, "high80": 0.1}      # a ratio below 0
    bad[1]["control"] = {"median": 130, "low80": 120, "high80": 140}     # more than 100% of patients
    bad[2]["effect"] = {"median": 3, "low80": 5, "high80": 1}            # low above high
    bad[3]["main_risk"] = "bad luck"
    bad[2]["variability"] = -1
    v = tround.validate(str(r), _jsonl(tmp_path / "bad.jsonl", bad))
    assert not v["ok"] and len(v["errors"]) == 5, v["errors"]

    extra = _fc([0.6, 0.5, 0.7, 0.4], CTL, EFF)
    extra[3]["control"] = {"median": 1, "low80": 0, "high80": 2}          # not a number question: ignored
    v = tround.validate(str(r), _jsonl(tmp_path / "extra.jsonl", extra))
    assert v["ok"] and any("no number questions" in w for w in v["warnings"])


def test_cards_export_refuses_bad_cards(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    broken = [dict(c) for c in CARDS]
    broken[1]["kind"] = "survival"
    with pytest.raises(ValueError):
        tround.export(str(b), str(tmp_path / "r"), "t", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", broken))
    with pytest.raises(ValueError):                                      # one card missing
        tround.export(str(b), str(tmp_path / "r2"), "t", closes="2026-12-15",
                      cards=_jsonl(tmp_path / "c2.jsonl", CARDS[:3]))


def test_number_scores_and_leaderboard(tmp_path):
    key, b, r, m = _round(tmp_path)
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    ref = _jsonl(tmp_path / "ref.jsonl", _fc([0.6, 0.6, 0.6, 0.6], CTL, EFF, [300, None, 8, None]))
    b0 = _jsonl(tmp_path / "b0.jsonl", _fc([0.65] * 4))
    # sharper and right on the control arms, same effects
    good = _jsonl(tmp_path / "good.jsonl", _fc([0.8, 0.3, 0.7, 0.4], [(20, 18, 22), (40, 35, 45), (-5, -6, -4), None],
                                               EFF, [300, None, 8, None]))
    tround.register(str(r), "ref-b0", b0, str(meta), "2026-10-31", kind="reference")
    tround.register(str(r), "ref-opus-5-5", ref, str(meta), "2026-10-31", kind="reference")
    tround.register(str(r), "team-a", good, str(meta), "2026-12-01")
    # results: trial 1 met (control 20 months, HR 0.7), trial 2 not met (control 40%, +2 points), trial 3 met with
    # no numbers published, trial 4 after the deadline
    key[0].update(set="post_cutoff", met=1, first_public_date="2027-02-01", control_value=20, effect_value=0.7)
    key[1].update(set="post_cutoff", met=0, first_public_date="2027-03-01", control_value=40, effect_value=2)
    key[2].update(set="post_cutoff", met=1, first_public_date="2027-04-01")
    key[3].update(set="post_cutoff", met=1, first_public_date="2027-08-01")
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    lb = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1)
    st = lb["status"]
    assert st["n_scored"] == 3 and st["n_reported_after_deadline"] == 1 and lb["reported_after_deadline"] == [IDS[3]]
    by = {e["id"]: e for e in lb["entries"] + lb["references"]}
    a, ref_row = by["team-a"]["numbers"], by["ref-opus-5-5"]["numbers"]
    assert a["control"]["n_published"] == 2 and a["control"]["n_scored"] == 2
    assert a["effect"]["n_scored"] == 2 and a["n_scored"] == 4
    assert a["control"]["coverage80"] == 1.0 and ref_row["control"]["coverage80"] == 0.5    # 20 months misses (9, 15)
    assert a["control"]["score"] < ref_row["control"]["score"]
    # the reference against its own widths: 1 plus 5 times the median's distance, plus 10 times any miss
    w1 = math.log(0.95 / 0.6)
    s1 = 1 + 5 * abs(math.log(0.7) - math.log(0.75)) / w1                 # HR 0.7 inside (0.6, 0.95)
    s2 = (20 + 10 * (5 - 2) + 5 * (15 - 2)) / 20                          # +2 points misses (5, 25)
    assert math.isclose(ref_row["effect"]["score"], (s1 + s2) / 2)
    assert by["ref-b0"]["numbers"]["n_scored"] == 0 and by["ref-b0"]["consistency"]["n"] == 0
    assert by["team-a"]["consistency"]["n"] == 3
    assert "hazard_ratio" not in by["team-a"]
    assert lb["entries"][0]["id"] == "team-a"                             # ranked by Brier


def test_percentile_score_counts_the_median():
    # same 80% range, different medians, result HR 0.72: the old interval score ties, the percentile score does not
    a, b, y = (0.88, 0.60, 1.05), (0.74, 0.60, 1.05), 0.72
    assert math.isclose(tnum.interval_score(a, y, True), tnum.interval_score(b, y, True))
    sa, sb = tnum.percentile_score(a, y, True), tnum.percentile_score(b, y, True)
    assert sb < sa
    assert math.isclose(sa, tnum.interval_score(a, y, True) + 5 * abs(math.log(y) - math.log(0.88)))
    # on the natural scale, a miss costs 10 times its size on top of the width and the median term
    assert math.isclose(tnum.percentile_score((15, 5, 25), 2, False), 20 + 10 * 3 + 5 * 13)
    # honest percentiles beat shifted ones on average (propriety check on a normal belief)
    import numpy as np
    rng = np.random.default_rng(1)
    ys = rng.normal(0, 1, 20000)
    z = 1.2815515655446004
    honest = np.mean([tnum.percentile_score((0, -z, z), v, False) for v in ys])
    for shifted in ((0.5, -z + 0.5, z + 0.5), (0, -z / 2, z / 2), (0, -2 * z, 2 * z), (0.4, -z, z)):
        assert honest < np.mean([tnum.percentile_score(shifted, v, False) for v in ys])


def test_implied_p_met():
    tte = _card("N", "time_to_event")
    f = {"effect": {"median": 0.75, "low80": 0.6, "high80": 0.95}, "variability": 300}
    p = tnum.implied_p_met(f, tte)
    assert 0.5 < p < 0.95
    weaker = tnum.implied_p_met({"effect": {"median": 0.95, "low80": 0.8, "high80": 1.1}, "variability": 300}, tte)
    assert weaker < p
    assert tnum.implied_p_met({"effect": {"median": 0.75, "low80": 0.6, "high80": 0.95}}, tte) is None
    resp = _card("N", "responder")
    q = tnum.implied_p_met({"control": {"median": 30, "low80": 25, "high80": 35},
                            "effect": {"median": 20, "low80": 12, "high80": 28}}, resp)
    assert q > 0.9
    assert tnum.log_scale(tte, "effect") and tnum.log_scale(tte, "control")
    assert not tnum.log_scale(_card("N", "time_to_event", control_measure="event rate at 2 years", unit="%"), "control")


def test_packet_with_card():
    from tdcb.trials.packets import render
    rec = {"nct_id": "NCT00000009", "title": "A phase 2 trial", "phase": ["PHASE2"], "primary_outcomes":
           [{"measure": "Overall survival", "time_frame": "3 years"}], "fetched_at": "2026-10-25T00:00:00Z"}
    plain = render(rec)
    assert "phase 3 trial" in plain and "hazard ratio" in plain
    with_card = render(rec, card=_card("NCT00000009", "time_to_event"))
    assert "phase 3" not in with_card and "First primary endpoint" not in with_card
    assert "## Question card" in with_card and "Number questions: yes" in with_card
    assert "Lower values of the effect favour" in with_card
    none = render(rec, card=_card("NCT00000009", "continuous", numbers="no"))
    assert "Number questions: none for this trial (arbitrary units)" in none


SEX = {"id": "sex", "name": "sex", "groups": {"women": "women", "men": "men"}, "basis": "phase 3"}
AGE = {"id": "age", "name": "age", "groups": {"under_65": "younger than 65", "65_plus": "65 or older"},
       "basis": "commonly reported"}


def test_subgroup_questions(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    cards = [dict(c) for c in CARDS]
    cards[0]["subgroups"] = [SEX, AGE]               # time-to-event, number questions
    cards[1]["subgroups"] = [SEX]                    # responder, number questions
    r = tmp_path / "round"
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", cards),
                      deadline="2027-06-30")
    assert m["n_subgroup_questions"] == 2 and m["n_subgroups"] == 3
    assert "subgroups" not in json.loads((r / "cards.jsonl").read_text().splitlines()[3])
    bad_card = dict(cards[3], subgroups=[SEX])       # no number questions: a card with subgroups is unusable
    assert any("number questions" in p for p in tnum.check_card(bad_card))
    assert tnum.check_card(dict(cards[0], subgroups=[dict(AGE, groups={"a": "x"})]))       # one group only
    assert tnum.check_card(dict(cards[0], subgroups=[AGE, AGE]))                          # ids repeat
    rows = _fc([0.6, 0.5, 0.7, 0.4], CTL, EFF)
    rows[0]["subgroups"] = {"sex": {"women": {"median": 0.7, "low80": 0.5, "high80": 0.95},
                                    "men": {"median": 0.8, "low80": 0.6, "high80": 1.05}},
                            "age": {"under_65": {"median": 0.7, "low80": 0.5, "high80": 0.95},
                                    "65_plus": {"median": 0.8, "low80": 0.6, "high80": 1.05}}}
    rows[1]["subgroups"] = {"sex": {"women": {"median": 12, "low80": 2, "high80": 22},
                                    "men": {"median": 16, "low80": 6, "high80": 26}}}
    v = tround.validate(str(r), _jsonl(tmp_path / "f.jsonl", rows))
    assert v["ok"], v["errors"]
    assert v["n_subgroup_answers"] == 2
    part = [dict(o) for o in rows]
    del part[1]["subgroups"]
    v = tround.validate(str(r), _jsonl(tmp_path / "p.jsonl", part))
    assert not v["ok"] and any("subgroups: give it for all 2" in e for e in v["errors"])
    bad = [dict(o) for o in rows]
    bad[0]["subgroups"] = dict(rows[0]["subgroups"], sex={"women": {"median": -1, "low80": -2, "high80": 1},
                                                          "men": rows[0]["subgroups"]["sex"]["men"]})
    bad[3]["subgroups"] = rows[1]["subgroups"]
    v = tround.validate(str(r), _jsonl(tmp_path / "b.jsonl", bad))
    assert not v["ok"] and any("subgroups sex women" in e for e in v["errors"])
    assert any("no subgroups question" in w for w in v["warnings"])
    missing_age = [dict(o) for o in rows]
    missing_age[0]["subgroups"] = {"sex": rows[0]["subgroups"]["sex"]}
    v = tround.validate(str(r), _jsonl(tmp_path / "m.jsonl", missing_age))
    assert not v["ok"] and any("age must be an object" in e for e in v["errors"])
    # scoring: the reference against itself scores 1 when the value sits on its median; old label rows still read
    cmap = tnum.load_cards(str(r / "cards.jsonl"))
    preds = {o["nct_id"]: o for o in rows}
    s = tnum.subgroup_scores(preds, preds, cmap, {IDS[0]: {"women_effect": 0.7, "men_effect": 0.8,
                                                           "subgroup_effects": {"age": {"65_plus": 0.8}}},
                                                  IDS[1]: {"subgroup_effects": {"sex": {"women": 12}}}})
    # the age subgroup is a commonly reported one: scored, but shown apart as experimental, not in the overall score
    assert s["n_published"] == 4 and s["n_scored"] == 3 and math.isclose(s["score"], 1.0) and s["coverage80"] == 1.0
    assert s["by_kind"]["sex"]["n_scored"] == 3 and s["by_kind"]["experimental"]["n_scored"] == 1


def test_packet_with_subgroup():
    from tdcb.trials.packets import render
    rec = {"nct_id": "NCT00000009", "title": "A trial", "phase": ["PHASE3"],
           "primary_outcomes": [{"measure": "Overall survival", "time_frame": "3 years"}], "fetched_at": "2026-10-25T00:00:00Z"}
    text = render(rec, card=dict(_card("NCT00000009", "time_to_event"), subgroups=[SEX, AGE]))
    assert "Subgroup questions" in text and "`sex`" in text and "`under_65`" in text and "65 or older" in text
    assert "Subgroup question" not in render(rec, card=_card("NCT00000009", "time_to_event"))
