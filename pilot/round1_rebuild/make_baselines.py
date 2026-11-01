"""Round 1 (rebuilt): the two baseline reference entries, B0 (base rate) and B1 (registry model).

usage: python3 -I make_baselines.py <round dir> <out dir> (--train-table baselines_training.jsonl
                                    --round-features baselines_round_features.jsonl |
                                    --status results_status.jsonl --merged merged_all.jsonl --records <records ...>)
                                    --corrections baselines_label_audit.jsonl [--pin <evidence files ...>]
                                    [--check-date 2026-10-25] [--before 2026-10-27]
Training trials: earlier company trials (all completed in 2026) whose primary result was public before the round
opens (`--before`), web-checked on `--check-date`. Each keeps its label (met, not met, vague, changed endpoint), the
date of its first public statement and the date its result became clear (`clear_date`). Stops with no result are left
out (the check did not record their reason, which decides whether the round drops them or counts them as not met).
Built from the Round 2 results check with the training-label audit's corrections (`--corrections`: relabels, drops and
the organiser's decisions), or read back from the shipped training table (`--train-table`), which this script also
writes, so anyone can refit without the Round 2 files; with the table, `--corrections` checks that the table carries
every correction. 93 of them are Pilot 2's trials; they are earlier than the round, so they may train its baselines,
but scores of these baselines on Pilot 2 are not out-of-sample. Only training trials whose first result came at a time
after their primary completion that the round can score are kept (from the earliest window start to the latest window
end over the round's trials, about -3.7 to +12 months).

Labels as the round reads them, window by window. A round trial is scored when its first result comes after the close
and by the deadline, so, counted from its own primary completion, within (close - PCD, deadline - PCD] = (a, b]. A
training trial counts for that window when its first result came within (a, b] after its own primary completion and
it was followed for the whole window (its primary completion + b is on or before the check date, so its label at the
window's end is known); it counts as met only if its result was clearly met by the window's end, and as not met
otherwise: not met, still vague or on a changed endpoint, or clear only after the window's end (rules 6 and 7). Trials
not followed for the whole window are left out, whatever their label: early results lean met, so keeping only the
clear ones would bias the rate up.
- B0: for each round trial, the share met among the training trials that count for its window, shrunk towards the
  share met in B1's fit with a weight of SHRINK trials. Few training trials were followed long enough for the windows
  of the round trials that completed earliest (windows ending 9-12 months out), so their B0 is mostly that share.
- B1: B0 moved, on the logit scale, by a registry-field model (phase 3, placebo or sham control, log enrolment,
  cancer, large company, China only, time-to-event endpoint; L2-regularised logistic regression with C = 0.1,
  features standardised) fitted once, on the training trials that count for the median round trial's window, then
  kept within [CLIP, 1 - CLIP]. One fit for all windows is an approximation; baselines_info.json gives its sensitivity
  to the window and to the organiser's label decisions.
- The early pass (the manifest's early_deadline, 31 March 2027): each round trial's window ends at that deadline
  instead, and B0 and B1 are worked out for it the same way, with the same fit (B1's registry-field model is not
  refitted); they are written as `p_met_mar` beside `p_met`. The final pass has no fields of its own: with no training
  trial followed that long, it uses `p_met`, as the rules say any entry without `p_met_dec` does.
These settings are fixed before the round opens.
Writes <out dir>/ref-b0.jsonl, ref-b1.jsonl (one line per trial with a p_met question), their meta files (with the
SHA-256s of this script, the training files, the corrections and the `--pin` files), baselines_training.jsonl,
baselines_round_features.jsonl and baselines_info.json (settings, the fit's window and counts, coefficients, the
matched rate by completion month, the training counts by China-only status, the sensitivity checks).
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np
from sklearn.linear_model import LogisticRegression

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "round2")))
try:                                     # the round's code; the refit from the shipped tables does not need it
    from tdcb.trials import numbers as tnum  # noqa: E402
    from tdcb.trials.operations import parse_date  # noqa: E402
    from tdcb.trials.packets import endpoint_kind  # noqa: E402
except ImportError:                      # standalone (the public dataset): the three helpers the refit uses
    import calendar
    import types

    def _load_cards(path):
        return {str(json.loads(x)["nct_id"]).upper(): json.loads(x) for x in open(path, encoding="utf-8") if x.strip()}

    tnum = types.SimpleNamespace(load_cards=_load_cards, has_p_met=lambda c: not c or c.get("design") != "none")

    def parse_date(s):
        s = str(s or "").strip()
        try:
            if len(s) == 7:
                y, m = int(s[:4]), int(s[5:7])
                return dt.date(y, m, calendar.monthrange(y, m)[1])
            return dt.date.fromisoformat(s[:10])
        except ValueError:
            return None

    def endpoint_kind(rec):
        raise SystemExit("building features from records needs the round's code (tdcb); refit with --train-table "
                         "and --round-features instead")

BIG = re.compile(r"pfizer|novartis|hoffmann|roche|genentech|merck sharp|astrazeneca|janssen|johnson|sanofi|glaxo|gsk|"
                 r"abbvie|bristol|lilly|amgen|novo nordisk|bayer|boehringer|takeda|gilead|regeneron|vertex|daiichi|"
                 r"astellas|eisai|otsuka|biogen|moderna|alexion", re.I)
NAMES = ["phase3", "placebo", "log_n", "cancer", "big_pharma", "china_only", "tte"]
C_REG = 0.1
CLIP = 0.05
SHRINK = 20
MONTH = 30.44


def feats(r: dict, m: dict | None) -> list:
    """The seven registry features (see the docstring); m is the trial's Round 2 reader row, if any."""
    from areas import area
    text = " ".join([r.get("title") or ""] + list(r.get("interventions") or []))
    placebo = ((m.get("reader") or {}).get("comparison") == "placebo or sham") if m else \
        bool(re.search(r"placebo|sham", text, re.I))
    cancer = (m["area"] == "cancer") if m else area({"conditions": r.get("conditions") or [],
                                                     "title": r.get("title") or "",
                                                     "interventions": r.get("interventions") or []}) == "cancer"
    countries = r.get("countries") or []
    return [float("PHASE3" in (r.get("phase") or [])), float(placebo), math.log(max(1, r.get("enrollment") or 1)),
            float(cancer), float(bool(BIG.search(r.get("sponsor") or ""))), float(countries == ["China"]),
            float(endpoint_kind(r) == "time_to_event")]


