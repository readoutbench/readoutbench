"""Track C scoring: probability that a trial meets its primary endpoint, and the hazard ratio.

Probability: Brier score and log loss (and skill against a reference such as B0), AUROC,
calibration slope and intercept, mean forecast against the observed rate.
Hazard ratio, for time-to-event primary endpoints with a reported HR: median absolute
error of log(HR), coverage of the 80% interval, and the interval score for an 80% interval
on the log scale (Gneiting and Raftery 2007; lower is better; it rewards narrow intervals
and penalises misses).
Decision score: if every trial forecast below a threshold (default 0.3) had been cancelled,
how many failures would have been avoided and how many winners lost. Both counts are
reported, not a net number, because a lost winner costs far more than an avoided failure.
Only questions whose result became public after ``cutoff`` count, so each forecaster is
scored on trials it could not have read about.
"""
from __future__ import annotations

import json
import math

import numpy as np

from .. import metrics


def load_predictions(path: str) -> dict:
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(o, dict) and o.get("case_id"):
                out[str(o["case_id"]).upper()] = o
    return out


def _p(o):
    try:
        v = float(o.get("p_met"))
    except (TypeError, ValueError, AttributeError):
        return None
    return v if 0 <= v <= 1 and math.isfinite(v) else None


def _hr(o):
    try:
        m, lo, hi = (float(o.get(k)) for k in ("hr_median", "hr_low80", "hr_high80"))
    except (TypeError, ValueError, AttributeError):
        return None
    if not all(math.isfinite(v) and v > 0 for v in (m, lo, hi)) or not lo <= m <= hi:
        return None
    return m, lo, hi


def select(key: list[dict], cutoff: str | None = None, sets=("post_cutoff",)) -> list[dict]:
    rows = [k for k in key if k["set"] in sets or (cutoff and k["set"] in ("post_cutoff", "pre_cutoff"))]
    if cutoff:
        rows = [k for k in rows if k.get("first_public_date") and k["first_public_date"] > cutoff]
    return rows


def _binary(p, y):
    status = y.astype(int)
    w = np.ones(len(y))
    out = {"n": int(len(y)), "event_rate": float(y.mean()), "mean_pred": float(p.mean()),
           "brier": metrics.brier(p, status, w), "log_loss": metrics.log_loss(p, status, w),
           "auroc": metrics.weighted_auc(p, status, w), "ece": metrics.ece(p, status, w)}
    out.update({f"calibration_{k}": v for k, v in metrics.calibration(p, status, w).items()})
    out.update(murphy(p, y))
    return out


def murphy(p, y, bins: int = 10) -> dict:
    """Murphy's split of the Brier score into reliability (miscalibration; lower is better), resolution (how much the
    forecasts sort met from not met; higher is better) and uncertainty (the outcome's own variance), with forecasts
    grouped in `bins` equal-width bins: Brier ~ reliability - resolution + uncertainty. `level_gap` is mean forecast
    minus observed rate: the part of the score any entry could fix by moving every forecast by the same amount."""
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    n = len(y)
    if n == 0:
        return {}
    ybar = float(y.mean())
    idx = np.minimum((p * bins).astype(int), bins - 1)
    rel = res = 0.0
    for b in range(bins):
        m = idx == b
        k = int(m.sum())
        if k:
            pb, yb = float(p[m].mean()), float(y[m].mean())
            rel += k * (pb - yb) ** 2
            res += k * (yb - ybar) ** 2
    return {"reliability": rel / n, "resolution": res / n, "uncertainty": ybar * (1 - ybar),
            "level_gap": float(p.mean()) - ybar}


def decision(p, y, threshold: float = 0.3) -> dict:
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    cancel = p < threshold
    return {"threshold": threshold, "n_cancelled": int(cancel.sum()),
            "failures_avoided": int((cancel & (y == 0)).sum()), "failures_total": int((y == 0).sum()),
            "winners_lost": int((cancel & (y == 1)).sum()), "winners_total": int((y == 1).sum())}


