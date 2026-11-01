"""Tests for the changes made after the outside reviews of Round 1 (26 Oct 2026): sister-trial bootstrap, the
Murphy split, width floors and the trimmed number score, strict number types, stale p_late records, the split
leaderboard and the final scoring pass."""
import json
import math
import os

import numpy as np
import pytest

from tdcb.trials import numbers as tnum
from tdcb.trials import operations as tops
from tdcb.trials import packets as tpk
from tdcb.trials import round as tround
from tdcb.trials import score as tscore

from test_round import META, _build, _jsonl
from test_round_cards import CARDS, CTL, EFF, IDS, _fc


def _key(n, met):
    return [{"nct_id": f"NCT{i:08d}", "set": "post_cutoff", "met": m, "endpoint_kind": "other",
             "first_public_date": "2027-02-01"} for i, m in zip(range(n), met)]


def test_cluster_bootstrap_widens_intervals_for_sister_trials():
    rng = np.random.default_rng(1)
    # 40 groups of 5 sister trials: same outcome and same forecast within a group, so their errors move together
    met = [int(rng.uniform() < 0.6) for g in range(40) for _ in range(5)]
    met = [met[5 * (i // 5)] for i in range(200)]
    gp = rng.uniform(0.2, 0.9, 40)
    key = _key(200, met)
    preds = {k["nct_id"]: {"p_met": float(gp[i // 5])} for i, k in enumerate(key)}
    clusters = {k["nct_id"]: f"g{i // 5}" for i, k in enumerate(key)}
    plain = tscore.score(preds, key, n_boot=400, seed=0)
    clus = tscore.score(preds, key, n_boot=400, seed=0, clusters=clusters)
    w = lambda r: r["ci95"]["brier"][1] - r["ci95"]["brier"][0]  # noqa: E731
    assert clus["n_clusters"] == 40 and plain["n_clusters"] == 200
    assert w(clus) > 1.5 * w(plain)


def test_paired_skill_against_several_references():
    key = _key(6, [1, 1, 1, 0, 0, 0])
    good = {k["nct_id"]: {"p_met": 0.8 if k["met"] else 0.2} for k in key}
    flat = {k["nct_id"]: {"p_met": 0.5} for k in key}
    r = tscore.score(good, key, n_boot=50, refs={"base_rate": flat, "registry_model": good})
    p = r["probability"]
    assert math.isclose(p["bss_vs_base_rate"], 1 - 0.04 / 0.25)
    assert math.isclose(p["bss_vs_registry_model"], 0.0)
    assert r["ci95"]["brier_minus_registry_model"] == [0.0, 0.0]          # paired: same resample for both


def test_strict_scoring_raises_on_missing_forecast():
    key = _key(3, [1, 0, 1])
    preds = {key[0]["nct_id"]: {"p_met": 0.7}}
    assert tscore.score(preds, key)["validity_rate"] < 1
    try:
        tscore.score(preds, key, strict=True)
    except ValueError:
        pass
    else:
        raise AssertionError("strict scoring should raise")


def test_murphy_split_and_level_gap():
    p = np.array([0.1, 0.1, 0.9, 0.9])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    m = tscore.murphy(p, y)
    brier = float(np.mean((p - y) ** 2))
    assert math.isclose(brier, m["reliability"] - m["resolution"] + m["uncertainty"])
    assert m["resolution"] == 0.25 and math.isclose(m["level_gap"], 0.0)
    shifted = tscore.murphy(p - 0.05, y)
    assert math.isclose(shifted["level_gap"], -0.05)


def test_plain_mean_scores_and_per_question_floors():
    s = tnum.summarise([1.0] * 19 + [100.0])
    assert s["score"] == s["mean"] > 5                                  # the ranked score is the plain mean
    assert s["trimmed_mean"] == 1.0 and s["median"] == 1.0              # shown as robustness checks
    cards = {c["nct_id"]: c for c in CARDS}
    ref = {r["nct_id"]: r for r in _fc([0.5] * 4, CTL, EFF)}
    ref[IDS[2]]["effect"] = {"median": 3, "low80": 2.99, "high80": 3.01}  # near-degenerate reference range
    floors = tnum.width_floors(ref, cards)
    assert (IDS[2], "effect") in floors and (IDS[0], "effect") in floors
    # continuous floors follow each question's own size: double every number of a card, and its floor doubles
    big = {k: dict(v) for k, v in ref.items()}
    big[IDS[2]] = {"nct_id": IDS[2], **{w: {q: 2 * x for q, x in ref[IDS[2]][w].items()} for w in ("control", "effect")}}
    assert math.isclose(tnum.width_floors(big, cards)[(IDS[2], "effect")], 2 * floors[(IDS[2], "effect")])
    truth = {IDS[2]: {"control_value": None, "effect_value": 4}}
    entry = {IDS[2]: {"effect": {"median": 3.5, "low80": 2, "high80": 5}}}
    raw = tnum.number_scores(entry, ref, cards, truth)
    floored = tnum.number_scores(entry, ref, cards, truth, {(IDS[2], "effect"): 1.0})
    assert raw["effect"]["score"] > 50 * floored["effect"]["score"]


def test_no_implied_p_met_for_non_inferiority_without_margin():
    c = dict(CARDS[2], design="non-inferiority", margin=None)
    f = {"p_met": 0.6, "control": {"median": -2, "low80": -4, "high80": 0},
         "effect": {"median": 3, "low80": 1, "high80": 5}, "variability": 8}
    assert tnum.implied_p_met(f, c) is None
    assert tnum.implied_p_met(f, dict(c, margin=-2)) is not None


def test_validator_rejects_strings_and_booleans(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", CARDS),
                  deadline="2027-06-30")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    rows = _fc([0.5, 0.5, 0.5, 0.5])
    rows[0]["p_met"] = "0.5"
    rows[1]["p_met"] = True
    v = tround.validate(str(r), _jsonl(tmp_path / "f.jsonl", rows), str(meta))
    assert not v["ok"] and sum("JSON numbers" in e for e in v["errors"]) == 2


def test_p_late_void_when_estimated_date_is_stale():
    row = {"nct_id": "NCT1", "questions": ["p_late", "p_stopped", "p_posted"], "primary_completion_date": "2027-01-15"}
    base = {"status": "ACTIVE_NOT_RECRUITING", "primary_completion_date": "2027-01-15", "has_results": False}
    assert tops.resolve(row, base, "2027-08-31")["late"] == 0                         # no type: read as before
    stale = tops.resolve(row, dict(base, primary_completion_date_type="ESTIMATED"), "2027-08-31")
    assert stale["late"] is None and "estimated" in stale["late_void"]
    assert tops.resolve(row, dict(base, primary_completion_date_type="ACTUAL"), "2027-08-31")["late"] == 0
    moved = dict(base, primary_completion_date="2027-07-30", primary_completion_date_type="ESTIMATED")
    assert tops.resolve(row, moved, "2027-08-31")["late"] == 1                        # moved date: late
    recent = dict(base, primary_completion_date_type="ESTIMATED")
    assert tops.resolve(row, recent, "2027-03-01")["late"] == 0                       # not yet 90 days past


def test_card_text_flags_inferred_design_and_margin():
    c = dict(CARDS[2], design="non-inferiority", design_basis="inferred")
    text = "\n".join(tpk.card_section(c))
    assert "does not state the design" in text and "margin not stated in the record" in text
    assert "own primary hypothesis" in text
    m = "\n".join(tpk.card_section(dict(CARDS[0], measure_basis="assumed")))
    assert "card's reading, given in the notes, is assumed" in m
    assert "is assumed" not in "\n".join(tpk.card_section(CARDS[0]))


def _rat(rows):
    """Forecast rows with a rationale on each: the Models board's instructions ask one for every trial with p_met."""
    return [dict(o, rationale="The drug class worked in an earlier trial.") for o in rows]


CLOSED = dict(META, setting="closed", web_access=False, models=["model-x"], model_version="model-x-2026-09-01",
              provider="Example AI", harness="one call per trial, the round's instructions")


def _instructions(tmp_path):
    p = tmp_path / "forecast_instructions.md"
    p.write_text("# Task: forecast\n")
    return str(p)


def test_boards_tiers_first_upload_and_final_pass(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    sis = tmp_path / "sisters.json"
    sis.write_text(json.dumps({"groups": {}, "trial_group": {IDS[0]: "drugx", IDS[1]: "drugx"},
                               "trial_china_only": {IDS[0]: True, IDS[1]: False, IDS[2]: False, IDS[3]: False},
                               "trial_below_bar": {IDS[0]: False, IDS[1]: False, IDS[2]: True, IDS[3]: False}}))
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", CARDS),
                      deadline="2027-06-30", final_deadline="2027-12-31", sisters=str(sis),
                      instructions=_instructions(tmp_path))
    assert m["final_deadline"] == "2027-12-31" and m["n_sister_groups"] == 1 and "sisters_sha256" in m
    assert "given that a result is public" in m["scoring"] and "Two boards" in m["scoring"]
    assert (r / "forecast_instructions.md").exists() and len(m["instructions_sha256"]) == 64
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    closed = tmp_path / "closed.json"
    closed.write_text(json.dumps(dict(CLOSED, prompt_sha256=m["instructions_sha256"])))
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=[])))   # a baseline: no model
    tround.register(str(r), "ref-b0", _jsonl(tmp_path / "b0.jsonl", _fc([0.6] * 4)), str(base), "2026-10-31",
                    kind="reference")
    tround.register(str(r), "ref-b1", _jsonl(tmp_path / "b1.jsonl", _fc([0.7, 0.4, 0.6, 0.5])), str(base),
                    "2026-10-31", kind="reference")
    tround.register(str(r), "ref-model-x", _jsonl(tmp_path / "x.jsonl", _rat(_fc([0.8, 0.3, 0.7, 0.6]))), str(closed),
                    "2026-10-31", kind="reference")
    tround.register(str(r), "team-a", _jsonl(tmp_path / "a.jsonl", _fc([0.9, 0.2, 0.8, 0.7])), str(meta), "2026-12-01")
    tround.register(str(r), "team-a.first", _jsonl(tmp_path / "a1.jsonl", _fc([0.6, 0.6, 0.6, 0.6])), str(meta),
                    "2026-11-02", kind="first_upload", of="team-a")
    tround.register(str(r), "team-b", _jsonl(tmp_path / "bb.jsonl", _fc([0.5] * 4)), str(meta), "2026-12-02")
    for k, met, d in zip(key, (1, 0, 1, 1), ("2027-02-01", "2027-03-01", "2027-04-01", "2027-09-01")):
        k.update(set="post_cutoff", met=met, first_public_date=d)
    key[1]["vague_at_deadline"] = True                                  # only vague by the deadline: not met
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    first = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1, labels_as_of="2027-07-15")
    final = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1, scoring_pass="final")
    assert first["status"]["n_scored"] == 3 and final["status"]["n_scored"] == 4
    assert final["supplementary"] and all("tier" not in e for e in final["entries"] + final["references"])
    assert first["status"]["n_sister_groups_scored"] == 2 and first["status"]["n_vague_only_scored_not_met"] == 1
    assert first["boards"] == {"models": ["ref-model-x"], "open": ["team-a", "team-b"]}  # first uploads on no board
    by = {e["id"]: e for e in first["entries"] + first["references"]}
    assert "team-a.first" not in by and by["team-a"]["board"] == "open" and by["ref-model-x"]["board"] == "models"
    assert by["ref-b0"]["board"] == by["ref-b1"]["board"] == "baseline" and "tier" not in by["ref-b1"]
    assert all(by[i]["tier"] in (1, 2, 3) for i in ("team-a", "team-b", "ref-model-x"))
    assert set(first["tier_rule"]) == {"models", "open"} and first["tier_rule"]["open"]["n_entries_tested"] == 2
    a = by["team-a"]
    assert a["bss_vs_base_rate"] > 0 and a["bss_vs_registry_model"] is not None and a["resolution"] is not None
    fu = a["first_upload"]
    assert fu["id"] == "team-a.first" and fu["received"] == "2026-11-02" and fu["brier_last_minus_first"] < 0
    assert len(fu["ci95"]) == 2 and "first_upload" not in by["team-b"]
    assert fu["same_setup"] and fu["setup"]["models"] == META["models"]
    assert a["without_vague_only"]["n"] == 2 and a["without_vague_only"]["brier"] is not None
    assert a["without_vague_only"]["tier"] in (1, 2, 3) and len(a["without_vague_only"]["bss_vs_registry_model_ci95"]) == 2
    assert a["without_below_bar"]["n"] == 2 and a["without_below_bar"]["brier"] is not None      # IDS[2] left out
    assert a["without_below_bar"]["tier"] in (1, 2, 3) and first["status"]["n_below_bar_scored"] == 1
    ch = a["bss_vs_registry_model_by_china_only"]
    assert ch["china_only"]["n"] == 1 and ch["other"]["n"] == 2
    assert first["pairwise_exploratory"]["exploratory"] and len(first["pairwise_exploratory"]["pairs"]) == 3
    unranked = tround.leaderboard(str(b), str(r), n_boot=0)                         # default threshold: 100 trials
    assert not unranked["status"]["ranked"] and all("tier" not in e for e in unranked["entries"])


def test_models_board_needs_one_model_no_web_provenance_and_the_round_prompt(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", CARDS),
                      deadline="2027-06-30", instructions=_instructions(tmp_path))
    fc = _jsonl(tmp_path / "f.jsonl", _rat(_fc([0.5] * 4)))
    bare = _jsonl(tmp_path / "bare.jsonl", _fc([0.5] * 4))

    def check(**kw):
        p = tmp_path / "m.json"
        p.write_text(json.dumps(dict(dict(CLOSED, prompt_sha256=m["instructions_sha256"]), **kw)))
        return tround.validate(str(r), fc, str(p))
    ok = check()
    assert ok["ok"] and ok["board"] == "models"
    p = tmp_path / "m.json"                                                  # no rationale: refused on this board
    assert any("rationale" in e for e in tround.validate(str(r), bare, str(p))["errors"])
    p.write_text(json.dumps(META))                                           # the Open board: rationale optional
    assert tround.validate(str(r), bare, str(p))["ok"]
    assert not check(web_access=True)["ok"] and not check(models=["a", "b"])["ok"]
    assert not check(model_version="")["ok"] and not check(provider=None)["ok"]
    assert not check(model_version="latest")["ok"] and not check(model_version="model-x-latest")["ok"]
    assert not check(model_version="model-y")["ok"]                          # no date or number
    assert not check(team="x" * 100_000)["ok"] and not check(harness="\u202eevil")["ok"]
    assert check(team="A | B ![x](https://e.example/p.png)")["ok"]             # text is allowed; the page escapes it
    assert not check(code_url="javascript:alert(1)")["ok"]
    sealed = tmp_path / "sealed.json"
    sealed.write_text(json.dumps(dict(CLOSED, prompt_sha256="0" * 64)))
    sha = tmp_path / "f.sha256"
    sha.write_text(tround.validate(str(r), fc)["sha256"] + "  forecasts.jsonl\n")
    assert tround.check_sealed(str(sealed), str(sha))["ok"]                    # no round given: no prompt check
    assert not tround.check_sealed(str(sealed), str(sha), instructions_sha256=m["instructions_sha256"])["ok"]
    other = check(prompt_sha256="0" * 64)
    assert not other["ok"] and any("unchanged" in e for e in other["errors"])
    assert tround.validate(str(r), fc)["board"] is None                       # no metadata given
    p = tmp_path / "open.json"
    p.write_text(json.dumps(dict(META, models=["a", "b"])))                    # the Open board takes anything
    assert tround.validate(str(r), fc, str(p))["board"] == "open"
    p.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=[])))
    assert not tround.validate(str(r), fc, str(p))["ok"]                       # no model: only the organiser's baselines


