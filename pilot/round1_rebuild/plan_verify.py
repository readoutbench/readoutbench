"""Plan the second check of every reported result or stop the results check found (leak_verify_instructions.md).

usage: python3 -I plan_verify.py <out dir> --checks <web check outputs ...> [--pubmed judged.jsonl] --records <...>
                                 [--merged merged.jsonl] [--done verify outputs ...] [--per-list 8] [--cap 4]
                                 [--fetch-cap 30] [--today 2026-10-29]
Takes every trial a web check marked reported ("yes" or "stopped_without_result") or with a stop announced, and every
trial whose PubMed judge found the primary result, and writes lists for verifying agents with the trial as registered
and the first finding (what, date, sources, quote). Trials already verified (--done) are left out. Also writes
<out dir>/recheck.txt: the trials whose web check ran without web search (its notes say the search budget had run
out), to check again.
"""
import argparse
import glob
import json
import os
import re

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--checks", nargs="+", required=True)
ap.add_argument("--pubmed")
ap.add_argument("--records", nargs="+", required=True)
ap.add_argument("--merged")
ap.add_argument("--done", nargs="*", default=[])
ap.add_argument("--per-list", type=int, default=8)
ap.add_argument("--cap", type=int, default=4)
ap.add_argument("--fetch-cap", type=int, default=30)
ap.add_argument("--today", default="2026-10-29")
a = ap.parse_args()
NO_SEARCH = re.compile(r"search budget|search was unavailable|search is unavailable|no web ?search|without (any )?web "
                       r"search|searches? (were|was) (not|un)available|budget (is |was )?(exhausted|used up)", re.I)
recs = {}
for p in a.records:
    for line in open(p):
        if line.strip():
            r = json.loads(line)
            recs[r["nct_id"]] = r
merged = {}
if a.merged:
    for line in open(a.merged):
        if line.strip():
            r = json.loads(line)
            merged[r["nct_id"]] = r
finds, recheck = {}, set()
for pat in a.checks:
    for p in sorted(glob.glob(pat)):
        for line in open(p):
            if not line.strip():
                continue
            r = json.loads(line)
            n = r["nct_id"]
            if NO_SEARCH.search(json.dumps(r.get("notes") or "")) and r.get("reported") == "no":
                recheck.add(n)
            if r.get("reported") in ("yes", "stopped_without_result") or r.get("stop_announced") == "yes":
                finds.setdefault(n, []).append(
                    f"web check: reported={r.get('reported')}, met={r.get('met')}, first public {r.get('first_public_date')}, "
                    f"interim={r.get('interim')}; stop announced={r.get('stop_announced')} ({r.get('stop_date')}: "
                    f"{r.get('stop_reason')}); sources: {'; '.join((r.get('sources') or [])[:4])}; quote: {r.get('quote')}; "
                    f"notes: {str(r.get('notes') or '')[:400]}")
if a.pubmed:
    for line in open(a.pubmed):
        if line.strip():
            r = json.loads(line)
            if r.get("primary_result_found"):
                finds.setdefault(r["nct_id"], []).append(
                    f"PubMed: PMID {r.get('pmid')} ({r.get('journal')}, {r.get('pub_date')}), doi {r.get('doi')}, read as "
                    f"met={r.get('met')}: {r.get('endpoint')}; {r.get('result')}; quote: {r.get('quote')}")
done = set()
for pat in a.done:
    for p in glob.glob(pat):
        done |= {json.loads(x)["nct_id"] for x in open(p) if x.strip()}
todo = sorted(n for n in finds if n not in done)


def cut(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n] + " [...]"


def line(n):
    rec = recs[n]
    prim = rec.get("primary_outcomes") or []
    outcomes = " ;; ".join(f"{cut(p.get('measure'), 200)} (time frame: {cut(p.get('time_frame'), 80)})" for p in prim[:4])
    comp = ((merged.get(n) or {}).get("reader") or {}).get("comparison") or "see title"
    return (f"- {n} | {cut(rec.get('title'), 250)} | acronym: {rec.get('acronym') or '-'} | sponsor: {rec.get('sponsor')} | "
            f"phase: {'/'.join(rec.get('phase') or [])} | interventions: {'; '.join(rec.get('interventions') or [])} | "
            f"conditions: {'; '.join(rec.get('conditions') or [])} | compared with: {comp} | start: {rec.get('start_date')} "
            f"| primary completion (registry): {rec.get('primary_completion_date')} | primary outcomes: {outcomes}\n"
            + "".join(f"  FIRST FINDING: {cut(f, 1500)}\n" for f in finds[n]))


os.makedirs(a.out, exist_ok=True)
lists = {}
for i in range(0, len(todo), a.per_list):
    name = f"V_{i // a.per_list:03d}"
    lists[name] = todo[i:i + a.per_list]
    open(os.path.join(a.out, name + ".md"), "w").write("".join(line(n) for n in lists[name]))
here = os.path.dirname(os.path.abspath(__file__))
ins = (open(os.path.join(here, "leak_verify_instructions.md")).read().replace("{cap}", str(a.cap))
       .replace("{fetch_cap}", str(a.fetch_cap)).replace("{today}", a.today))
open(os.path.join(a.out, "instructions.md"), "w").write(ins)
json.dump(lists, open(os.path.join(a.out, "lists.json"), "w"), indent=0)
open(os.path.join(a.out, "recheck.txt"), "w").write("".join(n + "\n" for n in sorted(recheck)))
print(f"{len(finds)} trials with a finding, {len(todo)} to verify in {len(lists)} lists; {len(recheck)} checked without "
      "web search, to check again")