def pdate(s) -> dt.date:
    """A registry date for the baselines: YYYY-MM-DD as given, a month-only YYYY-MM as the 15th (mid-month), the same
    for training lags and for each round trial's window. (The operations questions read YYYY-MM as the month's last
    day, in the sponsor's favour; that is a different question.)"""
    s = str(s or "").strip()
    return dt.date(int(s[:4]), int(s[5:7]), 15) if len(s) == 7 else parse_date(s)


def months(a: dt.date, b: dt.date) -> float:
    return (b - a).days / MONTH


def training_rows(status, merged, recs, before, corrections: dict | None = None) -> list:
    """Training rows from the Round 2 results check, with the label audit's corrections applied:
    {nct_id: {"action": "keep" | "relabel" | "drop", "first_public": ..., "clear_date": ..., "met": ...}}. A clear
    result keeps the date it became clear: the correction's, the web check's clear date, or the first statement's
    (a paper, or a first statement that was already clear)."""
    rows = []
    for s0 in status:
        s = dict(s0)
        n = s["nct_id"]
        c = (corrections or {}).get(n)
        if c and c["action"] == "drop":
            continue
        if c and c["action"] == "relabel":
            s.update(first_public=c["first_public"], met=c["met"])
        if not (s["status"] in ("history", "test") and s.get("met") in ("yes", "no", "vague", "endpoint_changed")
                and s.get("sponsor_type") == "company" and s.get("first_public") and s.get("primary_completion_date")
                and n in recs and s["first_public"] < before):
            continue
        pcd = pdate(s["primary_completion_date"])
        first = s["first_public"][:10]
        clear = None                         # the date the result became clear (rule 6); none while vague
        if s["met"] in ("yes", "no"):
            if c and c["action"] == "relabel":
                clear = c.get("clear_date") or first
            elif s.get("met_source") == "web":
                clear = (s.get("web") or {}).get("clear_date") or first
            else:                            # a paper found through PubMed: the first statement is the paper
                clear = first
            clear = max(clear[:10], first)
        rows.append({"nct_id": n, "primary_completion_date": s["primary_completion_date"],
                     "first_public": first, "clear_date": clear, "audited": bool(c),
                     "lag_months": round(months(pcd, dt.date.fromisoformat(first)), 3),
                     "clear_lag_months": round(months(pcd, dt.date.fromisoformat(clear)), 3) if clear else None,
                     "met": int(s["met"] == "yes"), "label": s["met"], "pilot2": s["status"] == "test",
                     "features": dict(zip(NAMES, feats(recs[n], merged.get(n))))})
    return rows