def test_rationale_and_evidence_optional_checked_never_scored(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", CARDS),
                  deadline="2027-06-30")
    rows = _fc([0.5] * 4)
    rows[0].update(rationale="The class worked in the earlier phase 2.", evidence=["NCT01234567", "PMID 123"])
    v = tround.validate(str(r), _jsonl(tmp_path / "ok.jsonl", rows))
    assert v["ok"] and v["n_rationales"] == 1
    rows[1]["rationale"] = " ".join(["word"] * (tround.RATIONALE_WORDS + 1))
    rows[2]["evidence"] = ["x"] * (tround.EVIDENCE_MAX + 1)
    rows[3]["evidence"] = "NCT01234567"
    v = tround.validate(str(r), _jsonl(tmp_path / "bad.jsonl", rows))
    assert not v["ok"] and len(v["errors"]) == 3
    assert any("at most 150" in e for e in v["errors"]) and any("must be a list" in e for e in v["errors"])
    rows = _fc([0.5] * 4)
    rows[0]["rationale"] = "fine \u202e reversed"
    rows[1]["evidence"] = ["NCT01234567\x1b[31m"]
    rows[2]["rationale"] = "x" * (tround.RATIONALE_CHARS + 1)                    # one huge token
    rows[3]["evidence"] = ["javascript:alert(1)"]
    v = tround.validate(str(r), _jsonl(tmp_path / "bad2.jsonl", rows))
    assert not v["ok"] and len(v["errors"]) == 4
    rows = _fc([0.5] * 4)
    rows[0]["rationale"] = "hidden \U000e0049\U000e0047 text"                 # Unicode tag characters
    assert not tround.validate(str(r), _jsonl(tmp_path / "bad3.jsonl", rows))["ok"]


