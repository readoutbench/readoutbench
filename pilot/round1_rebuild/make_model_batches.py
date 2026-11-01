"""Batches of packets for the organiser's Models board runs (Opus, Sonnet and Haiku), and their prompt.

usage: python3 -I make_model_batches.py <round dir> <out dir> [--per 10]
Writes <out dir>/B_<nnn>.md, each the packets of up to --per trials in the round's order, exactly as published (the
"packet" field of questions.jsonl), and <out dir>/prompt.txt: the one-line prompt each run agent gets, with the
round's instructions file (forecast_instructions.md, unchanged) and its batch. The runs follow the Models board's
rules: one model, the round's instructions and the packets only, no web and no other tools that bring in
information; their transcripts are kept and checked for any web search or fetch (check_model_runs.py).
"""
import argparse
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("round_dir")
ap.add_argument("out")
ap.add_argument("--per", type=int, default=10)
a = ap.parse_args()
qs = [json.loads(line) for line in open(os.path.join(a.round_dir, "questions.jsonl")) if line.strip()]
os.makedirs(a.out, exist_ok=True)
lists = {}
for i in range(0, len(qs), a.per):
    name = f"B_{i // a.per:03d}"
    chunk = qs[i:i + a.per]
    lists[name] = [q["nct_id"] for q in chunk]
    with open(os.path.join(a.out, name + ".md"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(q["packet"].rstrip() for q in chunk) + "\n")
json.dump(lists, open(os.path.join(a.out, "lists.json"), "w"), indent=0)
ins = os.path.abspath(os.path.join(a.round_dir, "forecast_instructions.md"))
prompt = (f"Read the instructions in {ins} and follow them exactly. The trials are in {{batch}} (read all of it, in "
          f"parts if needed). Write your answers to {{out}}. Use only the Read tool, to read these two files, and the "
          "Write tool, to write that one file: no web search, no web fetch, no other tool and no other file.")
open(os.path.join(a.out, "prompt.txt"), "w").write(prompt + "\n")
print(len(qs), "trials in", len(lists), "batches of up to", a.per)
