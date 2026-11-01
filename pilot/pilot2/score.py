"""Pilot 2: score the decomposed forecasts.

usage: python3 -I score.py <set.json> <cards.jsonl> <extracted.jsonl> <b1.jsonl> --forecasts name=path [...] [--out report.json]
For each forecaster: p_met (Brier, mean, AUROC, skill against the base rate and B1); whether it adds information to
B1 (likelihood-ratio test of logit(B1) + logit(forecast) against logit(B1) alone); coherence (the p_met implied by its
own control, effect and variability forecasts through the trial's design, against its stated p_met); and, where the
published numbers were found, the errors and 80%-interval coverage of its effect and control-arm forecasts.
"""
import argparse
import json
import math

import numpy as np
from scipy.stats import chi2, norm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ap = argparse.ArgumentParser()
ap.add_argument("set")
ap.add_argument("cards")
ap.add_argument("extracted")
ap.add_argument("b1")
ap.add_argument("--forecasts", nargs="+", required=True)
ap.add_argument("--out")
a = ap.parse_args()
Z80 = norm.ppf(0.9)
rows = {r["nct_id"]: r for r in json.load(open(a.set))}
cards = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.cards) if l.strip()}
ext = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.extracted) if l.strip()}
b1 = {json.loads(l)["case_id"]: json.loads(l) for l in open(a.b1)}
F = {}
for spec in a.forecasts:
    name, path = spec.split("=", 1)
    F[name] = {json.loads(l)["case_id"]: json.loads(l) for l in open(path) if l.strip()}


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def interval(d, log=False):
    if not isinstance(d, dict):
        return None
    m, lo, hi = num(d.get("median")), num(d.get("low80")), num(d.get("high80"))
    if m is None or lo is None or hi is None:
        return None
    if log:
        if min(m, lo, hi) <= 0:
            return None
        m, lo, hi = math.log(m), math.log(lo), math.log(hi)
    lo, hi = min(lo, hi), max(lo, hi)
    return m, max((hi - lo) / (2 * Z80), 1e-6), lo, hi


