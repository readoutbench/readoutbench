"""Pilot 3, part C: what the Round 1 leaderboard may look like at full size.

usage: python3 -I simulate.py <backtest dir> <dry-run dir> <out.json> [--sims 4000]

- p_met and numbers: Pilot 2's reported trials (part A) are resampled to the round's expected size: 250 p_met results
  and the published numbers that come with them (Pilot 2: 58% of trials published the effect, 47% the control arm).
  Entries keep their real forecasts and the trials their real outcomes, so the spread is real; the trial mix is
  Pilot 2's (no trial stopped early, 73% met).
- Operations: no outcome exists yet. The dry run's forecasts (part B) are resampled to the round's mix (673 main,
  13 equivalence, 166 operations-only trials), and outcomes are drawn from the three models' average forecast
  (the "consensus world"). This shows how far apart entries can land when none of them knows better than the
  average; it cannot show who is right.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import numbers as tnum  # noqa: E402
from tdcb.trials import operations as tops  # noqa: E402
from tdcb.trials import round as tround  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("backtest")
ap.add_argument("dry")
ap.add_argument("out")
ap.add_argument("--sims", type=int, default=4000)
ap.add_argument("--n-pmet", type=int, default=250)
a = ap.parse_args()
rng = np.random.default_rng(7)
OUT = {}

# ---- p_met, from Pilot 2's real outcomes
W = a.backtest
reg = json.load(open(os.path.join(W, "round", "registry.json")))
P = {e["id"]: tround.load_forecasts(os.path.join(W, "round", e["forecasts"])) for e in reg}
key = {k["nct_id"]: k for k in json.load(open(os.path.join(W, "build", "private", "key_C.json")))}
ids = sorted(key)
names = ["ref-opus-5-5", "sonnet-5-5", "haiku-5-5", "ref-b1", "ref-b0"]
y = np.array([key[n]["met"] for n in ids], float)
SE = {m: (np.array([P[m][n]["p_met"] for n in ids]) - y) ** 2 for m in names}
N = a.n_pmet
idx = rng.integers(0, len(ids), (a.sims, N))
B = {m: SE[m][idx].mean(1) for m in names}
skill = {m: 1 - B[m] / B["ref-b0"] for m in names}
rank = np.argsort(np.stack([B[m] for m in names], 1), 1)
OUT["p_met"] = {
    "n_results": N,
    "brier": {m: [float(np.percentile(B[m], q)) for q in (5, 50, 95)] for m in names},
    "skill_vs_b0": {m: [float(np.percentile(skill[m], q)) for q in (5, 50, 95)] for m in names},
    "p_first": {m: float(np.mean(rank[:, 0] == i)) for i, m in enumerate(names)},
    "p_opus_beats_sonnet": float(np.mean(B["ref-opus-5-5"] < B["sonnet-5-5"])),
    "p_sonnet_beats_haiku": float(np.mean(B["sonnet-5-5"] < B["haiku-5-5"])),
    "p_best_model_beats_b1": float(np.mean(np.minimum.reduce([B[m] for m in names[:3]]) < B["ref-b1"])),
    "p_each_model_beats_b0": {m: float(np.mean(B[m] < B["ref-b0"])) for m in names[:4]},
    "ci95_halfwidth_brier_diff_vs_b0": {m: float(1.96 * np.std(SE[m] - SE["ref-b0"], ddof=1) / math.sqrt(N))
                                        for m in names[:4]},
}
for n_alt in (125, 350, 700):
    ia = rng.integers(0, len(ids), (a.sims, n_alt))
    Ba = {m: SE[m][ia].mean(1) for m in names}
    OUT["p_met"][f"at_{n_alt}"] = {"p_opus_beats_sonnet": float(np.mean(Ba["ref-opus-5-5"] < Ba["sonnet-5-5"])),
                                   "p_sonnet_beats_haiku": float(np.mean(Ba["sonnet-5-5"] < Ba["haiku-5-5"])),
                                   "p_best_model_beats_b1": float(np.mean(np.minimum.reduce([Ba[m] for m in names[:3]])
                                                                          < Ba["ref-b1"]))}

# ---- numbers, from Pilot 2's published values
cards = tnum.load_cards(os.path.join(W, "round", "cards.jsonl"))
ref = P["ref-opus-5-5"]
models = ["ref-opus-5-5", "sonnet-5-5", "haiku-5-5"]
rows = []
for n in ids:
    for which, f in (("control", "control_value"), ("effect", "effect_value")):
        v = tnum.num(key[n].get(f))
        c = cards[n]
        if v is None:
            continue
        log = tnum.log_scale(c, which)
        rr = tnum.parse_range(ref[n].get(which))
        if rr is None or (log and v <= 0):
            continue
        w = tnum.width(rr, log)
        sc = []
        for m in models:
            r = tnum.parse_range(P[m][n].get(which))
            sc.append(tnum.percentile_score(r, v, log) / w if r else np.nan)
        rows.append(sc)
S = np.array(rows)
S = S[~np.isnan(S).any(1)]
n_eff, n_ctl = round(N * 0.58), round(N * 0.47)
n_ans = n_eff + n_ctl
ii = rng.integers(0, len(S), (a.sims, n_ans))
M = S[ii].mean(1)
OUT["numbers"] = {"n_answers": n_ans, "score": {m: [float(np.percentile(M[:, j], q)) for q in (5, 50, 95)]
                                                 for j, m in enumerate(models)},
                  "p_opus_beats_sonnet": float(np.mean(M[:, 0] < M[:, 1])),
                  "p_sonnet_beats_haiku": float(np.mean(M[:, 1] < M[:, 2])),
                  "p_opus_beats_haiku": float(np.mean(M[:, 0] < M[:, 2]))}

# ---- operations, from the dry run's forecasts, in a consensus world
D = a.dry
ops = tops.load_rows(os.path.join(D, "stage", "round", "operations.jsonl"))
qs = {q["nct_id"]: q["questions"] for q in json.load(open(os.path.join(D, "questions.json")))}
F = {m: {} for m in ("opus", "sonnet", "haiku")}
for m in F:
    for fn in sorted(os.listdir(os.path.join(D, "out_" + m))):
        F[m].update(tround.load_forecasts(os.path.join(D, "out_" + m, fn)))
WEIGHT = {"main": 673, "equivalence": 13, "operations only": 166}
dry_ids = sorted(ops)
groups = {g: [n for n in dry_ids if qs[n] == g] for g in WEIGHT}
res = {}
for q in tops.QUESTIONS:
    pools = {}
    for g, members in groups.items():
        rows_q = []
        for n in members:
            if q not in ops[n]["questions"]:
                continue
            ps = [F[m].get(n, {}).get(q) for m in F]
            if all(isinstance(p, (int, float)) and 0 <= p <= 1 for p in ps):
                rows_q.append(ps)
        pools[g] = np.array(rows_q)
    # expected number of these questions in the full round: each group's share asking q, times its size
    n_full = {g: round(WEIGHT[g] * len(pools[g]) / max(1, len(groups[g]))) for g in WEIGHT}
    briers = {m: [] for m in F}
    briers["share"] = []
    for _ in range(min(a.sims, 2000)):
        allp, ally = [], []
        for g, arr in pools.items():
            if not len(arr):
                continue
            pick = arr[rng.integers(0, len(arr), n_full[g])]
            truth = pick.mean(1)
            allp.append(pick)
            ally.append((rng.random(len(truth)) < truth).astype(float))
        p_, y_ = np.vstack(allp), np.concatenate(ally)
        for j, m in enumerate(F):
            briers[m].append(np.mean((p_[:, j] - y_) ** 2))
        briers["share"].append(np.mean((y_.mean() - y_) ** 2))
    allarr = np.vstack([v for v in pools.values() if len(v)])
    res[q] = {"n_full_round": int(sum(n_full.values())),
              "mean_forecast": {m: float(allarr[:, j].mean()) for j, m in enumerate(F)},
              "by_group_mean": {g: ({m: float(arr[:, j].mean()) for j, m in enumerate(F)} if len(arr) else None)
                                for g, arr in pools.items()},
              "pairwise_mean_abs_diff": {f"{a_}-{b_}": float(np.mean(np.abs(allarr[:, i] - allarr[:, j])))
                                         for i, a_ in enumerate(F) for j, b_ in enumerate(F) if i < j},
              "brier_consensus_world": {m: [float(np.percentile(v, q_)) for q_ in (5, 50, 95)] for m, v in briers.items()},
              "p_rank": {f"{a_}<{b_}": float(np.mean(np.array(briers[a_]) < np.array(briers[b_])))
                         for a_ in F for b_ in F if a_ != b_}}
OUT["operations"] = res
json.dump(OUT, open(a.out, "w"), indent=1)
print(json.dumps(OUT, indent=1))
