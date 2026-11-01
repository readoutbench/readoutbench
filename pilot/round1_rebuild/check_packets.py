"""Check, over every staged packet, that the questions the packet asks are exactly those the checker requires.

usage: python3 -I check_packets.py <round dir>
For each trial: p_met (or none), the number questions, every subgroup and group key, safety, the key secondary
endpoint, the next step and each operations question must appear in the packet exactly when the round asks them
(the round's cards.jsonl and operations.jsonl, as validate() reads them). A stale build, a renderer that drops a
line, or a card the packet does not reflect would make a model following its packets fail the checker on a whole
block. Exits 1 and lists the trials that differ.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import numbers as tnum  # noqa: E402

rd = sys.argv[1]
cards = {json.loads(x)["nct_id"]: json.loads(x) for x in open(os.path.join(rd, "cards.jsonl")) if x.strip()}
ops_path = os.path.join(rd, "operations.jsonl")
ops = ({json.loads(x)["nct_id"]: json.loads(x) for x in open(ops_path) if x.strip()}
       if os.path.exists(ops_path) else {})
OPS_QS = ("p_late", "p_stopped", "p_posted", "p_public_mar", "p_public", "p_public_dec", "p_amended")
problems = {}
n = 0
for line in open(os.path.join(rd, "questions.jsonl")):
    if not line.strip():
        continue
    q = json.loads(line)
    nid, text, c = q["nct_id"], q["packet"], cards.get(q["nct_id"])
    n += 1
    p = []
    if c is None:
        problems[nid] = ["no card"]
        continue
    asked = {
        "p_met": tnum.has_p_met(c),
        "numbers": tnum.is_number_question(c),
        "safety": tnum.has_safety(c),
        "key secondary": bool(tnum.key_secondary(c)),
        "next step": bool(tnum.next_step(c)),
        "subgroups": bool(tnum.subgroup_groups(c)),
    }
    shown = {
        "p_met": "neither `p_met` nor number questions are asked" not in text,
        "numbers": "- Number questions: yes." in text,
        "safety": "- Safety question:" in text,
        "key secondary": "`p_key_secondary`" in text,
        "next step": "`p_next_step`" in text,
        "subgroups": "- Subgroup questions: yes." in text,
    }
    p += [f"{k}: asked {asked[k]}, in the packet {shown[k]}" for k in asked if asked[k] != shown[k]]
    for sid, groups in tnum.subgroup_groups(c).items():
        if f"\"{sid}\"" not in text or any(f"`{g}`" not in text for g in groups):
            p.append(f"subgroup {sid}: id or group keys missing from the packet")
    row = ops.get(nid)
    for oq in OPS_QS:
        want = bool(row) and oq in row.get("questions", [])
        if oq == "p_late":
            got = "- `p_late` (late per the registry)" in text
        elif oq == "p_public":
            got = "- `p_public` (" in text
        elif oq in ("p_public_mar", "p_public_dec"):
            got = f"(`{oq}`)" in text
        else:
            got = f"- `{oq}`" in text
        if want != got:
            p.append(f"{oq}: asked {want}, in the packet {got}")
    if p:
        problems[nid] = p
print(f"{n} packets checked; {len(problems)} differ from the questions the checker requires")
for nid, p in list(problems.items())[:20]:
    print(nid, "; ".join(p))
sys.exit(1 if problems else 0)
