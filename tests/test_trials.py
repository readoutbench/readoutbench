import json
import os

import numpy as np

from tdcb import cli
from tdcb.trials import baselines as tb
from tdcb.trials import labels as tl
from tdcb.trials import packets as tp
from tdcb.trials import records as tr
from tdcb.trials import score as ts


def _rec(i, primary="Overall survival (OS)", status="ACTIVE_NOT_RECRUITING", placebo=False):
    return {"nct_id": f"NCT0{9000000 + i}", "title": f"A Phase 3 Study of Drug{i} Versus Standard Care in First-line Cancer",
            "brief_title": f"Drug{i} study", "acronym": None, "status": status, "phase": ["PHASE3"],
            "study_type": "INTERVENTIONAL", "conditions": ["Lung Cancer"],
            "interventions": [f"Drug{i}", "Placebo" if placebo else "Docetaxel"],
            "sponsor": "Pfizer" if i % 2 else "Small Biotech Co", "collaborators": None, "enrollment": 300 + 10 * i,
            "start_date": "2023-01-01", "primary_completion_date": "2026-05-01", "completion_date": "2028-01-01",
            "brief_summary": "Randomized comparison.", "detailed_description": None,
            "eligibility_criteria": "Inclusion: adults.", "minimum_age": "18 Years", "maximum_age": None, "sex": "ALL",
            "primary_outcomes": [{"measure": primary, "time_frame": "5 years", "description": None}],
            "secondary_outcomes": [{"measure": "Safety", "time_frame": "5 years", "description": None}],
            "url": f"https://clinicaltrials.gov/study/NCT0{9000000 + i}", "has_results": True,
            "n_locations": 40, "countries": ["China"] if i % 3 == 0 else ["Germany", "Japan", "United States"],
            "fetched_at": "2026-10-21T00:00:00Z"}