def test_finalize_labels_reads_the_rules_and_flags_disagreements(tmp_path):
    import subprocess
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(os.path.dirname(here), "pilot", "round1_rebuild", "finalize_labels.py")
    row = lambda n, **k: dict({"nct_id": n, "reported": "yes", "met": "yes", "first_public_date": "2027-02-01",  # noqa: E731
                               "clear_date": "2027-02-01", "confidence": "high", "control_value": None,
                               "effect_value": 0.7}, **k)
    A = [row("N1"), row("N2", met="endpoint_changed"), row("N3", reported="stopped_without_result",
         stop_reason="not about efficacy", met="not_reported"), row("N4", met="vague"), row("N5", effect_value=0.8)]
    B = [row("N1", first_public_date="2027-02-03", clear_date="2027-02-03"), row("N2", met="no"), row("N3", reported="stopped_without_result",
         stop_reason="not about efficacy", met="not_reported"), row("N4", met="vague"), row("N5")]
    pa, pb = _jsonl(tmp_path / "a.jsonl", A), _jsonl(tmp_path / "b.jsonl", B)
    out = tmp_path / "lab"
    r = subprocess.run([sys.executable, script, pa, pb, str(out), "--as-of", "2027-07-15", "--deadline", "2027-06-30",
                        "--manifest", str(_manifest(tmp_path))], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    labs = {json.loads(l)["nct_id"]: json.loads(l) for l in open(out / "labels.jsonl")}  # noqa: E741
    assert labs["N1"]["met"] == "yes" and labs["N2"]["met"] == "no"               # changed endpoint = not met
    assert labs["N3"]["reported"] == "stopped_without_result"                     # dropped
    assert labs["N4"]["met"] == "no"                                              # vague past the deadline
    dis = [json.loads(l) for l in open(out / "disagreements.jsonl")]  # noqa: E741
    assert [d["nct_id"] for d in dis] == ["N5"]                                   # numbers differ
    ag = json.load(open(out / "agreement.json"))
    assert ag["agreement_rate_where_a_result_was_found"] == 0.8 and ag["cohen_kappa_where_a_result_was_found"] is not None


def test_finalize_labels_reads_the_clear_date_against_each_deadline(tmp_path):
    import subprocess
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(os.path.dirname(here), "pilot", "round1_rebuild", "finalize_labels.py")
    # vague in May, clear (met) in July, numbers in the July release
    row = {"nct_id": "N1", "reported": "yes", "met": "yes", "first_public_date": "2027-05-10", "clear_date": "2027-07-10",
           "numbers_date": "2027-07-10", "confidence": "high", "control_value": 12.0, "effect_value": 0.7}
    clear = dict(row, nct_id="N2", first_public_date="2027-04-01", clear_date="2027-04-01", numbers_date="2027-09-01")
    pa = _jsonl(tmp_path / "a.jsonl", [row, clear])
    pb = _jsonl(tmp_path / "b.jsonl", [row, clear])

    def run(deadline, as_of):
        out = tmp_path / f"lab-{deadline}"
        r = subprocess.run([sys.executable, script, pa, pb, str(out), "--as-of", as_of, "--deadline", deadline,
                            "--manifest", str(_manifest(tmp_path))], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return {json.loads(l)["nct_id"]: json.loads(l) for l in open(out / "labels.jsonl")}  # noqa: E741
    june = run("2027-06-30", "2027-07-15")
    assert june["N1"]["met"] == "no" and june["N1"]["first_public_date"] == "2027-05-10"   # vague at the deadline
    assert june["N1"]["effect_value"] is None                                              # numbers came later
    assert june["N2"]["met"] == "yes" and june["N2"]["clear_date"] == "2027-04-01"
    assert june["N2"]["control_value"] is None                                             # paper after the deadline
    dec = run("2027-12-31", "2028-01-10")
    assert dec["N1"]["met"] == "yes" and dec["N1"]["effect_value"] == 0.7 and dec["N2"]["control_value"] == 12.0
    early = run("2027-06-30", "2027-06-01")                                                # before the deadline
    assert early["N1"]["reported"] == "no"                                                 # still open
    assert june["N1"]["vague_at_deadline"] and not june["N2"]["vague_at_deadline"]


def test_finalize_labels_sends_boundary_cases_and_bad_dates_to_the_organiser(tmp_path):
    import subprocess
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(os.path.dirname(here), "pilot", "round1_rebuild", "finalize_labels.py")
    r = lambda n, d, **k: dict({"nct_id": n, "reported": "yes", "met": "no", "first_public_date": d,  # noqa: E731
                                "clear_date": d, "confidence": "high"}, **k)
    A = [r("C1", "2026-12-05"), r("D1", "2027-06-28"), r("M1", "2027-03"), r("X1", "July 2027"), r("S1", "2027/03"),
         r("V1", "2027-03-01", met="vague", clear_date=None),
         r("T1", "2027-03-01", reported="stopped_without_result", stop_reason="business", met="not_reported"),
         r("F1", None, met="vague", clear_date=None),
         r("X2", "2027-03-01", clear_date="2027-02-01"), r("X3", "2027-03-01", met="yes", clear_date=None),
         r("OK", "2027-03-01")]
    B = [r("C1", "2026-12-12"), r("D1", "2027-07-03"), r("M1", "2027-03-01"), r("X1", "July 2027"), r("S1", "2027/03"),
         r("V1", "2027-03-01"),
         r("T1", "2027-03-01", reported="stopped_without_result", stop_reason="business", met="not_reported"),
         r("F1", None, met="vague", clear_date=None),
         r("X2", "2027-03-01", clear_date="2027-02-01"), r("X3", "2027-03-01", met="yes", clear_date=None),
         r("OK", "2027-03-04", clear_date="2027-03-04")]
    pa, pb = _jsonl(tmp_path / "a.jsonl", A), _jsonl(tmp_path / "b.jsonl", B)
    out = tmp_path / "lab"
    res = subprocess.run([sys.executable, script, pa, pb, str(out), "--as-of", "2027-07-15", "--deadline", "2027-06-30",
                          "--manifest", str(_manifest(tmp_path))], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    labs = {json.loads(l)["nct_id"] for l in open(out / "labels.jsonl")}  # noqa: E741
    dis = {json.loads(l)["nct_id"]: json.loads(l)["why"] for l in open(out / "disagreements.jsonl")}  # noqa: E741
    assert labs == {"M1", "OK"}                         # month-only dates read as the 1st; 3 days apart agree
    assert set(dis) == {"C1", "D1", "X1", "X2", "X3", "S1", "V1", "T1", "F1"}   # boundaries; bad dates; vague / no
    assert "stop_reason" in dis["T1"] and "no first_public_date" in dis["F1"]
    assert "YYYY-MM-DD" in dis["X1"] and "before" in dis["X2"] and "no clear_date" in dis["X3"]
    assert "YYYY-MM-DD" in dis["S1"]
    # the organiser's decisions pass the same rules: a vague one gets its flag, a malformed one stops the run
    dec = _jsonl(tmp_path / "dec.jsonl", [r("V1", "2027-03-01", met="vague", clear_date=None)])
    args = [sys.executable, script, pa, pb, str(out), "--as-of", "2027-07-15", "--deadline", "2027-06-30",
            "--manifest", str(_manifest(tmp_path))]
    assert subprocess.run(args + ["--decisions", dec], capture_output=True, text=True).returncode == 0
    v1 = [json.loads(l) for l in open(out / "labels.jsonl") if '"V1"' in l][0]  # noqa: E741
    assert v1["met"] == "no" and v1["vague_at_deadline"]
    bad = _jsonl(tmp_path / "bad.jsonl", [r("V1", "2027/03/01")])
    res = subprocess.run(args + ["--decisions", bad], capture_output=True, text=True)
    assert res.returncode != 0 and "organiser decisions fail" in res.stderr
    assert subprocess.run(args[:-2], capture_output=True, text=True).returncode != 0          # no manifest
    unknown = _jsonl(tmp_path / "unk.jsonl", [r("NCT_NOT_LISTED", "2027-03-01")])
    res = subprocess.run(args + ["--decisions", unknown], capture_output=True, text=True)
    assert res.returncode != 0 and "not a trial" in res.stderr
    wrong = [x if x != "2027-06-30" else "2027-06-15" for x in args]                      # not a pass deadline
    assert subprocess.run(wrong, capture_output=True, text=True).returncode != 0


def _manifest(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"closes": "2026-12-10", "deadline": "2027-06-30", "final_deadline": "2027-12-31"}))
    return p


def test_tiers_against_the_registry_model_each_entry_on_its_own():
    rng = np.random.default_rng(0)
    n = 400
    met = (rng.uniform(size=n) < 0.7).astype(int)
    key = _key(n, met.tolist())
    flat = {k["nct_id"]: {"p_met": 0.5} for k in key}                              # the registry model, here
    good = {k["nct_id"]: {"p_met": 0.85 if k["met"] else 0.35} for k in key}
    noise = rng.normal(0, 0.08, n)                                                  # as good on average, noisily
    twin = {k["nct_id"]: {"p_met": float(min(0.99, max(0.01, good[k["nct_id"]]["p_met"] + e)))}
            for k, e in zip(key, noise)}
    bad = {k["nct_id"]: {"p_met": 0.35 if k["met"] else 0.85} for k in key}
    nudged = {k: {"p_met": v["p_met"] + 0.002} for k, v in flat.items()}            # a negligible shift
    t = tround.tiers({"good": good, "twin": twin, "bad": bad, "nudged": nudged, "same": flat}, key, None, flat,
                     n_boot=500)
    tier = {e: r["tier"] for e, r in t["by_entry"].items()}
    assert tier == {"good": 1, "twin": 1, "bad": 3, "nudged": 2, "same": 2}
    assert t["n_entries_tested"] == 5 and t["by_entry"]["same"]["brier_minus_registry_model"] == 0
    assert tround.TIER_NAMES[2] == "no clear difference from the registry model"
    # the smaller one-sided p-value is doubled: a direction is never chosen after seeing the data
    r = t["by_entry"]["good"]
    assert r["p"] == min(1.0, 2 * min(r["p_better"], r["p_worse"])) and r["gain_needed_for_tier_1"] > 0.005
    pb, pw = tround._two_way(-0.02, 0.005, 0.005)
    assert math.isclose(pb, 0.5 * math.erfc(3 / math.sqrt(2))) and pw > 0.999
    # each entry is tested on its own: thirty free copies of the registry model change nothing for the others
    copies = {f"copy{i}": flat for i in range(30)}
    t2 = tround.tiers(dict(copies, good=good, twin=twin), key, None, flat, n_boot=500)
    assert t2["by_entry"]["good"]["p"] == t["by_entry"]["good"]["p"] and t2["by_entry"]["twin"]["tier"] == 1
    assert all(t2["by_entry"][c]["tier"] == 2 for c in copies)
    # sister groups: errors that move together give a wider spread than trial by trial
    g = {k["nct_id"]: f"g{i // 20}" for i, k in enumerate(key)}
    tg = tround.tiers({"twin": twin}, key, g, good, n_boot=500)["by_entry"]["twin"]
    assert tg["sd"] > 0
    # exploratory pairwise comparisons, never ranked
    pw = tround.pairwise({"good": good, "twin": twin, "nudged": nudged}, key, None, n_boot=500)
    pairs = {(p["a"], p["b"]): p for p in pw["pairs"]}
    assert pw["exploratory"] and pairs[("good", "nudged")]["clearly_better"] == "good"
    assert pairs[("good", "twin")]["clearly_better"] is None


def test_adds_to_the_registry_model_out_of_fold():
    rng = np.random.default_rng(3)
    n = 400
    x = rng.normal(0, 1, n)                                           # what the registry knows
    z = rng.normal(0, 1, n)                                           # what only the entry knows
    met = (rng.uniform(size=n) < 1 / (1 + np.exp(-(0.8 + x + 1.2 * z)))).astype(int)
    key = _key(n, met.tolist())
    p = lambda v: {k["nct_id"]: {"p_met": float(1 / (1 + np.exp(-vi)))} for k, vi in zip(key, v)}  # noqa: E731
    b1 = p(0.8 + x)
    informed = p(0.8 + x + 1.2 * z)
    clusters = {k["nct_id"]: f"g{i // 2}" for i, k in enumerate(key)}
    yes = tround.adds_to(informed, b1, key, clusters, n_boot=60)
    assert yes["adds"] and yes["brier_gain"] > 0.02 and yes["weight_entry"] > 0.5 and yes["folds"] == 10
    assert len(yes["gain_by_split"]) == 5 and yes["exploratory"] and yes["n_boot"] == 60
    assert math.isclose(yes["ci95"][0], yes["brier_gain"] - 1.959964 * yes["sd"]) and len(yes["ci95_percentile"]) == 2
    # turned upside down it is just as informative, but it does not "add": the weight must be positive
    flipped = {k: {"p_met": 1 - v["p_met"]} for k, v in informed.items()}
    upside = tround.adds_to(flipped, b1, key, clusters, n_boot=60)
    assert upside["brier_gain_any_sign"] > 0.02 and upside["weight_entry"] < 0 and not upside["adds"]
    assert upside["brier_gain"] is None and upside["ci95"] is None                     # its gain is not shown
    # recalibrating the registry model alone gains nothing: an entry that only rescales it adds nothing
    rescaled = p(2.0 * (0.8 + x))
    no = tround.adds_to(rescaled, b1, key, clusters, n_boot=60)
    assert not no["adds"] and abs(no["brier_gain_any_sign"]) < 0.01
    noise = p(rng.normal(0, 1, n))
    assert not tround.adds_to(noise, b1, key, clusters, n_boot=60)["adds"]
    assert tround.adds_to(informed, b1, key[:15], clusters, n_boot=20) is None        # too few trials


def test_shipped_templates_pass_the_checker(tmp_path):
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = os.path.join(os.path.dirname(here), "pilot", "round1_rebuild", "template")
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", CARDS),
                      deadline="2027-06-30", instructions=_instructions(tmp_path))
    fc = _jsonl(tmp_path / "f.jsonl", _rat(_fc([0.5] * 4)))
    v = tround.validate(str(r), fc, os.path.join(tpl, "meta.example.json"))
    assert v["ok"], v["errors"]
    mb = json.load(open(os.path.join(tpl, "meta.models_board.example.json")))
    mb["prompt_sha256"] = m["instructions_sha256"]                    # as build_space fills it in
    p = tmp_path / "mb.json"
    p.write_text(json.dumps(mb))
    v = tround.validate(str(r), fc, str(p))
    assert v["ok"], v["errors"]


