"""Turn a registry status pull into one line per trial of the round, beside the values the round was built from.

usage: python3 -I status_pull.py <records.jsonl> <round questions.json> <out.jsonl> <raw file or folder> [...]

Each raw input is either
  - a ClinicalTrials.gov API v2 study record as fetch_raw.py saves it (<NCT>.json, one per trial): status,
    hasResults, primary completion date and type, enrollment and the record's last update are read from it; or
  - a search result as the organiser's ClinicalTrials.gov tool returns it ({"items": [{"nct_id", "status",
    "primary_completion_date", "enrollment", ...}]}), which carries no hasResults field: for those rows has_results
    is null, and whether any trial has results posted is shown by the separate query in results_query.json.
The pull time of a raw file is taken from its name when it carries a millisecond epoch (the tool's own file names),
else from the file's modification time; it is written in UTC on every row. Rows are written in the order of the
round's questions.json. Standard library only.
"""
import datetime as dt
import json
import os
import re
import sys


def utc(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pulled_at(path):
    m = re.search(r"(\d{13})", os.path.basename(path))
    return utc(int(m.group(1)) / 1000) if m else utc(os.path.getmtime(path))


def from_api(d):
    p = d.get("protocolSection", {})
    st, dsm = p.get("statusModule", {}), p.get("designModule", {})
    pcd = st.get("primaryCompletionDateStruct") or {}
    return {"nct_id": p.get("identificationModule", {}).get("nctId"), "status": st.get("overallStatus"),
            "has_results": d.get("hasResults"), "primary_completion_date": pcd.get("date"),
            "primary_completion_type": pcd.get("type"),
            "enrollment": (dsm.get("enrollmentInfo") or {}).get("count"),
            "last_update_posted": (st.get("lastUpdatePostDateStruct") or {}).get("date")}


def from_search(it):
    return {"nct_id": it.get("nct_id"), "status": it.get("status"), "has_results": None,
            "primary_completion_date": it.get("primary_completion_date"), "primary_completion_type": None,
            "enrollment": it.get("enrollment"), "last_update_posted": None}


def main(records, questions, out, *raw):
    recs = {json.loads(x)["nct_id"]: json.loads(x) for x in open(records, encoding="utf-8") if x.strip()}
    order = [q["nct_id"] for q in json.load(open(questions, encoding="utf-8"))]
    files = []
    for r in raw:
        files += sorted(os.path.join(r, f) for f in os.listdir(r) if f.endswith(".json")) if os.path.isdir(r) else [r]
    got = {}
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        rows = [from_search(it) for it in d["items"]] if "items" in d else [from_api(d)]
        for row in rows:
            got[row["nct_id"]] = dict(row, pulled_utc=pulled_at(f), raw_file=os.path.basename(f))
    missing = [n for n in order if n not in got]
    if missing:
        sys.exit(f"{len(missing)} trials of the round are not in the pull, e.g. {missing[:5]}")
    n_changed = 0
    with open(out, "w", encoding="utf-8") as fh:
        for n in order:
            g, r = got[n], recs.get(n, {})
            row = dict(g, status_in_records=r.get("status"), primary_completion_in_records=r.get("primary_completion_date"))
            n_changed += (row["status"] != row["status_in_records"]
                          or row["primary_completion_date"] != row["primary_completion_in_records"])
            fh.write(json.dumps(row) + "\n")
    print(f"{len(order)} rows; {n_changed} with a status or primary completion date different from records.jsonl; "
          + (f"{sum(got[n]['has_results'] is True for n in order)} with results posted"
             if all(got[n]["has_results"] is not None for n in order) else
             f"results field not in {sum(got[n]['has_results'] is None for n in order)} rows' raw files (search results "
             "carry none); see results_query.json"))


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
