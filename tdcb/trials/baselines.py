"""Track C baselines, fitted only on trials reported before the cutoff.

B0: the share of earlier trials that met their primary endpoint, for every question; the
median earlier hazard ratio, with the 10th and 90th percentiles as the 80% interval.
B1: an L2-regularised logistic regression on a dozen registry features (endpoint type,
placebo control, number of primary endpoints, size, countries, sponsor, setting); hazard
ratio as in B0.
B1's training trials get out-of-fold predictions, so its scores on the pre-cutoff set are not
in-sample. B0 is one rate for every trial (a leave-fold-out rate would anti-correlate with
the held-out outcomes and fake a negative AUROC).
"""
from __future__ import annotations

import math
import re

import numpy as np

from .packets import endpoint_kind

BIG_PHARMA = re.compile(r"merck|msd|astrazeneca|roche|genentech|hoffmann|pfizer|seagen|bristol|novartis|lilly|"
                        r"janssen|johnson|abbvie|amgen|gilead|glaxo|gsk|sanofi|bayer|daiichi|astellas|takeda|"
                        r"boehringer|eisai|beigene|beone|regeneron|exelixis|ipsen|servier|jazz|incyte|"
                        r"acerta|celgene|aragon|loxo|kite pharma|juno|pharmacyclics|medimmune|tesaro|chugai|"
                        r"array biopharma", re.I)       # including subsidiaries that sponsor under their own name


def features(rec: dict) -> dict:
    po = (rec.get("primary_outcomes") or [{}])
    first = (po[0] or {}).get("measure") or ""
    text = " ".join(str(rec.get(k) or "") for k in ("title", "brief_title", "brief_summary"))
    countries = rec.get("countries") or []
    try:
        n = float(rec.get("enrollment") or 0)
    except (TypeError, ValueError):
        n = 0.0
    return {
        "tte": float(endpoint_kind(rec) == "time_to_event"),
        "os_first": float(bool(re.search(r"overall survival|\bOS\b", first, re.I))),
        "pfs_first": float(bool(re.search(r"progression[- ]free|\bPFS\b", first, re.I))),
        "n_primary": float(len(po)),
        "placebo": float(any("placebo" in str(i).lower() for i in rec.get("interventions") or [])),
        "log_enrollment": math.log1p(n),
        "n_countries": float(len(countries)),
        "china_only": float(countries == ["China"]),
        "big_pharma": float(bool(BIG_PHARMA.search(str(rec.get("sponsor") or "")))),
        "first_line": float(bool(re.search(r"first[- ]line|1L\b|untreated|treatment[- ]na[iï]ve|previously untreated",
                                           text, re.I))),
        "early_stage": float(bool(re.search(r"adjuvant|neoadjuvant|perioperative|resect", text, re.I))),
        "n_secondary": float(len(rec.get("secondary_outcomes") or [])),
    }


def _hr_prior(train_key: list[dict]):
    hrs = np.array([k["hr"] for k in train_key if k.get("hr")])
    if len(hrs) < 5:
        return 0.75, 0.55, 1.0
    return float(np.median(hrs)), float(np.percentile(hrs, 10)), float(np.percentile(hrs, 90))


def fit_and_predict(records: dict, key: list[dict], k_folds: int = 5, seed: int = 0
                    ) -> tuple[list[dict], list[dict], dict]:
    """Fit on pre-cutoff questions, predict every question. Returns (b0 rows, b1 rows, info).

    B0 is the training base rate for every trial. For B1, trials outside the training set get
    the model fitted on all training trials, and training trials get out-of-fold predictions
    (k folds; k_folds < 2 gives in-sample predictions).
    """
    train = [k for k in key if k["set"] == "pre_cutoff" and k["nct_id"] in records]
    rate = float(np.mean([k["met"] for k in train])) if train else 0.5
    hr_m, hr_lo, hr_hi = _hr_prior(train)
    info = {"n_train": len(train), "base_rate": rate, "hr_prior": [hr_m, hr_lo, hr_hi]}
    ids = sorted(records)
    names = list(features(next(iter(records.values()))).keys()) if records else []
    X = {i: [features(records[i])[n] for n in names] for i in ids}
    p0 = {i: rate for i in ids}
    hr0 = {i: (hr_m, hr_lo, hr_hi) for i in ids}
    p1 = dict(p0)
    tr_ids = [k["nct_id"] for k in train]
    y = np.array([k["met"] for k in train])
    fold = np.random.default_rng(seed).permutation(len(tr_ids)) % max(k_folds, 1) if tr_ids else np.array([])
    can_fit = lambda yy: len(yy) >= 20 and len(set(yy.tolist())) == 2
    if can_fit(y):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        def fit(idx):
            Xt = np.array([X[tr_ids[j]] for j in idx])
            sc = StandardScaler().fit(Xt)
            return sc, LogisticRegression(C=0.3, max_iter=1000).fit(sc.transform(Xt), y[idx])

        sc, clf = fit(np.arange(len(tr_ids)))
        for i in ids:
            p1[i] = float(clf.predict_proba(sc.transform([X[i]]))[0, 1])
        for f in range(k_folds if k_folds >= 2 and len(tr_ids) >= 2 * k_folds else 0):
            idx = np.where(fold != f)[0]
            if not can_fit(y[idx]):
                continue
            scf, clff = fit(idx)
            for j in np.where(fold == f)[0]:
                p1[tr_ids[j]] = float(clff.predict_proba(scf.transform([X[tr_ids[j]]]))[0, 1])
        info["b1_coefficients"] = dict(zip(names, [round(float(c), 3) for c in clf.coef_[0]]))
    row = lambda i, p: {"case_id": i, "p_met": round(p, 4), "hr_median": hr0[i][0], "hr_low80": hr0[i][1],
                        "hr_high80": hr0[i][2]}
    if k_folds >= 2:
        info["out_of_fold"] = f"B1 on training trials: {k_folds}-fold out-of-fold predictions"
    return [row(i, p0[i]) for i in ids], [row(i, p1[i]) for i in ids], info
