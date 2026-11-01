"""usage: python3 -I numscore.py <set.json> <cards.jsonl> <extracted.jsonl> name=forecasts.jsonl [...]
Paired log scores of the published effect and control numbers under each model's forecast (normal on the forecast scale,
log scale for hazard ratios); unit-free when differenced between models on the same trial. Also implied vs stated p_met."""
import json, sys, math
import numpy as np
from scipy.stats import norm
setp, cardp, extp = sys.argv[1:4]
rows = {r["nct_id"]: r for r in json.load(open(setp))}
cards = {json.loads(l)["nct_id"]: json.loads(l) for l in open(cardp) if l.strip()}
ext = {json.loads(l)["nct_id"]: json.loads(l) for l in open(extp) if l.strip()}
F = {}
for s in sys.argv[4:]:
    n, p = s.split("=", 1)
    F[n] = {json.loads(l)["case_id"]: json.loads(l) for l in open(p) if l.strip()}
Z = norm.ppf(0.9)
def num(x):
    try:
        v = float(x); return v if math.isfinite(v) else None
    except (TypeError, ValueError): return None
def iv(d, log=False):
    if not isinstance(d, dict): return None
    m, lo, hi = (num(d.get(k)) for k in ("median", "low80", "high80"))
    if None in (m, lo, hi): return None
    if log:
        if min(m, lo, hi) <= 0: return None
        m, lo, hi = map(math.log, (m, lo, hi))
    return m, max((max(lo, hi) - min(lo, hi)) / (2 * Z), 1e-9)
names = list(F)
for what in ("effect", "control"):
    L = {}
    for n, e in ext.items():
        if e.get("match") not in ("exact", "close"): continue
        k = cards[n]["kind"]; log = what == "effect" and k == "time_to_event"
        o = num(e.get("effect_estimate" if what == "effect" else "control_value"))
        if o is None or (log and o <= 0): continue
        o = math.log(o) if log else o
        vs = [iv(F[m][n].get(what), log) for m in names]
        if any(v is None for v in vs): continue
        # floor the spread at 1% of the scale of the value so a zero-width interval is not -inf
        fl = 0.01 * max(abs(o), 1e-3) if not log else 0.01
        L[n] = [norm.logpdf(o, v[0], max(v[1], fl)) for v in vs]
    A = np.array(list(L.values()))
    print(f"\n{what}: n={len(A)} trials with a number for all models")
    rng = np.random.default_rng(0)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            d = A[:, i] - A[:, j]
            bs = [np.mean(d[rng.integers(0, len(d), len(d))]) for _ in range(4000)]
            wins = np.mean(d > 0)
            print(f"  {names[i]} - {names[j]}: mean log-score diff {d.mean():+.2f} [{np.percentile(bs,2.5):+.2f}, {np.percentile(bs,97.5):+.2f}], "
                  f"median {np.median(d):+.2f}, {names[i]} better on {wins:.0%}, sd {d.std():.2f}")
# implied vs stated
Z80 = norm.ppf(0.9)
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



for m in names:
    imp, st, y = [], [], []
    for n in rows:
        r = implied(F[m][n], cards[n])
        if r: imp.append(r[0]); st.append(float(F[m][n]["p_met"])); y.append(rows[n]["met"])
    imp, st, y = map(np.array, (imp, st, y))
    from sklearn.metrics import roc_auc_score
    print(f"\n{m}: implied mean {imp.mean():.2f} vs stated {st.mean():.2f}; implied <0.1 or >0.9 in {np.mean((imp<.1)|(imp>.9)):.0%} vs stated {np.mean((st<.1)|(st>.9)):.0%};"
          f" AUROC implied {roc_auc_score(y, imp):.3f} stated {roc_auc_score(y, st):.3f}")