def check_corrections(train: list, corr: dict) -> int:
    """With a shipped training table: every correction must already be in it (a dropped trial absent, a relabelled or
    kept one with the corrected label and dates). Returns the number of corrections checked against a row."""
    rows, bad, n = {t["nct_id"]: t for t in train}, [], 0
    for k, c in corr.items():
        t = rows.get(k)
        if c["action"] == "drop":
            if t is not None:
                bad.append(f"{k}: dropped in the audit, but in the table")
            continue
        if t is None:
            continue                         # left out for another reason (not a company trial, no record, ...)
        n += 1
        want = {"label": c["met"], "first_public": c["first_public"][:10]}
        if c["action"] == "relabel":
            want["clear_date"] = (c.get("clear_date") or c["first_public"])[:10]
        for f, v in want.items():
            if t.get(f) != v:
                bad.append(f"{k}: {f} is {t.get(f)!r} in the table, {v!r} in the audit")
    if bad:
        raise SystemExit("the training table does not carry the audit's corrections:\n  " + "\n  ".join(bad))
    return n


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def label_at(t: dict, b: float, check: dt.date) -> int | None:
    """A training trial's label as the round would read it at a deadline b months after its primary completion: 1 if
    its result was clearly met by then, 0 if not (not met, still vague or on a changed endpoint, or clear only later:
    rules 6 and 7); None if the check came before that deadline, so the label there is not known."""
    if pdate(t["primary_completion_date"]) + dt.timedelta(days=b * MONTH) > check:
        return None
    return int(t["label"] == "yes" and t.get("clear_lag_months") is not None and t["clear_lag_months"] <= b)


def counts_for(train: list, a: float, b: float, check: dt.date) -> tuple:
    """The training trials that count for the window (a, b] (first result within it, followed for all of it), with
    their labels, and how many had a first result in the window but were not followed for all of it."""
    inwin = [t for t in train if a < t["lag_months"] <= b]
    use = [(t, label_at(t, b, check)) for t in inwin]
    use = [(t, y) for t, y in use if y is not None]
    return use, len(inwin) - len(use)


def window_rate(a: float, b: float, train: list, check: dt.date, prior: float) -> dict:
    use, n_out = counts_for(train, a, b, check)
    k = sum(y for _, y in use)
    return {"window_months": [round(a, 1), round(b, 1)], "n": len(use), "n_not_followed_left_out": n_out,
            "raw": k / len(use) if use else None, "rate": (k + SHRINK * prior) / (len(use) + SHRINK)}


def fit_b1(train: list, a: float, b: float, check: dt.date) -> dict:
    """B1's registry-field model, fitted on the training trials that count for the window (a, b]."""
    use, n_out = counts_for(train, a, b, check)
    X = np.array([[t["features"][k] for k in NAMES] for t, _ in use])
    y = np.array([lab for _, lab in use])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    clf = LogisticRegression(C=C_REG, max_iter=1000).fit((X - mu) / sd, y)
    return {"clf": clf, "mu": mu, "sd": sd, "share_met": float(y.mean()), "use": use, "n_not_followed_left_out": n_out}


