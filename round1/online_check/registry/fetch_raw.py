"""Save each trial's ClinicalTrials.gov record exactly as the official API v2 returns it (date types included).

usage: python3 fetch_raw.py round_ids.txt <out dir>
Writes <out dir>/<NCT id>.json, one file per trial, and skips files already there (so it can be rerun after a
failure). Needs Python 3.8+ and a network that reaches clinicaltrials.gov. Standard library only.
"""
import json
import os
import sys
import time
import urllib.request

ids = [x.split()[0] for x in open(sys.argv[1]) if x.strip()]
out = sys.argv[2]
os.makedirs(out, exist_ok=True)
for i, n in enumerate(ids, 1):
    path = os.path.join(out, n + ".json")
    if os.path.exists(path):
        continue
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"https://clinicaltrials.gov/api/v2/studies/{n}?format=json", timeout=60) as r:
                data = json.load(r)
            break
        except Exception as e:                     # retry a few times, slower each time
            if attempt == 3:
                sys.exit(f"{n}: {e}")
            time.sleep(5 * (attempt + 1))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    if i % 50 == 0:
        print(i, "of", len(ids))
    time.sleep(0.3)
print("done:", len(os.listdir(out)), "files")