def _hr_metrics(pred, true, alpha=0.2):
    m, lo, hi = (np.log(np.array([x[i] for x in pred])) for i in range(3))
    y = np.log(np.array(true))
    width = hi - lo
    score = width + (2 / alpha) * (lo - y) * (y < lo) + (2 / alpha) * (y - hi) * (y > hi)
    return {"n_hr": int(len(y)), "median_abs_log_error": float(np.median(np.abs(m - y))),
            "coverage80": float(np.mean((y >= lo) & (y <= hi))), "interval_score80": float(np.mean(score)),
            "median_width_ratio": float(np.median(np.exp(width)))}


def score(preds: dict, key: list[dict], ref: dict | None = None, cutoff: str | None = None,
          sets=("post_cutoff",), n_boot: int = 0, seed: int = 0, refs: dict | None = None,
          clusters: dict | None = None, strict: bool = False) -> dict:
    """Score one entry's p_met on the key's questions.

    ref: one reference entry (skill reported as bss_vs_ref); refs: several, {name: preds} (bss_vs_<name>).
    clusters: {nct_id: group}; the bootstrap then resamples whole groups (sister trials together), and the
    differences against each reference are paired (same resample for both). strict: a missing or invalid p_met
    raises instead of counting as 0.5 (used for registered entries, which the validator has already checked)."""
    rows = select(key, cutoff, sets)
    out = {"n_questions": len(rows), "cutoff": cutoff, "sets": list(sets)}
    if not rows:
        return out
    pv = [_p(preds.get(k["nct_id"])) for k in rows]
    if strict and any(v is None for v in pv):
        bad = [k["nct_id"] for k, v in zip(rows, pv) if v is None]
        raise ValueError(f"no valid p_met for {len(bad)} scored trials, e.g. {bad[:3]}")
    out["validity_rate"] = float(np.mean([v is not None for v in pv]))
    p = np.array([0.5 if v is None else v for v in pv])
    y = np.array([1.0 if k["met"] == 1 else 0.0 for k in rows])
    out["probability"] = _binary(p, y)
    out["decision"] = decision(p, y)
    allrefs = dict(refs or {})
    if ref is not None:
        allrefs["ref"] = ref
    rarr = {}
    for name, rp in allrefs.items():
        r = np.array([(_p(rp.get(k["nct_id"])) if _p(rp.get(k["nct_id"])) is not None else 0.5) for k in rows])
        rarr[name] = r
        b_ref = metrics.brier(r, y.astype(int), np.ones(len(y)))
        out["probability"][f"brier_{name}"] = b_ref
        out["probability"][f"bss_vs_{name}"] = float(1 - out["probability"]["brier"] / b_ref) if b_ref > 0 else float("nan")
    hr_rows = [(k, _hr(preds.get(k["nct_id"]))) for k in rows if k.get("endpoint_kind") == "time_to_event" and k.get("hr")]
    out["n_hr_reported"] = len(hr_rows)
    ok = [(k, h) for k, h in hr_rows if h is not None]
    if ok:
        out["hazard_ratio"] = _hr_metrics([h for _, h in ok], [k["hr"] for k, _ in ok])
        out["hazard_ratio"]["validity_rate"] = len(ok) / len(hr_rows)
    if n_boot:
        rng = np.random.default_rng(seed)
        if clusters:
            gid = [clusters.get(k["nct_id"], k["nct_id"]) for k in rows]
            _, inv = np.unique(np.array(gid, dtype=object).astype(str), return_inverse=True)
            groups = [np.flatnonzero(inv == g) for g in range(inv.max() + 1)]
        else:
            groups = [np.array([i]) for i in range(len(rows))]
        out["n_clusters"] = len(groups)
        vals = {"brier": [], "auroc": [], **{f"bss_vs_{n}": [] for n in rarr}, **{f"brier_minus_{n}": [] for n in rarr}}
        for _ in range(n_boot):
            idx = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
            m = _binary(p[idx], y[idx])
            vals["brier"].append(m["brier"])
            vals["auroc"].append(m["auroc"])
            for name, r in rarr.items():
                b_ref = metrics.brier(r[idx], y[idx].astype(int), np.ones(len(idx)))
                vals[f"bss_vs_{name}"].append(1 - m["brier"] / b_ref if b_ref > 0 else float("nan"))
                vals[f"brier_minus_{name}"].append(m["brier"] - b_ref)
        out["ci95"] = {k: [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))]
                       for k, v in vals.items() if v and np.isfinite(v).any()}
    return out
