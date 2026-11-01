"""Plan the results check for the Round 2 trials: which trials, in what order, in lists for labelling agents.

usage: python3 -I plan_label.py <merged.jsonl> <out dir> --records <records.jsonl> [...] [--per-list 10] [--cap 10] [--fetch-cap 45]
                                [--today 2026-10-25] [--only company|other|all] [--skip done.txt] [--hints hints.jsonl]
Takes the finished questions (default keep or review, primary completion passed) and the stopped trials (history),
company-run first, oldest primary completion first. Each list line carries what the labeller needs: title, acronym,
sponsor, phase, interventions, conditions, the comparison, the registered primary completion date and status, and the
primary outcomes as registered in the record pulled on 25 October 2026 (the packet). Writes <out dir>/L_<nn>.md,
<out dir>/instructions.md (label_instructions_r2.md with the search and fetch caps and the date filled in) and <out dir>/lists.json.
"""
import argparse
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("merged")
ap.add_argument("out")
ap.add_argument("--records", nargs="+", required=True)
ap.add_argument("--per-list", type=int, default=10)
ap.add_argument("--cap", type=int, default=10)
ap.add_argument("--fetch-cap", type=int, default=45)
ap.add_argument("--today", default="2026-10-25")
ap.add_argument("--only", choices=["company", "other", "all"], default="all")
ap.add_argument("--skip")
ap.add_argument("--hints")
a = ap.parse_args()
rows = [json.loads(line) for line in open(a.merged)]
recs = {}
for p in a.records:
    for line in open(p):
        if line.strip():
            r = json.loads(line)
            recs[r["nct_id"]] = r
skip = {line.split()[0] for line in open(a.skip) if line.strip()} if a.skip else set()
hints = {}
if a.hints:
    for line in open(a.hints):
        if line.strip():
            h = json.loads(line)
            hints[h["nct_id"]] = h["hint"]


def wanted(r):
    if r["nct_id"] in skip:
        return False
    company = r["sponsor_class"] == "INDUSTRY"
    if a.only != "all" and company != (a.only == "company"):
        return False
    return (r["default"] in ("keep", "review") and r["past"]) or r["default"] == "stopped"


todo = sorted((r for r in rows if wanted(r)),
              key=lambda r: (r["sponsor_class"] != "INDUSTRY", r["primary_completion_date"], r["nct_id"]))


def cut(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n] + " [...]"


def line(r):
    rec = recs.get(r["nct_id"], {})
    prim = rec.get("primary_outcomes") or []
    outcomes = " ;; ".join(f"{cut(p.get('measure'), 200)} (time frame: {cut(p.get('time_frame'), 80)})" for p in prim[:6])
    if len(prim) > 6:
        outcomes += f" ;; and {len(prim) - 6} more"
    return (f"- {r['nct_id']} | {cut(r['title'], 250)} | acronym: {rec.get('acronym') or '-'} | sponsor: {r['sponsor']} | "
            f"phase: {'/'.join(r['phase'])} | interventions: {'; '.join(r.get('interventions') or [])} | "
            f"conditions: {'; '.join(r.get('conditions') or [])} | compared with: {r['reader'].get('comparison')} | "
            f"primary completion (registry): {r['primary_completion_date']} | status: {r['status'].lower()} | "
            f"primary outcomes: {outcomes}" + (f" | {hints[r['nct_id']]}" if r["nct_id"] in hints else ""))


os.makedirs(a.out, exist_ok=True)
lists = {}
for i in range(0, len(todo), a.per_list):
    name = f"L_{i // a.per_list:03d}"
    chunk = todo[i:i + a.per_list]
    lists[name] = [r["nct_id"] for r in chunk]
    with open(os.path.join(a.out, name + ".md"), "w") as fh:
        fh.write("\n".join(line(r) for r in chunk) + "\n")
here = os.path.dirname(os.path.abspath(__file__))
ins = open(os.path.join(here, "label_instructions_r2.md")).read().replace("{cap}", str(a.cap)).replace("{fetch_cap}", str(a.fetch_cap)).replace("{today}", a.today)
open(os.path.join(a.out, "instructions.md"), "w").write(ins)
json.dump(lists, open(os.path.join(a.out, "lists.json"), "w"), indent=0)
n_company = sum(r["sponsor_class"] == "INDUSTRY" for r in todo)
print(f"{len(todo)} trials ({n_company} company-run, {len(todo) - n_company} other) in {len(lists)} lists of up to "
      f"{a.per_list}; stopped: {sum(r['default'] == 'stopped' for r in todo)}")
