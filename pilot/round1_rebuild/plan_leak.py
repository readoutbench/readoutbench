"""Plan the results check of every trial of the round (leak_check_instructions.md): lists for checking agents.

usage: python3 -I plan_leak.py <questions.jsonl or ids.txt> <merged.jsonl> <out dir> --records <records.jsonl> [...]
                               [--hints hints.jsonl] [--only ids.txt] [--per-list 12] [--cap 12] [--fetch-cap 45]
                               [--today 2026-10-29] [--instructions final_check_instructions.md]
Every trial is checked, not only those past their primary completion date: a trial can report its primary result at
an interim analysis long before the date it registered. Oldest start first (the likeliest to have reported early).
Each list line carries the trial as registered (title, acronym, sponsor, phase, interventions, conditions, the
comparison, start, primary completion and status, primary outcomes) and its PubMed note when one is given. Writes
<out dir>/L_<nnn>.md, <out dir>/instructions.md (with the caps and the date filled in) and <out dir>/lists.json.
"""
import argparse
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("trials")
ap.add_argument("merged")
ap.add_argument("out")
ap.add_argument("--records", nargs="+", required=True)
ap.add_argument("--hints")
ap.add_argument("--only")
ap.add_argument("--per-list", type=int, default=12)
ap.add_argument("--cap", type=int, default=12)
ap.add_argument("--fetch-cap", type=int, default=45)
ap.add_argument("--today", default="2026-10-29")
ap.add_argument("--instructions", default="leak_check_instructions.md", help="next to this script")
a = ap.parse_args()


def ids_of(path):
    if path.endswith(".jsonl"):
        return [json.loads(line)["nct_id"] for line in open(path) if line.strip()]
    return [line.split()[0] for line in open(path) if line.strip()]


ids = ids_of(a.trials)
if a.only:
    keep = set(ids_of(a.only))
    ids = [n for n in ids if n in keep]
merged = {}
for line in open(a.merged):
    if line.strip():
        r = json.loads(line)
        merged[r["nct_id"]] = r
recs = {}
for p in a.records:                      # later files win
    for line in open(p):
        if line.strip():
            r = json.loads(line)
            recs[r["nct_id"]] = r
hints = {}
if a.hints:
    for line in open(a.hints):
        if line.strip():
            h = json.loads(line)
            hints[h["nct_id"]] = h["hint"]
missing = [n for n in ids if n not in recs]
if missing:
    raise SystemExit(f"{len(missing)} trials have no record, e.g. {missing[:3]}")
ids.sort(key=lambda n: (recs[n].get("start_date") or "9999", n))


def cut(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n] + " [...]"


def line(n):
    rec, m = recs[n], merged.get(n, {})
    reader = m.get("reader") or {}
    prim = rec.get("primary_outcomes") or []
    outcomes = " ;; ".join(f"{cut(p.get('measure'), 200)} (time frame: {cut(p.get('time_frame'), 80)})" for p in prim[:6])
    if len(prim) > 6:
        outcomes += f" ;; and {len(prim) - 6} more"
    phase = "/".join(rec.get("phase") or []) or "not stated"
    return (f"- {n} | {cut(rec.get('title') or rec.get('brief_title'), 250)} | acronym: {rec.get('acronym') or '-'} | "
            f"sponsor: {rec.get('sponsor')} | phase: {phase} | interventions: {'; '.join(rec.get('interventions') or [])} | "
            f"conditions: {'; '.join(rec.get('conditions') or [])} | compared with: {reader.get('comparison') or 'see title'} | "
            f"start: {rec.get('start_date') or 'not stated'} | primary completion (registry): "
            f"{rec.get('primary_completion_date')} | status: {str(rec.get('status') or '').lower()} | "
            f"primary outcomes: {outcomes}" + (f" | {hints[n]}" if n in hints else ""))


os.makedirs(a.out, exist_ok=True)
lists = {}
for i in range(0, len(ids), a.per_list):
    name = f"L_{i // a.per_list:03d}"
    lists[name] = ids[i:i + a.per_list]
    with open(os.path.join(a.out, name + ".md"), "w") as fh:
        fh.write("\n".join(line(n) for n in lists[name]) + "\n")
here = os.path.dirname(os.path.abspath(__file__))
ins = (open(os.path.join(here, a.instructions)).read().replace("{cap}", str(a.cap))
       .replace("{fetch_cap}", str(a.fetch_cap)).replace("{today}", a.today))
open(os.path.join(a.out, "instructions.md"), "w").write(ins)
json.dump(lists, open(os.path.join(a.out, "lists.json"), "w"), indent=0)
print(f"{len(ids)} trials in {len(lists)} lists of up to {a.per_list}; {sum(n in hints for n in ids)} with a PubMed note")