def b1_value(rate: float, x: np.ndarray, f: dict) -> float:
    logit = math.log(rate / (1 - rate)) + float(((x - f["mu"]) / f["sd"]) @ f["clf"].coef_[0])
    return min(max(1 / (1 + math.exp(-logit)), CLIP), 1 - CLIP)


def predict(pm: list, windows: dict, rfeat: dict, train: list, check: dt.date, f: dict) -> tuple:
    """B0 and B1 for each round trial, given its window and B1's fit."""
    rows0, rows1, cache = [], [], {}
    for n in pm:
        a, b = windows[n]
        if (a, b) not in cache:
            cache[(a, b)] = window_rate(a, b, train, check, f["share_met"])
        r = cache[(a, b)]["rate"]
        rows0.append({"nct_id": n, "p_met": round(r, 4)})
        rows1.append({"nct_id": n, "p_met": round(b1_value(r, np.array([rfeat[n][k] for k in NAMES]), f), 4)})
    return rows0, rows1


def summary(rows1: list, rfeat: dict, f: dict) -> dict:
    p = np.array([r["p_met"] for r in rows1])
    ch = np.array([rfeat[r["nct_id"]]["china_only"] == 1.0 for r in rows1])
    return {"n_fit": len(f["use"]), "share_met_fit": round(f["share_met"], 4),
            "china_only_coefficient": round(float(f["clf"].coef_[0][NAMES.index("china_only")]), 3),
            "b1_mean": round(float(p.mean()), 4), "b1_mean_china_only": round(float(p[ch].mean()), 4),
            "b1_mean_other": round(float(p[~ch].mean()), 4)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("round_dir")
    ap.add_argument("out")
    ap.add_argument("--train-table")
    ap.add_argument("--round-features", help="the round trials' features as written by an earlier run")
    ap.add_argument("--status")
    ap.add_argument("--merged")
    ap.add_argument("--records", nargs="*", default=[])
    ap.add_argument("--check-date", default="2026-10-25")
    ap.add_argument("--corrections", help="the training-label audit (JSONL: nct_id, action, first_public, clear_date, "
                    "met, audit): applied when building, checked against --train-table")
    ap.add_argument("--pin", nargs="*", default=[], help="evidence files whose SHA-256 the metadata records")
    ap.add_argument("--before", default="2026-10-27")
    a = ap.parse_args()
    recs = {}
    for p in a.records:
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                recs[r["nct_id"]] = r
    man = json.load(open(os.path.join(a.round_dir, "manifest.json")))
    cards = tnum.load_cards(os.path.join(a.round_dir, "cards.jsonl"))
    ops = {json.loads(line)["nct_id"]: json.loads(line) for line in open(os.path.join(a.round_dir, "operations.jsonl"))}
    corr = {json.loads(line)["nct_id"]: json.loads(line) for line in open(a.corrections) if line.strip()} \
        if a.corrections else None
    if a.train_table:
        train = [json.loads(line) for line in open(a.train_table) if line.strip()]
    else:
        status = [json.loads(line) for line in open(a.status) if line.strip()]
        merged = {json.loads(line)["nct_id"]: json.loads(line) for line in open(a.merged) if line.strip()}
        train = training_rows(status, merged, recs, a.before, corr)
    train = [t for t in train if t["nct_id"] not in set(man["trials"])]
    n_checked = check_corrections(train, corr) if corr else None   # built here, or read back: the same check
    # Only trials whose first result came at a time after primary completion the round can score: between the
    # earliest window start and the latest window end over the round's trials. Trials that reported years before
    # their registered completion (an interim win, with the completion date moved later) are another population.
    close_, deadline_ = dt.date.fromisoformat(man["closes"]), dt.date.fromisoformat(man["deadline"])
    pm_pcd = [pdate(ops[n]["primary_completion_date"]) for n in man["trials"] if tnum.has_p_met(cards.get(n))]
    lag_lo, lag_hi = min(months(p, close_) for p in pm_pcd), max(months(p, deadline_) for p in pm_pcd)
    n_before = len(train)
    train_all = [dict(t, in_lag_window=lag_lo < t["lag_months"] <= lag_hi) for t in train]
    train = [t for t in train_all if t["in_lag_window"]]
    check = dt.date.fromisoformat(a.check_date)
    pm = [n for n in man["trials"] if tnum.has_p_met(cards.get(n))]
    windows = {n: (months(pdate(ops[n]["primary_completion_date"]), close_),
                   months(pdate(ops[n]["primary_completion_date"]), deadline_)) for n in pm}
    # B1's registry-field model and B0's shrinkage target come from one fit, on the median round trial's window
    a_fit, b_fit = float(np.median([w[0] for w in windows.values()])), float(np.median([w[1] for w in windows.values()]))
    f = fit_b1(train, a_fit, b_fit, check)
    if a.round_features:
        rfeat = {json.loads(line)["nct_id"]: json.loads(line)["features"] for line in open(a.round_features)}
    else:
        if not all(n in recs for n in pm):
            raise SystemExit("--records must hold the round's trials (for their registry features)")
        merged_r = {json.loads(line)["nct_id"]: json.loads(line) for line in open(a.merged) if line.strip()} \
            if a.merged else {}
        rfeat = {n: dict(zip(NAMES, feats(recs[n], merged_r.get(n)))) for n in pm}
    os.makedirs(a.out, exist_ok=True)
    rows0, rows1 = predict(pm, windows, rfeat, train, check, f)
    early = {}
    if man.get("early_deadline"):                       # the early pass: the same rates and fit, windows ending earlier
        early_ = dt.date.fromisoformat(man["early_deadline"])
        windows_e = {n: (windows[n][0], months(pdate(ops[n]["primary_completion_date"]), early_)) for n in pm}
        rows0e, rows1e = predict(pm, windows_e, rfeat, train, check, f)
        for r, re_ in zip(rows0 + rows1, rows0e + rows1e):
            assert r["nct_id"] == re_["nct_id"]
            r["p_met_mar"] = re_["p_met"]
        p1e = np.array([r["p_met"] for r in rows1e])
        early = {"deadline": man["early_deadline"],
                 "window_end_months": [round(min(w[1] for w in windows_e.values()), 2),
                                       round(max(w[1] for w in windows_e.values()), 2)],
                 "n_round_trials_with_no_training_trial_followed": sum(
                     counts_for(train, *windows_e[n], check)[0] == [] for n in pm),
                 "b0_range_on_round": [min(r["p_met"] for r in rows0e), max(r["p_met"] for r in rows0e)],
                 "b1_on_round": dict(summary(rows1e, rfeat, f), n_at_upper_clip=int((p1e >= 1 - CLIP).sum()),
                                     n_at_lower_clip=int((p1e <= CLIP).sum()))}
    by_month = {}
    for n in pm:
        mkey = ops[n]["primary_completion_date"][:7]
        if mkey not in by_month:
            by_month[mkey] = window_rate(*windows[n], train, check, f["share_met"])
    # sensitivity: B1's fit on the windows of the round trials at the 25th and 75th percentile of window end, and with
    # the organiser's decided labels left out of training (they are the second labelling's disagreements)
    sens = {}
    for q in (25, 75):
        bq = float(np.percentile([w[1] for w in windows.values()], q))
        aq = bq - (b_fit - a_fit)
        fq = fit_b1(train, aq, bq, check)
        sens[f"fit_on_window_end_p{q}"] = dict(window_months=[round(aq, 2), round(bq, 2)],
                                               **summary(predict(pm, windows, rfeat, train, check, fq)[1], rfeat, fq))
    decided = {k for k, c in (corr or {}).items() if c.get("audit") == "organiser decision"}
    if decided:
        tr_x = [t for t in train if t["nct_id"] not in decided]
        fx = fit_b1(tr_x, a_fit, b_fit, check)
        sens["organiser_decisions_left_out"] = dict(n_left_out=len(decided),
                                                    **summary(predict(pm, windows, rfeat, tr_x, check, fx)[1], rfeat, fx))
    for name, rows in (("ref-b0", rows0), ("ref-b1", rows1)):
        with open(os.path.join(a.out, name + ".jsonl"), "w") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows))
    with open(os.path.join(a.out, "baselines_round_features.jsonl"), "w") as fh:
        fh.write("".join(json.dumps({"nct_id": n, "features": rfeat[n]}) + "\n" for n in pm))
    with open(os.path.join(a.out, "baselines_training.jsonl"), "w") as fh:
        fh.write("".join(json.dumps(t) + "\n" for t in sorted(train_all, key=lambda t: t["nct_id"])))
    china = Counter((bool(t["features"]["china_only"]), y) for t, y in f["use"])
    labels_fit = Counter(t["label"] if not (t["label"] == "yes" and not y) else "yes, clear only later"
                         for t, y in f["use"])
    p1 = np.array([r["p_met"] for r in rows1])
    info = {"settings": {"C": C_REG, "clip": CLIP, "shrink_trials": SHRINK, "check_date": a.check_date,
                         "before": a.before, "training_lag_months": [round(lag_lo, 2), round(lag_hi, 2)]},
            "n_train_before_lag_filter": n_before, "n_train": len(train), "n_train_pilot2": sum(t["pilot2"] for t in train),
            "corrections_checked_against_table": n_checked,
            "fit": {"window_months": [round(a_fit, 2), round(b_fit, 2)], "n": len(f["use"]),
                    "n_not_followed_left_out": f["n_not_followed_left_out"], "labels": dict(sorted(labels_fit.items())),
                    "share_met": round(f["share_met"], 4)},
            "training_by_china_only": {"china_only": {"met": china[(True, 1)], "not_met": china[(True, 0)]},
                                       "other": {"met": china[(False, 1)], "not_met": china[(False, 0)]}},
            "coefficients_per_sd": dict(zip(NAMES, [round(float(c), 3) for c in f["clf"].coef_[0]])),
            "matched_rate_by_completion_month": by_month,
            "b0_range_on_round": [min(r["p_met"] for r in rows0), max(r["p_met"] for r in rows0)],
            "b1_on_round": dict(summary(rows1, rfeat, f), n_at_upper_clip=int((p1 >= 1 - CLIP).sum()),
                                n_at_lower_clip=int((p1 <= CLIP).sum())),
            "sensitivity": sens}
    if early:
        info["early_pass"] = early
    json.dump(info, open(os.path.join(a.out, "baselines_info.json"), "w"), indent=1)
    # the metadata pins the files the baselines come from, so a changed training table is caught (build_space.py)
    shas = {fn: _sha(os.path.join(a.out, fn))
            for fn in ("baselines_training.jsonl", "baselines_round_features.jsonl", "baselines_info.json")}
    shas["make_baselines.py"] = _sha(os.path.abspath(__file__))
    for path in ([a.corrections] if a.corrections else []) + list(a.pin):
        shas[os.path.basename(path)] = _sha(path)
    shas = dict(sorted(shas.items()))
    meta = {"team": "ReadoutBench", "contact": "organiser", "setting": "closed", "web_access": False,
            "cost_usd_per_trial": 0, "models": [], "sources_sha256": shas}
    json.dump(dict(meta, entry_name="Base rate (B0)", harness="share met at the deadline among earlier company trials whose "
                   "first result came within the same window after primary completion and that were followed for all of "
                   "it, shrunk towards the share in B1's fit (make_baselines.py)"),
              open(os.path.join(a.out, "ref-b0.meta.json"), "w"), indent=1)
    json.dump(dict(meta, entry_name="Registry model (B1)", harness="B0's matched rate moved by a logistic regression "
                   "on 7 registry fields (C = 0.1), kept within [0.05, 0.95] (make_baselines.py)"),
              open(os.path.join(a.out, "ref-b1.meta.json"), "w"), indent=1)

    print(json.dumps({k: info[k] for k in ("n_train", "fit", "training_by_china_only", "coefficients_per_sd",
                                           "b0_range_on_round", "b1_on_round", "sensitivity")}))
    for mo, v in sorted(by_month.items()):
        print(" ", mo, v)
