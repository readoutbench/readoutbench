"""Pilot 2: effect CRPS in units of each trial's own standard error (trials with a 95% CI), paired between models.
usage: python3 -I crps.py <set.json> <cards.jsonl> <extracted.jsonl> name=forecasts.jsonl [...]"""
import json, sys, math
import numpy as np
from scipy.stats import norm
setp, cardp, extp = sys.argv[1:4]
cards = {json.loads(l)["nct_id"]: json.loads(l) for l in open(cardp) if l.strip()}
ext = {json.loads(l)["nct_id"]: json.loads(l) for l in open(extp) if l.strip()}
F = {}
for s in sys.argv[4:]:
    n, p = s.split("=", 1); F[n] = {json.loads(l)["case_id"]: json.loads(l) for l in open(p) if l.strip()}
Z = norm.ppf(0.9)
def num(x):
    try:
        v = float(x); return v if math.isfinite(v) else None
    except (TypeError, ValueError): return None
def iv(d, log=False):
    m, lo, hi = (num(d.get(k)) for k in ("median", "low80", "high80")) if isinstance(d, dict) else (None,)*3
    if None in (m, lo, hi): return None
    if log:
        if min(m, lo, hi) <= 0: return None
        m, lo, hi = map(math.log, (m, lo, hi))
    return m, max((max(lo, hi) - min(lo, hi)) / (2 * Z), 1e-9)
def crps(mu, s, o):
    z = (o - mu) / s
    return s * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / math.sqrt(math.pi))
names = list(F); R = {}; worst = {m: [] for m in names}
for n, e in ext.items():
    if e.get("match") not in ("exact", "close"): continue
    k = cards[n]["kind"]; log = k == "time_to_event"
    o, lo, hi = (num(e.get(x)) for x in ("effect_estimate", "effect_low95", "effect_high95"))
    if None in (o, lo, hi) or (log and min(o, lo, hi) <= 0): continue
    if log: o, lo, hi = map(math.log, (o, lo, hi))
    se = (hi - lo) / (2 * 1.96)
    if se <= 0: continue
    vs = [iv(F[m][n].get("effect"), log) for m in names]
    if any(v is None for v in vs): continue
    R[n] = [crps(v[0], v[1], o) / se for v in vs]
    for m, v in zip(names, vs): worst[m].append(((o - v[0]) / v[1], n))
A = np.array(list(R.values()))
print(f"effect CRPS in units of the trial's own standard error, n={len(A)} trials with a 95% CI")
for i, m in enumerate(names): print(f"  {m}: mean {A[:, i].mean():.2f}, median {np.median(A[:, i]):.2f}")
rng = np.random.default_rng(0)
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        d = A[:, j] - A[:, i]
        bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
        print(f"  {names[i]} better than {names[j]} by {d.mean():+.2f} SE [{np.percentile(bs,2.5):+.2f}, {np.percentile(bs,97.5):+.2f}]; wins {np.mean(d>0):.0%}; sd {d.std():.2f}")
for m in names:
    w = sorted(worst[m], key=lambda t: -abs(t[0]))[:3]
    print(" ", m, "largest misses (in own sigma):", [(round(z, 1), n) for z, n in w])
