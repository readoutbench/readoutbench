"""The fixes after the independent reviews of the Round 1 additions (29 October 2026): field-by-field decisions and
robust secondary answers in finalize_labels, labels tied to their pass, tiers only on complete labels, the early
pass's baselines, the Open board's method, ignored answers left unchecked, card checks, and review fixes that win
over the card additions."""
import json
import os
import subprocess
import sys

import pytest

from tdcb.trials import numbers as tnum
from tdcb.trials import round as tround

from test_round import META, _jsonl
from test_round_cards import _card
from test_round1_additions import IDS, _full, _round

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "pilot", "round1_rebuild")
AGE = {"id": "age", "name": "age", "groups": {"under_65": "younger than 65", "65_plus": "65 or older"},
       "basis": "stratification factor"}


def _label_round(tmp_path):
    """A manifest and, beside it, the round's cards: N1 has sex and age subgroups."""
    (tmp_path / "manifest.json").write_text(json.dumps({"closes": "2026-12-10", "early_deadline": "2027-03-31",
                                                        "deadline": "2027-06-30", "final_deadline": "2027-12-31"}))
    c = dict(_card("N1", "time_to_event"), subgroups=[tnum.SEX_SUBGROUP, AGE])
    _jsonl(tmp_path / "cards.jsonl", [c, _card("N2", "time_to_event"), _card("N3", "time_to_event")])
    return tmp_path / "manifest.json"


def _row(n, **k):
    return dict({"nct_id": n, "reported": "yes", "met": "yes", "first_public_date": "2027-02-01",
                 "clear_date": "2027-02-01", "numbers_date": "2027-02-01", "confidence": "high", "control_value": 9.0,
                 "effect_value": 0.7}, **k)


def _finalize(tmp_path, A, B, dec=None, name="lab"):
    man = _label_round(tmp_path)
    args = [sys.executable, os.path.join(SCRIPTS, "finalize_labels.py"), _jsonl(tmp_path / f"{name}_a.jsonl", A),
            _jsonl(tmp_path / f"{name}_b.jsonl", B), str(tmp_path / name), "--as-of", "2027-07-15", "--deadline",
            "2027-06-30", "--manifest", str(man)]
    if dec is not None:
        args += ["--decisions", _jsonl(tmp_path / f"{name}_dec.jsonl", dec)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        return r, None, None
    out = tmp_path / name
    labs = {json.loads(x)["nct_id"]: json.loads(x) for x in open(out / "labels.jsonl") if x.strip()}
    sec = {json.loads(x)["nct_id"]: json.loads(x) for x in open(out / "secondary_disagreements.jsonl") if x.strip()}
    return r, labs, sec


def test_decisions_apply_field_by_field(tmp_path):
    common = dict(key_secondary_met="yes", key_secondary_date="2027-03-01",
                  subgroup_effects={"age": {"65_plus": 0.8}}, subgroup_date="2027-03-01", safety_date="2027-03-01",
                  safety_control=5)
    A = [_row("N1", safety_experimental=10, **common)]
    B = [_row("N1", safety_experimental=14, **common)]
    r, labs, sec = _finalize(tmp_path, A, B)
    assert r.returncode == 0, r.stderr
    assert labs["N1"]["safety_experimental"] is None and sec["N1"]["fields"][0]["field"] == "safety_experimental"
    # the organiser decides only the field in dispute; what both labellers agreed on stays
    r, labs, sec = _finalize(tmp_path, A, B, [{"nct_id": "N1", "safety_experimental": 12, "safety_date": "2027-03-01"}],
                             name="dec")
    assert r.returncode == 0, r.stderr
    lab = labs["N1"]
    assert lab["safety_experimental"] == 12 and lab["safety_control"] == 5 and lab["key_secondary_met"] == 1
    assert lab["subgroup_effects"] == {"age": {"65_plus": 0.8}} and lab["met"] == "yes"
    assert lab["label_deadline"] == "2027-06-30" and lab["labels_as_of"] == "2027-07-15" and "N1" not in sec
    # a decision on the main label keeps the agreed secondary answers too
    A2 = [_row("N1", first_public_date="2027-02-01", clear_date="2027-02-01", **common, safety_experimental=10)]
    B2 = [_row("N1", first_public_date="2027-02-25", clear_date="2027-02-25", **common, safety_experimental=10)]
    r, labs, _ = _finalize(tmp_path, A2, B2, [_row("N1", first_public_date="2027-02-01")], name="main")
    assert r.returncode == 0, r.stderr
    assert labs["N1"]["key_secondary_met"] == 1 and labs["N1"]["safety_experimental"] == 10
    # a secondary-only decision needs an agreed main label
    r, _, _ = _finalize(tmp_path, A2, B2, [{"nct_id": "N1", "safety_experimental": 12, "safety_date": "2027-03-01"}],
                        name="bad")
    assert r.returncode == 1 and "main label is not agreed" in r.stderr


def test_malformed_secondary_answers_reach_the_organiser(tmp_path):
    A = [_row("N1", subgroup_effects="not published", key_secondary_met=["yes"], key_secondary_date="2027-03-01"),
         _row("N2", key_secondary_met="Yes", key_secondary_date="2027-03-01", safety_experimental="12%",
              safety_date="2027-03-01"),
         _row("N3", subgroup_effects={"region": {"asia": 0.7}}, subgroup_date="2027-03-01")]
    B = [_row("N1", subgroup_effects={}, key_secondary_met=None),
         _row("N2", key_secondary_met=True, key_secondary_date="2027-03-01", safety_experimental=12,
              safety_date="2027-03-01"),
         _row("N3", subgroup_effects={"region": {"asia": 0.7}}, subgroup_date="2027-03-01")]
    r, labs, sec = _finalize(tmp_path, A, B)
    assert r.returncode == 0, r.stderr                          # no crash, and the pass is written
    assert labs["N2"]["key_secondary_met"] == 1                  # "Yes" and true read the same
    fields = {n: {f["field"] for f in v["fields"]} for n, v in sec.items()}
    assert {"subgroup_effects", "key_secondary_met"} <= fields["N1"]
    assert "safety_experimental" in fields["N2"]                 # "12%" is not a share: listed, not dropped
    assert "subgroup_effects.region.asia" in fields["N3"]        # not a subgroup of the card
    assert labs["N3"]["subgroup_effects"] == {}


def test_the_leaderboard_needs_labels_read_for_its_pass(tmp_path):
    key, b, r, m = _round(tmp_path)
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=[])))
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    tround.register(str(r), "ref-opus-5-5", _jsonl(tmp_path / "ref.jsonl", _full()), str(meta), "2026-10-31",
                    kind="reference")
    b1 = [{"nct_id": n, "p_met": 0.5} for n in IDS[:4]]           # no p_met_mar
    tround.register(str(r), "ref-b1", _jsonl(tmp_path / "b1.jsonl", b1), str(base), "2026-10-31", kind="reference")
    tround.register(str(r), "ref-b0", _jsonl(tmp_path / "b0.jsonl", b1), str(base), "2026-10-31", kind="reference")
    for k, d in zip(key[:3], ("2027-02-01", "2027-03-15", "2027-05-01")):
        k.update(set="post_cutoff", met=1, first_public_date=d, label_deadline="2027-03-31", labels_as_of="2027-04-30")
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    with pytest.raises(ValueError, match="read for the deadline 2027-03-31"):
        tround.leaderboard(str(b), str(r), n_boot=0, min_scored=1)                     # the first pass, March labels
    with pytest.raises(ValueError, match="p_met_mar is missing"):
        tround.leaderboard(str(b), str(r), n_boot=0, min_scored=1, scoring_pass="early")
    b1 = [{"nct_id": n, "p_met": 0.5, "p_met_mar": 0.55} for n in IDS[:4]]
    for f in ("b1", "b0"):
        (r / "entries" / f"ref-{f}" / "forecasts.jsonl").write_text("".join(json.dumps(o) + "\n" for o in b1))
    lb = tround.leaderboard(str(b), str(r), n_boot=0, min_scored=1, scoring_pass="early")
    assert lb["status"]["labels_as_of"] == "2027-04-30" and lb["status"]["labels_complete"]


