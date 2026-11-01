"""Round 1 (rebuilt): stage the round from the question list, the records and the question cards.

usage: python3 -I stage_round.py <questions.json> <cards.jsonl> <work dir> --records <records.jsonl> [...]
                                 --snapshot <the day the records were pulled> [--opens 2026-11-01] [--closes 2026-11-15]
                                 [--early-deadline 2027-03-31] [--deadline 2027-06-30] [--final-deadline 2027-12-31]
                                 [--ops-read 2027-08-31]
                                 [--sisters sisters.json] [--instructions forecast_instructions.md]
Writes <work dir>/registry/<NCT>.json (the records), <work dir>/labels_open.jsonl (every question open) and
<work dir>/operations.jsonl (the launch-day status, registered primary completion date and operations questions of
each trial, with --opens as the launch day), builds the Track C set (<work dir>/build) and exports the round to <work dir>/round
with its cards, operations questions (p_public for each of the three passes added for every trial with p_met, and
p_amended for every trial), sister groups and forecast
instructions, which are the Models board's prompt (default: forecast_instructions.md next to this script). On launch
day, run it on the records pulled that day.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import build as tbuild  # noqa: E402
from tdcb.trials import operations as tops  # noqa: E402
from tdcb.trials import round as tround  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("questions")
ap.add_argument("cards")
ap.add_argument("work")
ap.add_argument("--records", nargs="+", required=True)
ap.add_argument("--snapshot", required=True, help="the day the records were pulled (shown in every packet)")
ap.add_argument("--opens", default="2026-11-01")
ap.add_argument("--closes", default="2026-11-15")
ap.add_argument("--final-deadline", default="2027-12-31")
ap.add_argument("--sisters")
ap.add_argument("--deadline", default="2027-06-30")
ap.add_argument("--early-deadline", default="2027-03-31")
ap.add_argument("--round", default="2026-r1")
ap.add_argument("--ops-read", default=tops.OPS_READ_DATE)
ap.add_argument("--instructions", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                       "forecast_instructions.md"))
a = ap.parse_args()
ids = [q["nct_id"] for q in json.load(open(a.questions))]
recs = {}
for p in a.records:
    for line in open(p):
        if line.strip():
            r = json.loads(line)
            recs[r["nct_id"]] = r
reg = os.path.join(a.work, "registry")
os.makedirs(reg, exist_ok=True)
for n in ids:
    json.dump(recs[n], open(os.path.join(reg, n + ".json"), "w"), indent=1, ensure_ascii=False)
labels = os.path.join(a.work, "labels_open.jsonl")
with open(labels, "w") as fh:
    for n in ids:
        fh.write(json.dumps({"nct_id": n, "reported": "no"}) + "\n")
cards = os.path.join(a.work, "cards.jsonl")
want = set(ids)
with open(cards, "w") as fh:
    for line in open(a.cards):
        if line.strip() and json.loads(line)["nct_id"] in want:
            fh.write(line if line.endswith("\n") else line + "\n")
ops = os.path.join(a.work, "operations.jsonl")
no_ops = []
with open(ops, "w") as fh:
    for n in ids:
        row = tops.launch_row(recs[n], a.opens)
        if row is None:
            no_ops.append(n)
        else:
            fh.write(json.dumps(row) + "\n")
if no_ops:
    raise SystemExit(f"{len(no_ops)} trials are stopped, have posted results or no primary completion date on the "
                     f"records given; take them off the list first: {no_ops[:10]}")
m = tbuild.build(reg, [labels], os.path.join(a.work, "build"), snapshot_date=a.snapshot)
print("build:", m["counts"], "leak phrases:", len(m["leak_phrases"]) or "none")
man = tround.export(os.path.join(a.work, "build"), os.path.join(a.work, "round"), a.round, closes=a.closes,
                    opens=a.opens, cards=cards, deadline=a.deadline, operations=ops, ops_read=a.ops_read,
                    final_deadline=a.final_deadline, sisters=a.sisters, instructions=a.instructions,
                    early_deadline=a.early_deadline)
print({k: man.get(k) for k in ("round", "opens", "closes", "early_deadline", "deadline", "final_deadline", "n_trials",
                               "n_p_met_questions", "n_number_questions", "n_subgroup_questions", "n_subgroups",
                               "n_safety_questions", "n_key_secondary_questions", "n_next_step_questions",
                               "n_operations_questions",
                               "operations_read_date", "n_sister_groups", "instructions_sha256")})
