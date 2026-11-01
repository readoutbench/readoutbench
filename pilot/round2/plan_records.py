"""Plan full-record look-ups (registry tool get_trial_details) for a random sample of candidates, or all of them.

usage: python3 -I plan_records.py <candidates.jsonl> <out dir> <sample size | all> [batch size] [seed] [exclude.json]
                                  [--sponsors industry|other|all]
Takes the candidates of the chosen lead sponsor class (default: company-run), without phase 1/2 trials, and
samples them proportionally by area with at least 3 per area, or takes all of them ("all"), leaving out the
NCT numbers listed in exclude.json. Writes <out dir>/sample.json and <out dir>/tasks/R_<nn>.md.
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from areas import area  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("candidates")
ap.add_argument("out")
ap.add_argument("n")
ap.add_argument("size", nargs="?", type=int, default=25)
ap.add_argument("seed", nargs="?", type=int, default=1025)
ap.add_argument("exclude", nargs="?")
ap.add_argument("--sponsors", choices=["industry", "other", "all"], default="industry")
a = ap.parse_args()
exclude = set(json.load(open(a.exclude))) if a.exclude else set()
rows = [json.loads(line) for line in open(a.candidates)]


def sponsor_ok(r):
    return a.sponsors == "all" or (r["sponsor_class"] == "INDUSTRY") == (a.sponsors == "industry")


pool = [r for r in rows if sponsor_ok(r) and tuple(r.get("phase") or []) != ("PHASE1", "PHASE2")
        and r["nct_id"] not in exclude]
by = {}
for r in sorted(pool, key=lambda r: r["nct_id"]):
    by.setdefault(area(r), []).append(r)
rng = random.Random(a.seed)
sample = []
for x in sorted(by):
    if a.n == "all":
        sample += [r["nct_id"] for r in by[x]]
        continue
    k = max(3, round(int(a.n) * len(by[x]) / len(pool)))
    sample += [r["nct_id"] for r in rng.sample(by[x], min(k, len(by[x])))]
rng.shuffle(sample)
os.makedirs(os.path.join(a.out, "tasks"), exist_ok=True)
json.dump(sample, open(os.path.join(a.out, "sample.json"), "w"), indent=0)
for i in range(0, len(sample), a.size):
    lines = ["# Registry record look-ups", "",
             "Use only the tool `mcp__Clinical_Trials__get_trial_details` (load it with ToolSearch first if it is not loaded).",
             "For each NCT number below, in order, call it once with nct_id set to that number.",
             "A result too large to show is saved to a file automatically; that is expected. Do not open or read that file",
             "and do not retry: just go on to the next number. Do not summarize, retype or save the results.",
             "When all calls are made, reply with the single word: done", ""] + sample[i:i + a.size]
    open(os.path.join(a.out, "tasks", f"R_{i // a.size:02d}.md"), "w").write("\n".join(lines) + "\n")
print(len(sample), "trials in", (len(sample) + a.size - 1) // a.size, "tasks")