def test_open_board_method_and_ignored_answers(tmp_path):
    meta = dict(META, setting="open", web_access=True, retrieval="none", human_in_the_loop=False, fine_tuned=False,
                ensemble=False)
    assert any("contradicts web_access" in e for e in tround.check_meta(meta))
    assert not tround.check_meta(dict(meta, retrieval="web search"))
    assert any("contradicts" in e for e in tround.check_meta(dict(meta, web_access=False, retrieval="web search")))
    assert tround.check_rationale({"reason": "x" * 401}) and not tround.check_rationale({"reason": "drug too weak."})
    _, _, r, _ = _round(tmp_path)
    rows = _full()
    rows[4].update(p_public_mar=0.9, p_public=0.1)               # an operations-only trial: not asked, ignored
    v = tround.validate(str(r), _jsonl(tmp_path / "f.jsonl", rows))
    assert v["ok"], v["errors"]
    assert any("p_public_mar is not asked" in w for w in v["warnings"])


def test_card_checks():
    c = _card("N1", "time_to_event")
    assert tnum.check_card(dict(c, subgroups=[dict(AGE, id="age\n")]))                  # a key with a newline
    assert tnum.check_card(dict(c, subgroup="sex"))                                      # an old cards file
    assert tnum.check_card(dict(c, key_secondary={"endpoint": "OS", "basis": "key"}))
    assert not tnum.check_card(dict(c, key_secondary={"endpoint": "OS", "basis": "named"}))
    assert tnum.subgroup_kind(dict(c, subgroups=[AGE]), "age") == "record"
    assert tnum.subgroup_kind(dict(c, subgroups=[dict(AGE, basis="commonly reported")]), "age") == "experimental"


def test_review_fixes_win_over_the_additions(tmp_path):
    n = "NCT00000031"
    q = tmp_path / "questions.json"
    q.write_text(json.dumps([{"nct_id": n, "questions": "main", "phase": "PHASE3"}]))
    main = dict(_card(n, "time_to_event"), key_secondary=None, subgroups=[])        # the review removed both
    pm = _jsonl(tmp_path / "main.jsonl", [main])
    recs = _jsonl(tmp_path / "recs.jsonl", [{"nct_id": n, "sex": "ALL", "title": "A trial", "primary_outcomes": []}])
    adds = _jsonl(tmp_path / "adds.jsonl", [{"nct_id": n, "key_secondary": {"endpoint": "PFS", "basis": "first listed"},
                                             "subgroups": [AGE]}])
    out = tmp_path / "cards.jsonl"
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "make_cards.py"), str(q), pm, recs, "--out", str(out),
                        "--additions", adds], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    card = json.loads(open(out).readline())
    assert "key_secondary" not in card and "subgroups" not in card and card["next_step"] == "application"
    pm2 = _jsonl(tmp_path / "main2.jsonl", [_card(n, "time_to_event")])              # no review fix: additions apply
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "make_cards.py"), str(q), pm2, recs, "--out", str(out),
                        "--additions", adds], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    card = json.loads(open(out).readline())
    assert card["key_secondary"]["endpoint"] == "PFS" and [s["id"] for s in card["subgroups"]] == ["sex", "age"]