def test_from_api_v2_converts_a_study():
    study = {"hasResults": False, "protocolSection": {
        "identificationModule": {"nctId": "NCT01234567", "briefTitle": "Short", "officialTitle": "Long title", "acronym": "ABC-1"},
        "statusModule": {"overallStatus": "COMPLETED", "startDateStruct": {"date": "2022-01"},
                         "primaryCompletionDateStruct": {"date": "2026-03-01"}, "completionDateStruct": {"date": "2027"}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Sponsor"}, "collaborators": [{"name": "Group"}]},
        "designModule": {"phases": ["PHASE3"], "studyType": "INTERVENTIONAL", "enrollmentInfo": {"count": 500}},
        "conditionsModule": {"conditions": ["Breast Cancer"]},
        "armsInterventionsModule": {"interventions": [{"name": "Drug A"}, {"name": "Drug B"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "PFS", "timeFrame": "3 years"}]},
        "eligibilityModule": {"eligibilityCriteria": "Adults", "sex": "FEMALE", "minimumAge": "18 Years"},
        "contactsLocationsModule": {"locations": [{"country": "France"}, {"country": "France"}, {"country": "Spain"}]}}}
    rec = tr.from_api_v2(study, fetched_at="2026-10-21T00:00:00Z")
    assert rec["nct_id"] == "NCT01234567" and rec["acronym"] == "ABC-1" and rec["enrollment"] == 500
    assert rec["interventions"] == ["Drug A", "Drug B"] and rec["countries"] == ["France", "Spain"]
    assert rec["n_locations"] == 3 and rec["primary_outcomes"][0]["time_frame"] == "3 years"
    assert set(tr.FIELDS) == set(rec)


def test_packet_hides_status_and_results_and_types_the_endpoint():
    rec = _rec(1, status="TERMINATED")
    text = tp.render(rec)
    assert "TERMINATED" not in text and "clinicaltrials.gov/study" not in text and "has_results" not in text
    assert "time-to-event" in text and "Overall survival" in text
    assert tp.endpoint_kind(_rec(2, primary="Objective response rate (ORR) by BICR")) == "other"
    assert tp.endpoint_kind(_rec(3, primary="Pathological complete response (pCR)")) == "other"
    assert tp.endpoint_kind(_rec(4, primary="Progression-free survival per RECIST 1.1")) == "time_to_event"
    assert tp.leak_problems("The trial met its primary endpoint.") and not tp.leak_problems(text)


def test_labels_sort_into_sets_and_overrides_apply(tmp_path):
    rows = [
        {"nct_id": "NCT1", "reported": "yes", "first_public_date": "2026-08-02", "met": "yes", "hr": 0.7,
         "hr_ci_low": 0.6, "hr_ci_high": 0.8, "confidence": "high"},
        {"nct_id": "NCT2", "reported": "yes", "first_public_date": "2026-03-10", "met": "no", "hr": 9.0,
         "confidence": "medium"},
        {"nct_id": "NCT3", "reported": "no", "met": "not_reported"},
        {"nct_id": "NCT4", "reported": "yes", "first_public_date": "2026-09-01", "met": "yes", "confidence": "low"},
        {"nct_id": "NCT5", "reported": "yes", "first_public_date": "2026-09-01", "met": "yes", "hr": 0.7,
         "hr_ci_low": 0.75, "hr_ci_high": 0.9, "confidence": "high"},
    ]
    p1 = tmp_path / "a.jsonl"
    p1.write_text("\n".join(json.dumps(r) for r in rows))
    p2 = tmp_path / "override.jsonl"
    p2.write_text(json.dumps({"nct_id": "NCT4", "confidence": "high"}))
    lab = tl.load_labels([str(p1), str(p2)])
    sets = {k: tl.assign(v, "2026-06-30")[0] for k, v in lab.items()}
    assert sets == {"NCT1": "post_cutoff", "NCT2": "pre_cutoff", "NCT3": "open", "NCT4": "post_cutoff",
                    "NCT5": "post_cutoff"}
    assert lab["NCT2"]["hr"] is None                      # implausible HR dropped
    assert lab["NCT5"]["hr"] == 0.7 and lab["NCT5"]["hr_ci_low"] is None   # inconsistent CI dropped
    assert lab["NCT4"]["met"] == "yes"                    # override kept the other fields


def test_trial_scores_and_cutoff_selection():
    key = [{"nct_id": f"NCT{i}", "set": "post_cutoff" if i < 6 else "pre_cutoff", "met": i % 2,
            "first_public_date": f"2026-0{1 + i % 9}-15", "endpoint_kind": "time_to_event", "hr": 0.7} for i in range(10)]
    perfect = {k["nct_id"]: {"p_met": float(k["met"]), "hr_median": 0.7, "hr_low80": 0.6, "hr_high80": 0.8} for k in key}
    r = ts.score(perfect, key)
    assert r["n_questions"] == 6 and r["probability"]["brier"] == 0 and r["probability"]["auroc"] == 1
    assert r["hazard_ratio"]["coverage80"] == 1 and r["hazard_ratio"]["median_abs_log_error"] == 0
    # a forecaster with a later knowledge cutoff is scored only on results after it
    late = ts.score(perfect, key, cutoff="2026-06-30")
    assert late["n_questions"] == sum(k["first_public_date"] > "2026-06-30" for k in key)
    half = {k: {"p_met": 0.5} for k in perfect}
    rr = ts.score(perfect, key, ref=half)
    assert np.isclose(rr["probability"]["bss_vs_ref"], 1.0)
    missing = ts.score({}, key)
    assert missing["validity_rate"] == 0 and "hazard_ratio" not in missing


def test_trials_build_baselines_run_and_score(tmp_path):
    reg = tmp_path / "registry"
    reg.mkdir()
    labs = []
    rng = np.random.default_rng(0)
    for i in range(40):
        rec = _rec(i, placebo=i % 4 == 0)
        (reg / f"{rec['nct_id']}.json").write_text(json.dumps(rec))
        if i < 30:
            date = "2026-03-01" if i < 25 else "2026-08-15"
            labs.append({"nct_id": rec["nct_id"], "reported": "yes", "first_public_date": date,
                         "met": "yes" if rng.random() < 0.55 else "no", "hr": round(float(rng.uniform(0.5, 1.0)), 2),
                         "confidence": "high"})
        else:
            labs.append({"nct_id": rec["nct_id"], "reported": "no", "met": "not_reported"})
    lp = tmp_path / "labels.jsonl"
    lp.write_text("\n".join(json.dumps(x) for x in labs))
    out = tmp_path / "build"
    cli.main(["trials", "build", "--registry", str(reg), "--labels", str(lp), "--out", str(out)])
    man = json.load(open(out / "manifest_C.json"))
    assert man["counts"] == {"post_cutoff": 5, "pre_cutoff": 25, "open": 10}
    assert not man["leak_phrases"]
    cli.main(["trials", "baselines", "--build", str(out)])
    b1 = [json.loads(x) for x in open(out / "predictions" / "c_b1.jsonl")]
    assert len(b1) == 40 and len({round(x["p_met"], 4) for x in b1}) > 1
    key = json.load(open(out / "private" / "key_C.json"))
    recs = {json.load(open(f))["case_id"]: json.load(open(f))["record"]
            for f in (out / "packets" / "C").glob("*/*.json")}
    pre = {k["nct_id"] for k in key if k["set"] == "pre_cutoff"}
    _, oof, info = tb.fit_and_predict(recs, key, k_folds=5)
    _, ins, _ = tb.fit_and_predict(recs, key, k_folds=0)
    oof, ins = {x["case_id"]: x["p_met"] for x in oof}, {x["case_id"]: x["p_met"] for x in ins}
    assert "out_of_fold" in info and any(oof[i] != ins[i] for i in pre)      # training trials: out of fold
    assert all(oof[i] == ins[i] for i in recs if i not in pre)               # others: the full model
    pred = tmp_path / "mock_c.jsonl"
    cli.main(["run", "--build", str(out), "--track", "C", "--split", "post_cutoff", "--provider", "mock",
              "--out", str(pred)])
    rep = tmp_path / "rep.json"
    cli.main(["trials", "score", "--build", str(out), "--pred", str(pred), "--ref",
              str(out / "predictions" / "c_b0.jsonl"), "--n-boot", "50", "--out", str(rep)])
    r = json.load(open(rep))
    assert r["n_questions"] == 5 and r["validity_rate"] == 1 and "bss_vs_ref" in r["probability"]
    assert os.path.exists(out / "private" / "key_C.json")


def test_build_leaves_out_trials_on_the_exclusion_list(tmp_path):
    reg = tmp_path / "registry"
    reg.mkdir()
    labs = []
    for i in range(4):
        rec = _rec(i)
        (reg / f"{rec['nct_id']}.json").write_text(json.dumps(rec))
        labs.append({"nct_id": rec["nct_id"], "reported": "no", "met": "not_reported"})
    lp = tmp_path / "labels.jsonl"
    lp.write_text("\n".join(json.dumps(x) for x in labs))
    ex = tmp_path / "exclude.txt"
    ex.write_text("# comment line\nNCT09000001 not a cancer trial (warts)\n")
    out = tmp_path / "build"
    cli.main(["trials", "build", "--registry", str(reg), "--labels", str(lp), "--out", str(out),
              "--exclude", str(ex)])
    man = json.load(open(out / "manifest_C.json"))
    assert man["counts"]["open"] == 3
    assert man["excluded"] == [{"nct_id": "NCT09000001", "reason": "out of scope: not a cancer trial (warts)"}]
    assert not (out / "packets" / "C" / "open" / "NCT09000001.md").exists()
