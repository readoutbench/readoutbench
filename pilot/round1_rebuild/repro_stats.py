"""Run-to-run difference in p_met on the round's prompt: each model's first run against its second run of the same
batches (r1m/repro), and each pair of models against each other, on the trials with p_met.
usage: python3 -I repro_stats.py <runs dir>
(<runs dir> holds <model>_forecasts.jsonl, batches/ and repro/: pick.json and out_<model>/ with the second runs.)
Prints, per comparison: trials, mean |difference|, and for the rules' check (40 trials, drawn with replacement, 20000
draws, seed 1; reproduced at a mean |difference| of at most 0.08) the share of draws above 0.08 and the 99th
percentile of the 40-trial mean; the old check (20 trials at 0.06) is shown next to it. Writes repro/repro_stats.json."""
import json
import random
import statistics as st
import sys

S = sys.argv[1]
pick = json.load(open(S + "/repro/pick.json"))["batches"]
lists = json.load(open(S + "/batches/lists.json"))
ids = [n for b in pick for n in lists[b]]


def load(path):
    return {json.loads(x)["nct_id"]: json.loads(x) for x in open(path) if x.strip()}


first = {m: load(f"{S}/{m}_forecasts.jsonl") for m in ("opus", "sonnet", "haiku")}
second = {}
for m in first:
    d = {}
    for b in pick:
        try:
            d.update(load(f"{S}/repro/out_{m}/{b}.jsonl"))
        except FileNotFoundError:
            pass
    second[m] = d


def compare(a, b, label, draws=20000):
    common = [n for n in ids if isinstance(a.get(n, {}).get("p_met"), (int, float))
              and isinstance(b.get(n, {}).get("p_met"), (int, float))]
    diffs = [abs(a[n]["p_met"] - b[n]["p_met"]) for n in common]
    if len(diffs) < 20:
        print(f"{label}: {len(diffs)} trials, too few")
        return None
    out = {"trials": len(diffs), "mean_abs_diff": round(st.mean(diffs), 4), "median_abs_diff": round(st.median(diffs), 4)}
    for k, thr in ((40, 0.08), (20, 0.06)):
        rng = random.Random(1)
        means = sorted(st.mean(rng.choices(diffs, k=k)) for _ in range(draws))
        out[f"share_{k}_trial_draws_above_{thr}"] = round(sum(x > thr for x in means) / draws, 4)
        out[f"p99_of_{k}_trial_mean"] = round(means[int(0.99 * draws)], 4)
    print(label, out)
    return out


res = {"batches": pick, "same_model": {}, "between_models": {}}
for m in first:
    res["same_model"][m] = compare(first[m], second[m], f"{m} run 1 vs run 2")
for a, b in (("opus", "sonnet"), ("opus", "haiku"), ("sonnet", "haiku")):
    res["between_models"][f"{a}-{b}"] = compare(first[a], first[b], f"{a} vs {b} (first runs)")
json.dump(res, open(S + "/repro/repro_stats.json", "w"), indent=1)
