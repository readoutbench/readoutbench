"""Read full registry records (get_trial_details) back out of the retrieval agents' transcripts.

usage: python3 -I collect_records.py <sample.json> <agents.tsv> <tasks dir> <out records.jsonl> <out missing.txt>
Keeps the fields of pilot/labelling/trim_record.py (no locations, but their number and countries).
"""
import datetime as dt
import json
import os
import re
import sys

KEEP = ["nct_id", "title", "brief_title", "acronym", "status", "phase", "study_type", "conditions", "interventions",
        "sponsor", "collaborators", "enrollment", "start_date", "primary_completion_date", "completion_date",
        "brief_summary", "detailed_description", "eligibility_criteria", "minimum_age", "maximum_age", "sex",
        "primary_outcomes", "secondary_outcomes", "url", "has_results"]
samplep, agents, tdir, outp, missp = sys.argv[1:6]
want = set(json.load(open(samplep)))
SAVED = re.compile(r"(?:Output has been saved to|Full output saved to:)\s*(\S+?\.txt)")
got, problems = {}, []
for line in open(agents):
    if not line.strip():
        continue
    model, batch, aid = line.split()
    path = os.path.join(tdir, aid + ".output")
    if not os.path.exists(path):
        problems.append(f"{batch}: no transcript")
        continue
    uses = {}
    for raw in open(path, encoding="utf-8", errors="replace"):
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        content = (m.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                uses[c.get("id")] = (c.get("name"), c.get("input") or {})
            elif c.get("type") == "tool_result":
                name, inp = uses.get(c.get("tool_use_id"), (None, {}))
                if name != "mcp__Clinical_Trials__get_trial_details":
                    continue
                n = str(inp.get("nct_id") or "").strip().upper()
                cc = c.get("content")
                text = "".join(x.get("text", "") for x in cc if isinstance(x, dict)) if isinstance(cc, list) else str(cc)
                m2 = SAVED.search(text)
                if m2:
                    try:
                        text = open(m2.group(1), encoding="utf-8").read()
                    except OSError:
                        problems.append(f"{batch}: saved file missing for {n}")
                        continue
                try:
                    d = json.loads(text)
                except json.JSONDecodeError:
                    problems.append(f"{batch}: unparsable result for {n}: {text[:80]}")
                    continue
                t = d.get("trial", d) if isinstance(d, dict) else None
                if not isinstance(t, dict) or t.get("nct_id") != n or n not in want:
                    problems.append(f"{batch}: result not usable for {n}")
                    continue
                rec = {k: t.get(k) for k in KEEP}
                locs = t.get("locations") if isinstance(t.get("locations"), list) else []
                rec["n_locations"] = len(locs)
                rec["countries"] = sorted({str(x.get("country")) for x in locs if isinstance(x, dict) and x.get("country")})
                rec["fetched_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                got[n] = rec
with open(outp, "w") as fh:
    for n in sorted(got):
        fh.write(json.dumps(got[n], ensure_ascii=False) + "\n")
missing = sorted(want - set(got))
open(missp, "w").write("\n".join(missing) + ("\n" if missing else ""))
print("wanted", len(want), "| records", len(got), "| missing", len(missing))
for p in problems[:20]:
    print("  ", p)
