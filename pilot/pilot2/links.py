"""Pilot 2: which link breaks. Signed errors of the effect and control-arm forecasts against the published numbers.
usage: python3 -I links.py <set.json> <cards.jsonl> <extracted.jsonl> name=forecasts.jsonl [...]"""
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
    except (TypeError, ValueError):
        return None
def iv(d, log=False):
    if not isinstance(d, dict): return None
    m, lo, hi = (num(d.get(k)) for k in ("median", "low80", "high80"))
    if None in (m, lo, hi): return None
    if log:
        if min(m, lo, hi) <= 0: return None
        m, lo, hi = map(math.log, (m, lo, hi))
    return m, max((max(lo, hi) - min(lo, hi)) / (2 * Z), 1e-6), min(lo, hi), max(lo, hi)
def ctl_dir(c):
    k, cm = c["kind"], (c.get("control_measure") or "").lower()
    if k in ("continuous", "responder"): return c["better"]
    if any(w in cm for w in ("median", "free", "survival")) and "rate of" not in cm: return "higher"
    if any(w in cm for w in ("rate", "relapse", "events", "incidence", "cumulative")): return "lower"
    return None
from collections import Counter
print("match:", Counter(e.get("match") for e in ext.values()), "of", len(ext))
for name, f in F.items():
    E, C = [], []
    for n, e in ext.items():
        c = cards.get(n)
        if not c or n not in f or e.get("match") not in ("exact", "close"): continue
        k = c["kind"]; y = rows[n]["met"]
        obs = num(e.get("effect_estimate"))
        v = iv(f[n].get("effect"), log=k == "time_to_event")
        if obs is not None and v and (k != "time_to_event" or obs > 0):
            o = math.log(obs) if k == "time_to_event" else obs
            s = 1 if c["better"] == "higher" else -1
            # optimism > 0: forecast median better than the observed effect
            E.append({"n": n, "k": k, "y": y, "z": s * (v[0] - o) / v[1], "pit": norm.cdf((o - v[0]) / v[1]) if s > 0 else norm.cdf((v[0] - o) / v[1]),
                      "cov": v[2] <= o <= v[3], "risk": f[n]["main_risk"]})
        co = num(e.get("control_value")); cv = iv(f[n].get("control")); d = ctl_dir(c)
        if co is not None and cv and d:
            s = 1 if d == "higher" else -1
            C.append({"n": n, "k": k, "y": y, "z": s * (cv[0] - co) / cv[1], "cov": cv[2] <= co <= cv[3], "risk": f[n]["main_risk"]})
    print(f"\n== {name}")
    for lab, L in (("effect", E), ("control", C)):
        if not L: continue
        z = np.array([x["z"] for x in L]); cov = np.mean([x["cov"] for x in L])
        print(f"  {lab}: n={len(L)} cover80 {cov:.0%}; forecast better than observed in {np.mean(z>0):.0%}; median signed z {np.median(z):+.2f}")
        for y in (1, 0):
            zz = np.array([x["z"] for x in L if x["y"] == y])
            if len(zz): print(f"     {'met' if y else 'not met'}: n={len(zz)} forecast better than observed {np.mean(zz>0):.0%}, median z {np.median(zz):+.2f}")
        for k in ("time_to_event", "continuous", "responder"):
            zz = [x for x in L if x["k"] == k]
            if zz: print(f"     {k}: n={len(zz)} cover80 {np.mean([x['cov'] for x in zz]):.0%}, median z {np.median([x['z'] for x in zz]):+.2f}")
    # not-met trials: what went wrong vs what was named
    nm = {x["n"]: x for x in E if x["y"] == 0}; nc = {x["n"]: x for x in C if x["y"] == 0}
    print("  not-met trials: named risk | effect weaker than forecast? | control stronger than forecast?")
    for n in sorted(set(nm) | set(nc)):
        print(f"     {n} {f[n]['main_risk']:26s} | {'yes' if n in nm and nm[n]['z']>0 else ('no' if n in nm else '-'):3s} | {'yes' if n in nc and nc[n]['z']<0 else ('no' if n in nc else '-')}")
