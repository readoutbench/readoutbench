"""Pilot 2: recalibrated and combined Brier scores (5-fold CV), paired Brier differences, calibration bins.
usage: python3 -I compare.py <set.json> <b1.jsonl> name=forecasts.jsonl [...]"""
import json, sys, math
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
setp, b1p = sys.argv[1], sys.argv[2]
rows = {r["nct_id"]: r for r in json.load(open(setp))}
b1 = {json.loads(l)["case_id"]: json.loads(l) for l in open(b1p)}
F = {}
for s in sys.argv[3:]:
    n, p = s.split("=", 1)
    F[n] = {json.loads(l)["case_id"]: json.loads(l) for l in open(p) if l.strip()}
ids = sorted(set.intersection(*[set(f) for f in F.values()]) & set(b1))
y = np.array([rows[n]["met"] for n in ids]); print("n", len(ids), "met", int(y.sum()), "not met", int(len(y) - y.sum()))
lg = lambda p: np.log(np.clip(p, 1e-3, 1 - 1e-3) / (1 - np.clip(p, 1e-3, 1 - 1e-3)))
pb = np.array([b1[n]["p_met"] for n in ids])
P = {k: np.array([float(f[n]["p_met"]) for n in ids]) for k, f in F.items()}
P["B1"] = pb
br = lambda p: float(np.mean((p - y) ** 2))
def cv(X, k=5, reps=20):
    out = np.zeros(len(y)); 
    for r in range(reps):
        sk = StratifiedKFold(k, shuffle=True, random_state=r)
        for tr, te in sk.split(X, y):
            m = LogisticRegression(C=1e6, max_iter=1000).fit(X[tr], y[tr]); out[te] += m.predict_proba(X[te])[:, 1] / reps
    return out
print("\nraw / recalibrated (5-fold CV) Brier, AUROC")
for k, p in P.items():
    rc = cv(lg(p).reshape(-1, 1))
    print(f"  {k:7s} raw {br(p):.3f}  recal {br(rc):.3f}  AUROC {roc_auc_score(y, p):.3f}  mean {p.mean():.2f}")
for k in F:
    c = cv(np.column_stack([lg(pb), lg(P[k])]))
    print(f"  B1+{k:6s} combined CV Brier {br(c):.3f} AUROC {roc_auc_score(y, c):.3f}")
if len(F) > 1:
    ks = list(F)
    c = cv(np.column_stack([lg(pb)] + [lg(P[k]) for k in ks]))
    print(f"  B1+all combined CV Brier {br(c):.3f}")
rng = np.random.default_rng(1)
print("\npaired raw Brier differences (95% bootstrap)")
names = list(P)
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a, b = P[names[i]], P[names[j]]
        d = (a - y) ** 2 - (b - y) ** 2
        bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
        print(f"  {names[i]} - {names[j]}: {d.mean():+.3f} [{np.percentile(bs,2.5):+.3f}, {np.percentile(bs,97.5):+.3f}] sd {d.std():.3f}")
print("\ncalibration bins (stated p_met)")
edges = [0, .3, .5, .7, .85, 1.01]
for k, p in P.items():
    s = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        s.append(f"[{lo:.2f},{hi:.2f}) n={m.sum():3d} p={p[m].mean() if m.any() else float('nan'):.2f} met={y[m].mean() if m.any() else float('nan'):.2f}")
    print(" ", k, " | ".join(s))
print("\ncorrelations of logit p_met")
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        print(f"  {names[i]}~{names[j]} {np.corrcoef(lg(P[names[i]]), lg(P[names[j]]))[0,1]:.2f}")
