"""Pilot 2: a registry-field baseline (B1) fitted on trials whose result was public before 1 July 2026.

usage: python3 -I b1.py <results_status.jsonl> <merged.jsonl> <predict set.json> <out b1.jsonl> --records <records.jsonl> [...]
Features from the registry record only: phase 3, placebo or sham control, log enrolment, cancer, large company,
China only, time-to-event endpoint. L2-regularised logistic regression, trained on the history set (web-checked,
met or not met, first public statement before the cutoff). Prints the training size, base rate and coefficients.
"""
import argparse
import json
import math
import os
import re
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "round2")))
from tdcb.trials.packets import endpoint_kind  # noqa: E402
from areas import area  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("status")
ap.add_argument("merged")
ap.add_argument("predict")
ap.add_argument("out")
ap.add_argument("--records", nargs="+", required=True)
a = ap.parse_args()
status = [json.loads(l) for l in open(a.status)]
merged = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.merged)}
recs = {}
for p in a.records:
    for l in open(p):
        if l.strip():
            r = json.loads(l)
            recs[r["nct_id"]] = r
BIG = re.compile(r"pfizer|novartis|hoffmann|roche|genentech|merck sharp|astrazeneca|janssen|johnson|sanofi|glaxo|gsk|"
                 r"abbvie|bristol|lilly|amgen|novo nordisk|bayer|boehringer|takeda|gilead|regeneron|vertex|daiichi|"
                 r"astellas|eisai|otsuka|biogen|moderna|alexion", re.I)
NAMES = ["phase3", "placebo", "log_n", "cancer", "big_pharma", "china_only", "tte"]


def feats(n):
    r = recs[n]
    m = merged.get(n)
    text = " ".join([r.get("title") or ""] + list(r.get("interventions") or []))
    placebo = (m["reader"].get("comparison") == "placebo or sham") if m else bool(re.search(r"placebo|sham", text, re.I))
    cancer = (m["area"] == "cancer") if m else area({"conditions": r.get("conditions") or [], "title": r.get("title") or "",
                                                       "interventions": r.get("interventions") or []}) == "cancer"
    countries = r.get("countries") or []
    return [float("PHASE3" in (r.get("phase") or [])), float(placebo), math.log(max(1, r.get("enrollment") or 1)),
            float(cancer), float(bool(BIG.search(r.get("sponsor") or ""))), float(countries == ["China"]),
            float(endpoint_kind(r) == "time_to_event")]


train = [r for r in status if r["status"] == "history" and r["web"] and r["met"] in ("yes", "no") and r["nct_id"] in recs]
X = np.array([feats(r["nct_id"]) for r in train])
y = np.array([r["met"] == "yes" for r in train], dtype=int)
mu, sd = X.mean(0), X.std(0) + 1e-9
clf = LogisticRegression(C=1.0, max_iter=1000).fit((X - mu) / sd, y)
print(f"trained on {len(train)} trials, base rate {y.mean():.2f}")
print("coefficients (per SD):", {k: round(float(v), 2) for k, v in zip(NAMES, clf.coef_[0])})
pred = json.load(open(a.predict))
with open(a.out, "w") as fh:
    for r in pred:
        p = float(clf.predict_proba((np.array([feats(r["nct_id"])]) - mu) / sd)[0, 1])
        fh.write(json.dumps({"case_id": r["nct_id"], "p_met": round(p, 4), "b0": round(float(y.mean()), 4)}) + "\n")
print("wrote", len(pred), "predictions")
