"""Round 1: how the tier test behaves at the round's size, by simulation (the rules' table of the lead needed).

usage: python3 -I sim_tiers.py <sisters.json> <out.json> [--reps 1000] [--seed 7] [--registry-sd 0.9] [--shared 0.5]
Each simulated round draws trials in whole sister groups with the round's group sizes (sisters.json). A trial's true
chance of success has a group effect, so sister trials succeed or fail together; the registry model's and the
entry's forecasts err around it, with errors shared within a group too. For each size (100, 200, 400 scored trials and every
trial with p_met in the sisters file) it reports, over `reps` rounds:
- the false "clearly better" rate when the entry's true Brier score is exactly 0.005 below the registry model's (the
  margin), and the false "clearly worse" rate when it is exactly 0.005 above; both should be about 2.5%;
- the same "clearly better" rate for a centred bootstrap tail, for comparison with the normal approximation;
- the standard deviation of the paired Brier difference, and from it the lead needed for "clearly better" about half
  the time (0.005 + 1.96 sd) and 80% of the time (0.005 + 2.80 sd);
- the same standard deviation for an entry built on the registry model's own forecasts (small changes to them),
  which varies far less from it and so needs a smaller lead.
The error sizes are set, not fitted: the registry model's forecast error has a standard deviation of `--registry-sd`
on the logit scale, a share `--shared` of every forecast error is common to a sister group, and the entry's error is
whatever puts it exactly at the margin. The rules show the default and one other setting.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import round as tr  # noqa: E402

GAP = tr.MIN_GAP
sig = lambda x: 1 / (1 + np.exp(-x))  # noqa: E731


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sisters")
    ap.add_argument("out")
    ap.add_argument("--reps", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--registry-sd", type=float, default=0.9)
    ap.add_argument("--shared", type=float, default=0.5)
    a = ap.parse_args()
    sizes = np.array([len(v) for v in json.load(open(a.sisters))["groups"].values()])
    SIZES = (100, 200, 400, int(sizes.sum()))           # the last: every trial with p_met in this sisters file
    rng = np.random.default_rng(a.seed)

    def draw(n, s_e, s_b=a.registry_sd, rho=a.shared, near=None):
        sz = rng.choice(sizes, size=n)
        g = np.repeat(np.arange(n), sz)[:n]
        G = g.max() + 1
        eta = 0.85 + rng.normal(0, 0.6, G)[g] + rng.normal(0, 0.9, n)

        def err(s):
            return s * (np.sqrt(rho) * rng.normal(0, 1, G)[g] + np.sqrt(1 - rho) * rng.normal(0, 1, n))
        eb = err(s_b)
        ee = eb + rng.normal(0, near, n) if near is not None else err(s_e)
        return g, sig(eta), sig(eta + eb), sig(eta + ee)

    def expected(s_e, n=200000):
        g, pi, pb, pe = draw(n, s_e)
        return float(np.mean((pe - pi) ** 2 - (pb - pi) ** 2))

    def solve(target):                                  # the entry's error that puts it exactly at the margin
        lo, hi = 0.0, 2.0
        for _ in range(22):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if expected(mid) < target else (lo, mid)
        return (lo + hi) / 2
    s_better, s_worse = solve(-GAP), solve(GAP)
    out = {"settings": {"reps": a.reps, "seed": a.seed, "gap": GAP, "registry_error_sd_logit": a.registry_sd,
                        "within_group_error_share": a.shared, "entry_error_sd_at_minus_gap": s_better,
                        "entry_error_sd_at_plus_gap": s_worse, "bootstrap_resamples": 1000}, "by_size": {}}
    for n in SIZES:
        fb = fw = fc = 0
        sds, sds_near = [], []
        for rep in range(a.reps):
            for s_e, which in ((s_better, "better"), (s_worse, "worse")):
                g, pi, pb, pe = draw(n, s_e)
                y = (rng.uniform(size=n) < pi).astype(float)
                ids = [f"t{i}" for i in range(n)]
                clusters = {f"t{i}": f"g{gi}" for i, gi in enumerate(g)}
                se = {"e": (pe - y) ** 2, "b": (pb - y) ** 2}
                b = tr._cluster_boot(se, ids, clusters, 1000, int(rng.integers(1e9)))
                d = float(se["e"].mean() - se["b"].mean())
                db = b["e"] - b["b"]
                sd = float(db.std(ddof=1))
                pbet, pwor = tr._two_way(d, sd, GAP)
                if which == "better":
                    sds.append(sd)
                    fb += min(1, 2 * min(pbet, pwor)) < tr.ALPHA and pbet < pwor
                    fc += np.mean((db - d) <= (d + GAP)) < tr.ALPHA / 2
                else:
                    fw += min(1, 2 * min(pbet, pwor)) < tr.ALPHA and pwor < pbet
            if rep < 200:                               # an entry built on the registry model's forecasts
                g, pi, pb, pe = draw(n, None, near=0.25)
                y = (rng.uniform(size=n) < pi).astype(float)
                ids = [f"t{i}" for i in range(n)]
                clusters = {f"t{i}": f"g{gi}" for i, gi in enumerate(g)}
                b = tr._cluster_boot({"e": (pe - y) ** 2, "b": (pb - y) ** 2}, ids, clusters, 1000,
                                     int(rng.integers(1e9)))
                sds_near.append(float((b["e"] - b["b"]).std(ddof=1)))
        sd, sdn = float(np.mean(sds)), float(np.mean(sds_near))
        out["by_size"][n] = {
            "false_clearly_better_at_margin": float(fb / a.reps), "false_clearly_worse_at_margin": float(fw / a.reps),
            "false_clearly_better_centred_bootstrap": float(fc / a.reps), "mc_standard_error": float(np.sqrt(0.025 * 0.975 / a.reps)),
            "sd": sd, "lead_needed_half_the_time": GAP + 1.959964 * sd, "lead_needed_80pct": GAP + 2.801585 * sd,
            "sd_entry_built_on_registry_model": sdn, "lead_needed_half_the_time_built_on_it": GAP + 1.959964 * sdn,
            "lead_needed_80pct_built_on_it": GAP + 2.801585 * sdn}
        print(n, {k: round(v, 4) for k, v in out["by_size"][n].items()}, flush=True)
    json.dump(out, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