def _make_baselines():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "make_baselines", os.path.join(os.path.dirname(here), "pilot", "round1_rebuild", "make_baselines.py"))
    mb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mb)
    return mb


def test_baseline_labels_are_read_at_each_window_end_on_fully_followed_trials():
    import datetime as dt
    mb = _make_baselines()
    check = dt.date(2026, 10, 25)
    base = {"primary_completion_date": "2026-06-15", "lag_months": 1.0, "features": {k: 0.0 for k in mb.NAMES}}
    vague = dict(base, nct_id="V", label="vague", met=0, clear_lag_months=None)
    early = dict(base, nct_id="E", label="yes", met=1, clear_lag_months=1.0)
    late = dict(base, nct_id="L", label="yes", met=1, clear_lag_months=3.5)     # vague first, clear 3.5 months on
    assert mb.label_at(vague, 3.0, check) == 0             # followed to mid-September: still vague there, not met
    assert mb.label_at(late, 3.0, check) == 0              # clear only after that window's end (rule 6)
    assert mb.label_at(late, 4.0, check) == 1
    for t in (vague, early, late):                         # mid-December is after the check: unknown for all,
        assert mb.label_at(t, 6.0, check) is None          # the clear ones included (no one-sided censoring)
    use, n_out = mb.counts_for([vague, early, late], 0.0, 6.0, check)
    assert use == [] and n_out == 3
    m = mb.window_rate(0.0, 4.0, [vague, early, late, dict(early, lag_months=4.5)], check, 0.6)
    assert m["n"] == 3 and m["raw"] == 2 / 3                # the trial first public after the window's end is out
    assert abs(m["rate"] - (2 + 20 * 0.6) / 23) < 1e-12


