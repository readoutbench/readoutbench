"""Pilot 2: write batches of trial packets (registry record, no result), optionally with each trial's question card.

usage: python3 -I make_batches.py <set.json> <out dir> --records <records.jsonl> [...] --size 12 --prefix F
                                  [--cards cards.jsonl] [--snapshot 2026-10-25]
Packets are rendered by tdcb.trials.packets (no overall status, results flag or link), with a header that does not
assume phase 3 and without Round 1's hazard-ratio line. Writes <out dir>/<prefix>_<nn>.md and <out dir>/batches.json.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials.packets import leak_problems, render  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("set")
ap.add_argument("out")
ap.add_argument("--records", nargs="+", required=True)
ap.add_argument("--size", type=int, default=12)
ap.add_argument("--prefix", default="F")
ap.add_argument("--cards")
ap.add_argument("--snapshot", default="2026-10-25")
a = ap.parse_args()
ids = [r["nct_id"] for r in json.load(open(a.set))]
recs = {}
for p in a.records:
    for line in open(p):
        if line.strip():
            r = json.loads(line)
            recs[r["nct_id"]] = r
cards = {}
if a.cards:
    for line in open(a.cards):
        if line.strip():
            c = json.loads(line)
            cards[c["nct_id"]] = c
CARD_KEYS = ["endpoint", "kind", "effect_measure", "better", "control_measure", "unit", "experimental_arm", "control_arm",
             "n_experimental", "n_control", "design", "margin", "alpha_two_sided"]


def packet(n):
    t = render(recs[n], a.snapshot)
    t = t.replace("Forecast the result of this randomized phase 3 trial.", "Forecast the result of this randomized trial.")
    t = "\n".join(line for line in t.splitlines() if not line.startswith("- First primary endpoint:")) + "\n"
    if a.cards:
        c = cards[n]
        t += "\n## Question card\n" + "\n".join(f"- {k}: {c.get(k)}" for k in CARD_KEYS) + "\n"
    return t


os.makedirs(a.out, exist_ok=True)
batches, leaks = {}, []
for i in range(0, len(ids), a.size):
    name = f"{a.prefix}_{i // a.size:02d}"
    chunk = ids[i:i + a.size]
    texts = [packet(n) for n in chunk]
    for n, t in zip(chunk, texts):
        if leak_problems(t):
            leaks.append((n, leak_problems(t)))
    batches[name] = chunk
    open(os.path.join(a.out, name + ".md"), "w").write(f"# {len(chunk)} trials\n\n" + "\n".join(texts))
json.dump(batches, open(os.path.join(a.out, "batches.json"), "w"), indent=0)
print(len(ids), "trials in", len(batches), "batches; leak phrases:", leaks or "none")
