"""The 31 October registry status check: which trials of the round have stopped or posted results.

usage: python3 -I status_drops.py <raw dir> <manifest.json> <out drops.jsonl>
<raw dir> holds one ClinicalTrials.gov API v2 record per trial, as fetch_raw.py saves them (<NCT id>.json).
Writes one drop line {"nct_id", "step", "status", "has_results"} for every trial of the round whose overall status is
terminated, withdrawn or suspended, or that has results posted; prints the count and any trial with no record (those
stop the launch until pulled). Append the lines to launch.py's drops file and run launch.py again.
"""
import json
import os
import sys

STOPPED = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}
STEP = "registry status check (31 October): stopped or results posted"
raw, manifest, out = sys.argv[1:4]
ids = json.load(open(manifest))["trials"]
drops, missing = [], []
for n in ids:
    p = os.path.join(raw, n + ".json")
    if not os.path.exists(p):
        missing.append(n)
        continue
    d = json.load(open(p, encoding="utf-8"))
    nid = (((d.get("protocolSection") or {}).get("identificationModule") or {}).get("nctId") or "").upper()
    if nid != n:
        sys.exit(f"{p}: the record is {nid or 'unnamed'}, not {n}")
    status = (((d.get("protocolSection") or {}).get("statusModule") or {}).get("overallStatus") or "").upper()
    has = bool(d.get("hasResults"))
    if status in STOPPED or has:
        drops.append({"nct_id": n, "step": STEP, "status": status, "has_results": has})
if missing:
    sys.exit(f"{len(missing)} trials have no record (pull them first; nothing written): {' '.join(missing)}")
with open(out, "w", encoding="utf-8") as fh:
    fh.write("".join(json.dumps(x) + "\n" for x in drops))
print(f"{len(ids)} trials: {len(drops)} to drop")
