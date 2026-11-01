"""Pilot 3: draw the dry-run sample from the Round 1 trial list and write batches from a staged round's packets.

usage: python3 -I make_sample.py sample <questions.json> <out questions.json> [--main 70] [--ops 56] [--seed 3]
       python3 -I make_sample.py batches <round dir> <questions.json> <out dir> [--size 14]
sample: every equivalence trial, and seeded random draws of main and operations-only trials.
batches: one file per batch of packets (main, equivalence and operations-only trials in separate batches), named
<kind>_<nn>.md, with batches.json listing the trials of each batch.
"""
import argparse
import json
import os
import random

ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["sample", "batches"])
ap.add_argument("a")
ap.add_argument("b")
ap.add_argument("c", nargs="?")
ap.add_argument("--main", type=int, default=70)
ap.add_argument("--ops", type=int, default=56)
ap.add_argument("--seed", type=int, default=3)
ap.add_argument("--size", type=int, default=14)
x = ap.parse_args()
if x.cmd == "sample":
    qs = json.load(open(x.a))
    rng = random.Random(x.seed)
    by = {k: [q for q in qs if q["questions"] == k] for k in ("main", "equivalence", "operations only")}
    pick = rng.sample(by["main"], x.main) + by["equivalence"] + rng.sample(by["operations only"], x.ops)
    pick.sort(key=lambda q: (q["primary_completion_date"], q["nct_id"]))
    json.dump(pick, open(x.b, "w"), indent=0)
    print(len(pick), {k: sum(q["questions"] == k for q in pick) for k in by})
else:
    rd, qpath, out = x.a, x.b, x.c
    os.makedirs(out, exist_ok=True)
    qs = json.load(open(qpath))
    short = {"main": "M", "equivalence": "E", "operations only": "O"}
    batches = {}
    for kind, s in short.items():
        ids = [q["nct_id"] for q in qs if q["questions"] == kind]
        for i in range(0, len(ids), x.size):
            name = f"{s}_{i // x.size:02d}"
            part = ids[i:i + x.size]
            with open(os.path.join(out, name + ".md"), "w") as fh:
                fh.write("\n\n---\n\n".join(open(os.path.join(rd, "packets", n + ".md")).read().strip() for n in part) + "\n")
            batches[name] = part
    json.dump(batches, open(os.path.join(out, "batches.json"), "w"), indent=1)
    print({k: len(v) for k, v in batches.items()})
