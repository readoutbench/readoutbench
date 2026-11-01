"""Check the output of a results-check pass (final_check_deep_instructions.md) before it is used.

usage: python3 -I check_results_rows.py <lists dir> <outputs dir> [--min-queries 2] [--min-opened 1]
                                       [--records records.jsonl] [--checked-from 2026-10-29] [--why]
<lists dir> holds lists.json (list name -> NCT ids) as plan_leak.py writes it; <outputs dir> holds L_NNN.jsonl.
Prints, per list, whether its file is there and complete, then every trial in one of four groups:
  finding   reported "yes" or "stopped_without_result", or a stop announced: the trial comes out of the round
  clean     passes the bar of results_gate.py (the same one launch.py applies)
  shallow   checked, but not to that bar (counts as not checked)
  missing   no row, "unchecked", or a malformed row
Exit 0 when every trial is a finding or clean, 1 otherwise. launch.py applies the same bar.
"""
import argparse
import json
import os
import sys

KEYS = {"nct_id", "reported", "first_public_date", "clear_date", "met", "endpoint", "result", "interim", "sources",
        "quote", "stop_announced", "stop_date", "stop_reason", "confidence", "queries", "pages_checked", "notes",
        "checked_on"}
ap = argparse.ArgumentParser()
ap.add_argument("lists")
ap.add_argument("outputs")
ap.add_argument("--min-queries", type=int, default=2)
ap.add_argument("--min-opened", type=int, default=1)
ap.add_argument("--records", help="the round's records.jsonl: enables the language rule for East Asian trials")
ap.add_argument("--checked-from", help="YYYY-MM-DD: rows dated earlier are not clean")
ap.add_argument("--signed-off", help="JSONL of the organiser's sign-offs of flagged rows")
ap.add_argument("--why", action="store_true", help="print why each shallow row is shallow")
a = ap.parse_args()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from results_gate import classify, load_signed_off  # noqa: E402
lists = json.load(open(os.path.join(a.lists, "lists.json")))
recs = {}
if a.records:
    recs = {json.loads(x)["nct_id"]: json.loads(x) for x in open(a.records, encoding="utf-8") if x.strip()}
group = {"finding": [], "clean": [], "shallow": [], "missing": []}
for name, ids in sorted(lists.items()):
    path = os.path.join(a.outputs, name + ".jsonl")
    rows, bad = [], 0
    if os.path.exists(path):
        for x in open(path, encoding="utf-8"):
            if not x.strip():
                continue
            try:
                r = json.loads(x)
                assert isinstance(r, dict) and KEYS <= set(r) and r["nct_id"] in ids
                rows.append(r)
            except Exception:
                bad += 1
    print(f"{name}: {'no file' if not os.path.exists(path) else f'{len(rows)} of {len(ids)} rows'}"
          + (f", {bad} malformed lines" if bad else ""))
    for n, (k, why) in classify([rows], recs, ids, min_queries=a.min_queries, min_opened=a.min_opened,
                                checked_from=a.checked_from,
                                signed_off=load_signed_off(a.signed_off) if a.signed_off else {}).items():
        group[k].append(n)
        if k == "shallow" and a.why:
            print("  shallow", n, why)
print()
for k, v in group.items():
    print(f"{k}: {len(v)}" + (f"  {' '.join(v)}" if k == "finding" and v else ""))
sys.exit(0 if not group["shallow"] and not group["missing"] else 1)
