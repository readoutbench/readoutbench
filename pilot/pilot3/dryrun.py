"""Pilot 3, part B: describe the dry-run answers on the Round 1 sample.

usage: python3 -I dryrun.py <dry-run dir> <out.json>
Reads out_<model>/*.jsonl, the sample's questions.json and its staged round (cards, operations rows), and reports:
what each model answered by trial type, how far the models agree, the consistency check, and the main risks named.
"""
import json
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import numbers as tnum  # noqa: E402
from tdcb.trials import operations as tops  # noqa: E402
from tdcb.trials import round as tround  # noqa: E402

D, out = sys.argv[1], sys.argv[2]
M = ("opus", "sonnet", "haiku")
F = {m: {} for m in M}
for m in M:
    for fn in sorted(os.listdir(os.path.join(D, "out_" + m))):
        F[m].update(tround.load_forecasts(os.path.join(D, "out_" + m, fn)))
qs = {q["nct_id"]: q for q in json.load(open(os.path.join(D, "questions.json")))}
cards = tnum.load_cards(os.path.join(D, "stage", "round", "cards.jsonl"))
ops = tops.load_rows(os.path.join(D, "stage", "round", "operations.jsonl"))
ids = sorted(qs)
R = {"n_trials": len(ids), "groups": dict(Counter(q["questions"] for q in qs.values()))}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else None


def phase(n):
    return "phase 3" if "PHASE3" in qs[n]["phase"] else "phase 2"


# p_met by group
pm = {}
for label, sel in (("main, phase 3", lambda n: qs[n]["questions"] == "main" and phase(n) == "phase 3"),
                   ("main, phase 2", lambda n: qs[n]["questions"] == "main" and phase(n) == "phase 2"),
                   ("equivalence", lambda n: qs[n]["questions"] == "equivalence")):
    sub = [n for n in ids if sel(n)]
    pm[label] = {"n": len(sub), **{m: mean([tnum.num(F[m][n].get("p_met")) for n in sub]) for m in M}}
R["p_met_mean"] = pm
P = {m: np.array([F[m][n]["p_met"] for n in ids if tnum.has_p_met(cards[n])]) for m in M}
logit = lambda p: np.log(np.clip(p, .01, .99) / (1 - np.clip(p, .01, .99)))  # noqa: E731
R["p_met_agreement"] = {f"{a}-{b}": {"corr_logit": float(np.corrcoef(logit(P[a]), logit(P[b]))[0, 1]),
                                     "mean_abs_diff": float(np.mean(np.abs(P[a] - P[b]))),
                                     "sd_diff": float(np.std(P[a] - P[b]))}
                        for i, a in enumerate(M) for b in M[i + 1:]}
R["p_met_extreme_share"] = {m: float(np.mean((P[m] < 0.1) | (P[m] > 0.9))) for m in M}

# operations by group
og = {}
for q in tops.QUESTIONS:
    og[q] = {}
    for g in ("main", "equivalence", "operations only"):
        sub = [n for n in ids if qs[n]["questions"] == g and q in ops[n]["questions"]]
        og[q][g] = {"n": len(sub), **{m: mean([tnum.num(F[m][n].get(q)) for n in sub]) for m in M}}
    allq = [n for n in ids if q in ops[n]["questions"]]
    A = {m: np.array([F[m][n][q] for n in allq]) for m in M}
    og[q]["agreement"] = {f"{a}-{b}": {"corr": float(np.corrcoef(A[a], A[b])[0, 1]),
                                       "mean_abs_diff": float(np.mean(np.abs(A[a] - A[b])))}
                          for i, a in enumerate(M) for b in M[i + 1:]}
    og[q]["share_at_or_above_0.5"] = {m: float(np.mean(A[m] >= 0.5)) for m in M}
R["operations_mean"] = og

# p_late against status and date
late = [n for n in ids if "p_late" in ops[n]["questions"]]
by_status = {}
for st in sorted({ops[n]["status"] for n in late}):
    sub = [n for n in late if ops[n]["status"] == st]
    by_status[st] = {"n": len(sub), **{m: mean([F[m][n]["p_late"] for n in sub]) for m in M}}
R["p_late_by_status"] = by_status
by_month = {}
for lo, hi, lab in (("2026-10-27", "2026-12-31", "Nov-Dec 2026"), ("2027-01-01", "2027-03-31", "Jan-Mar 2027")):
    sub = [n for n in late if lo <= str(tops.parse_date(ops[n]["primary_completion_date"])) <= hi]
    by_month[lab] = {"n": len(sub), **{m: mean([F[m][n]["p_late"] for n in sub]) for m in M}}
R["p_late_by_registered_date"] = by_month
post = {}
for lo, hi, lab in (("2026-07-01", "2026-09-30", "Jul-Sep 2026"), ("2026-10-01", "2026-12-31", "Oct-Dec 2026"),
                    ("2027-01-01", "2027-03-31", "Jan-Mar 2027")):
    sub = [n for n in ids if lo <= str(tops.parse_date(ops[n]["primary_completion_date"])) <= hi]
    post[lab] = {"n": len(sub), **{m: mean([F[m][n]["p_posted"] for n in sub]) for m in M}}
R["p_posted_by_registered_date"] = post

# numbers, consistency, risks
R["consistency"] = {m: tnum.consistency(F[m], cards, ids) for m in M}
R["main_risk"] = {m: dict(Counter(F[m][n].get("main_risk") for n in ids if tnum.has_p_met(cards[n])).most_common())
                  for m in M}
R["stray_answers"] = {m: {"p_met_on_operations_only": sum(F[m][n].get("p_met") is not None for n in ids
                                                          if not tnum.has_p_met(cards[n])),
                          "p_late_not_asked": sum(F[m][n].get("p_late") is not None for n in ids
                                                  if "p_late" not in ops[n]["questions"]),
                          "numbers_not_asked": sum(F[m][n].get("control") is not None for n in ids
                                                   if not tnum.is_number_question(cards[n]))}
                      for m in M}
nq = [n for n in ids if tnum.is_number_question(cards[n])]
wid = {}
for m in M:
    w = []
    for n in nq:
        for which in ("control", "effect"):
            r, ro = tnum.parse_range(F[m][n].get(which)), tnum.parse_range(F["opus"][n].get(which))
            log = tnum.log_scale(cards[n], which)
            if r and ro and not (log and min(r[1], ro[1]) <= 0) and tnum.width(ro, log) > 0:
                w.append(tnum.width(r, log) / tnum.width(ro, log))
    wid[m] = float(np.median(w)) if w else None
R["number_range_width_vs_opus_median"] = wid
json.dump(R, open(out, "w"), indent=1)
print(json.dumps(R, indent=1))