def implied(f, c):
    """P(the trial reports success) from the forecaster's own predictive distribution of the reported effect."""
    kind = c.get("kind")
    ne, nc = num(c.get("n_experimental")), num(c.get("n_control"))
    if not ne or not nc:
        return None
    alpha = num(c.get("alpha_two_sided")) or 0.05
    z = norm.ppf(1 - alpha / 2)
    better = c.get("better")
    ef = interval(f.get("effect"), log=(kind == "time_to_event"))
    if ef is None or better not in ("lower", "higher"):
        return None
    mu, sig = ef[0], ef[1]
    if kind == "time_to_event":
        d = num(f.get("variability"))
        if not d or d <= 0:
            return None
        r = ne / (ne + nc)
        se = math.sqrt(1 / (d * r * (1 - r)))
    elif kind == "continuous":
        s = num(f.get("variability"))
        if not s or s <= 0:
            return None
        se = s * math.sqrt(1 / ne + 1 / nc)
    elif kind == "responder":
        cf = interval(f.get("control"))
        if cf is None:
            return None
        pc = min(max(cf[0] / 100, 0.001), 0.999)
        pe = min(max(pc + mu / 100, 0.001), 0.999)
        se = 100 * math.sqrt(pc * (1 - pc) / nc + pe * (1 - pe) / ne)
    else:
        return None
    margin = num(c.get("margin"))
    if c.get("design") == "non-inferiority" and margin is not None:
        m = abs(margin)
        if kind == "time_to_event":
            m = abs(math.log(margin)) if margin > 0 else None
            if m is None:
                return None
        t = (m - z * se) if better == "lower" else (-m + z * se)
    else:
        t = -z * se if better == "lower" else z * se
    p = norm.cdf((t - mu) / sig) if better == "lower" else 1 - norm.cdf((t - mu) / sig)
    return float(p), se


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def ll(p, y):
    p = np.clip(np.asarray(p), 1e-4, 1 - 1e-4)
    y = np.asarray(y)
    return float(np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def boot_ci(fn, n, k=2000, seed=0):
    rng = np.random.default_rng(seed)
    vals = [fn(rng.integers(0, n, n)) for _ in range(k)]
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


report = {}
ids_all = sorted(rows)
for name, f in F.items():
    ids = [n for n in ids_all if n in f and num(f[n].get("p_met")) is not None and n in b1]
    y = np.array([rows[n]["met"] for n in ids])
    p = np.array([num(f[n]["p_met"]) for n in ids])
    pb = np.array([b1[n]["p_met"] for n in ids])
    b0 = np.full(len(ids), b1[ids[0]]["b0"])
    res = {"n": len(ids), "met_share": float(y.mean()), "mean_p_met": float(p.mean()), "brier": brier(p, y),
           "brier_b1": brier(pb, y), "brier_b0": brier(b0, y), "auroc": float(roc_auc_score(y, p)),
           "auroc_b1": float(roc_auc_score(y, pb)), "recalls_result": int(sum(bool(f[n].get("recalls_result")) for n in ids))}
    res["skill_vs_b1"] = 1 - res["brier"] / res["brier_b1"]
    res["skill_vs_b1_ci"] = boot_ci(lambda i: 1 - brier(p[i], y[i]) / brier(pb[i], y[i]), len(ids))
    res["brier_diff_vs_b1_ci"] = boot_ci(lambda i: brier(p[i], y[i]) - brier(pb[i], y[i]), len(ids))
    # adds information: y ~ logit(B1) vs y ~ logit(B1) + logit(model), unpenalised
    X1 = logit(pb).reshape(-1, 1)
    X2 = np.column_stack([logit(pb), logit(p)])
    m1 = LogisticRegression(C=1e6, max_iter=1000).fit(X1, y)
    m2 = LogisticRegression(C=1e6, max_iter=1000).fit(X2, y)
    l1, l2 = ll(m1.predict_proba(X1)[:, 1], y), ll(m2.predict_proba(X2)[:, 1], y)
    res["adds_info_lr"] = 2 * (l2 - l1)
    res["adds_info_p"] = float(chi2.sf(max(0.0, 2 * (l2 - l1)), 1))
    res["adds_info_coef"] = float(m2.coef_[0][1])
    # recalibrated forecast alone (level and slope), in sample: what its ranking is worth
    m3 = LogisticRegression(C=1e6, max_iter=1000).fit(logit(p).reshape(-1, 1), y)
    res["recal_intercept_shift"] = float(m3.intercept_[0])
    # coherence
    imp = {n: implied(f[n], cards[n]) for n in ids if n in cards}
    ok = [n for n in ids if imp.get(n)]
    pi = np.array([imp[n][0] for n in ok])
    ps = np.array([num(f[n]["p_met"]) for n in ok])
    yo = np.array([rows[n]["met"] for n in ok])
    res["coherence"] = {"n": len(ok), "mean_abs_gap": float(np.mean(np.abs(pi - ps))) if ok else None,
                        "share_gap_over_0.2": float(np.mean(np.abs(pi - ps) > 0.2)) if ok else None,
                        "corr": float(np.corrcoef(pi, ps)[0, 1]) if len(ok) > 2 else None,
                        "brier_stated": brier(ps, yo) if ok else None, "brier_implied": brier(pi, yo) if ok else None,
                        "brier_diff_ci": boot_ci(lambda i: brier(pi[i], yo[i]) - brier(ps[i], yo[i]), len(ok)) if ok else None}
    # interval width vs the trial's own sampling error (an interval narrower than the noise alone is overconfident)
    narrow = [n for n in ok if interval(f[n].get("effect"), log=cards[n]["kind"] == "time_to_event")[1] < imp[n][1]]
    res["coherence"]["share_effect_interval_narrower_than_noise"] = len(narrow) / len(ok) if ok else None
    # effect and control accuracy where numbers were found
    eff, ctl = {"time_to_event": [], "continuous": [], "responder": []}, {"time_to_event": [], "continuous": [], "responder": []}
    for n in ids:
        e, c = ext.get(n), cards.get(n)
        if not e or not c or e.get("match") not in ("exact", "close"):
            continue
        k = c["kind"]
        if k not in eff:
            continue
        obs = num(e.get("effect_estimate"))
        iv = interval(f[n].get("effect"), log=(k == "time_to_event"))
        if obs is not None and iv is not None and (k != "time_to_event" or obs > 0):
            o = math.log(obs) if k == "time_to_event" else obs
            lo95, hi95 = num(e.get("effect_low95")), num(e.get("effect_high95"))
            se = None
            if lo95 is not None and hi95 is not None and (k != "time_to_event" or (lo95 > 0 and hi95 > 0)):
                se = ((math.log(hi95) - math.log(lo95)) if k == "time_to_event" else (hi95 - lo95)) / (2 * 1.96)
            eff[k].append({"nct": n, "err": abs(iv[0] - o), "z_err": abs(iv[0] - o) / se if se else None,
                           "covered": iv[2] <= o <= iv[3], "obs": obs})
        co = num(e.get("control_value"))
        ci = interval(f[n].get("control"))
        if co is not None and ci is not None:
            ctl[k].append({"nct": n, "err": abs(ci[0] - co), "rel_err": abs(ci[0] - co) / abs(co) if co else None,
                           "covered": ci[2] <= co <= ci[3]})
    res["effect"] = {k: {"n": len(v), "median_err": float(np.median([x["err"] for x in v])) if v else None,
                         "median_err_in_se": float(np.median([x["z_err"] for x in v if x["z_err"] is not None]))
                         if any(x["z_err"] is not None for x in v) else None,
                         "coverage80": float(np.mean([x["covered"] for x in v])) if v else None} for k, v in eff.items()}
    res["control"] = {k: {"n": len(v), "median_err": float(np.median([x["err"] for x in v])) if v else None,
                          "median_rel_err": float(np.median([x["rel_err"] for x in v if x["rel_err"] is not None]))
                          if any(x["rel_err"] is not None for x in v) else None,
                          "coverage80": float(np.mean([x["covered"] for x in v])) if v else None} for k, v in ctl.items()}
    res["_effect_rows"] = eff
    res["_control_rows"] = ctl
    res["main_risk"] = dict(sorted(((r, sum(1 for n in ids if f[n].get("main_risk") == r))
                                     for r in {f[n].get("main_risk") for n in ids}), key=lambda kv: -kv[1]))
    report[name] = res
for name, r in report.items():
    print(f"\n== {name}: n={r['n']} (met {r['met_share']:.0%}), mean p_met {r['mean_p_met']:.2f}, recalls {r['recalls_result']}")
    print(f"   Brier {r['brier']:.3f} | B1 {r['brier_b1']:.3f} | B0 {r['brier_b0']:.3f} | skill vs B1 {r['skill_vs_b1']:+.2f} "
          f"{[round(x, 2) for x in r['skill_vs_b1_ci']]} | AUROC {r['auroc']:.2f} (B1 {r['auroc_b1']:.2f})")
    print(f"   adds information to B1: LR {r['adds_info_lr']:.2f}, p = {r['adds_info_p']:.3f}, coefficient {r['adds_info_coef']:+.2f};"
          f" recalibration intercept {r['recal_intercept_shift']:+.2f}")
    c = r["coherence"]
    print(f"   coherence (n={c['n']}): mean |implied - stated| {c['mean_abs_gap']:.2f}, gap > 0.2 in {c['share_gap_over_0.2']:.0%},"
          f" corr {c['corr']:.2f}; Brier stated {c['brier_stated']:.3f} vs implied {c['brier_implied']:.3f}"
          f" (diff CI {[round(x, 3) for x in c['brier_diff_ci']]}); effect interval narrower than noise in"
          f" {c['share_effect_interval_narrower_than_noise']:.0%}")
    for k in ("time_to_event", "continuous", "responder"):
        e, ct = r["effect"][k], r["control"][k]
        print(f"   {k}: effect n={e['n']} median err {e['median_err']} (in SE {e['median_err_in_se']}), cover80 {e['coverage80']};"
              f" control n={ct['n']} median rel err {ct['median_rel_err']}, cover80 {ct['coverage80']}")
    print("   main risk named:", r["main_risk"])
if a.out:
    json.dump(report, open(a.out, "w"), indent=1, default=str)