def test_baseline_refit_checks_the_audit_against_the_table():
    mb = _make_baselines()
    table = [{"nct_id": "A", "label": "yes", "first_public": "2026-05-01", "clear_date": "2026-05-01"},
             {"nct_id": "K", "label": "vague", "first_public": "2026-06-01", "clear_date": None}]
    corr = {"A": {"action": "relabel", "met": "yes", "first_public": "2026-05-01", "clear_date": "2026-05-01"},
            "K": {"action": "keep", "met": "vague", "first_public": "2026-06-01"},
            "D": {"action": "drop", "met": "vague", "first_public": "2026-06-01"}}
    assert mb.check_corrections(table, corr) == 2
    with pytest.raises(SystemExit, match="D: dropped"):
        mb.check_corrections(table + [{"nct_id": "D", "label": "vague", "first_public": "2026-06-01"}], corr)
    with pytest.raises(SystemExit, match="clear_date"):
        mb.check_corrections([dict(table[0], clear_date="2026-07-01"), table[1]], corr)


def test_without_below_bar_says_when_it_cannot_be_computed(tmp_path):
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    sis = tmp_path / "sisters.json"
    sis.write_text(json.dumps({"groups": {}, "trial_group": {}, "trial_below_bar": {i: i != IDS[0] for i in IDS}}))
    tround.export(str(b), str(r), "t-r1", closes="2026-12-15", cards=_jsonl(tmp_path / "c.jsonl", CARDS),
                  deadline="2027-06-30", sisters=str(sis), instructions=_instructions(tmp_path))
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=[])))
    tround.register(str(r), "ref-b0", _jsonl(tmp_path / "b0.jsonl", _fc([0.6] * 4)), str(base), "2026-10-31",
                    kind="reference")
    tround.register(str(r), "ref-b1", _jsonl(tmp_path / "b1.jsonl", _fc([0.7, 0.4, 0.6, 0.5])), str(base),
                    "2026-10-31", kind="reference")
    tround.register(str(r), "team-a", _jsonl(tmp_path / "a.jsonl", _fc([0.9, 0.2, 0.8, 0.7])), str(meta), "2026-12-01")
    for k, met, d in zip(key, (1, 0, 1, 1), ("2027-02-01", "2027-03-01", "2027-04-01", "2027-05-01")):
        k.update(set="post_cutoff", met=met, first_public_date=d)
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    lb = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1, labels_as_of="2027-07-15")
    a = {e["id"]: e for e in lb["entries"]}["team-a"]
    assert a["without_below_bar"]["n"] == 1 and "not_computable" in a["without_below_bar"]
    assert "tier" not in a["without_below_bar"] and lb["status"]["n_below_bar_scored"] == 3
