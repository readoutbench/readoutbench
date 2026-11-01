"""Check the organiser's Models board runs: closed book, and complete. Then merge each model's answers into one file.

usage: python3 -I check_model_runs.py <agents.tsv> <transcripts dir> <outputs dir> <batches dir> <out forecasts.jsonl>
                                      --instructions <the round's forecast_instructions.md> --manifest <manifest.json>
                                      --model-version <exact model id>
agents.tsv: one line per run agent: model, batch name, agent id (its transcript is <transcripts dir>/<id>.output).
Refuses (exit 1) if any transcript used a tool other than Read, Write and Edit (any web search or fetch above all),
read a file other than the instructions, its own batch and its own output, or wrote or edited any file but its own
output; and lists every batch whose output is missing, malformed or does not hold exactly one line per trial of the
batch (in any order: the answers are merged in the batch's order). Otherwise writes the merged forecasts. Reading or
editing the run's own output file brings in no information (models check and tidy their own answers, such as dropping
a field the trial does not ask), so both are allowed like a second Write. The instructions read must be the round's
own file (that path, with the SHA-256 in the manifest), and every reply in every transcript must name the declared model
version (a reply naming none is refused too). Every trial of the round (the manifest's list) must be answered by exactly
one checked run; answers for trials since taken out of the round are left out of the merged file. The output file must be
exactly what the transcript's own Write and Edit calls produce, so an answer changed after the run is refused. A message
the harness itself marks <synthetic> (an API error notice) carries no model output and is passed over, unless it calls a
tool.
"""
import argparse
import hashlib
import json
import os
import sys

ap = argparse.ArgumentParser()
for x in ("agents", "tdir", "odir", "bdir", "outp"):
    ap.add_argument(x)
ap.add_argument("--instructions", required=True)
ap.add_argument("--manifest", required=True)
ap.add_argument("--model-version", required=True)
a = ap.parse_args()
agents, tdir, odir, bdir, outp = a.agents, a.tdir, a.odir, a.bdir, a.outp
lists = json.load(open(os.path.join(bdir, "lists.json")))
problems, lines = [], []
man = json.load(open(a.manifest))
want = man["instructions_sha256"]
round_trials = man["trials"]
if hashlib.sha256(open(a.instructions, "rb").read()).hexdigest() != want:
    problems.append(f"{a.instructions} is not the round's instructions (SHA-256 {want[:12]}... in the manifest)")
INSTR = os.path.abspath(a.instructions)
for row in open(agents):
    if not row.strip():
        continue
    model, batch, aid = row.split()
    path = os.path.join(tdir, aid + ".output")
    if not os.path.exists(path):
        problems.append(f"{batch}: no transcript")
        continue
    seen_model = False
    written = None                    # the output file as the transcript's own Write and Edit calls leave it
    for raw in open(path, encoding="utf-8", errors="replace"):
        if not raw.strip():
            continue
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            problems.append(f"{batch}: a transcript line is not JSON (a cut-off log cannot be checked)")
            continue
        msg = (m.get("message") if isinstance(m, dict) else None) or {}
        if not isinstance(msg, dict):
            continue
        has_tool = any(isinstance(c, dict) and c.get("type") == "tool_use" for c in msg.get("content") or [])
        named = msg.get("model")
        if named == "<synthetic>" and not has_tool:
            pass                                  # the harness's own placeholder (an API error), no model output
        elif (msg.get("role") == "assistant" or named is not None or has_tool) and named != a.model_version:
            # every reply must name the declared model: a reply naming another, or none, cannot be verified
            problems.append(f"{batch}: a reply came from {msg.get('model') or 'an unnamed model'}, "
                            f"not {a.model_version}")
        seen_model = seen_model or (msg.get("role") == "assistant" and msg.get("model") == a.model_version)
        for c in msg.get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            name, inp = c.get("name"), c.get("input") or {}
            if name == "SubagentHandback":      # the harness's own end-of-task report: brings in no information
                continue
            fp = str(inp.get("file_path", ""))
            own = os.path.abspath(fp) == os.path.abspath(os.path.join(odir, batch + ".jsonl"))
            if name not in ("Read", "Write", "Edit"):
                problems.append(f"{batch}: used the tool {name}")
            elif name == "Read" and not (own or os.path.abspath(fp) == INSTR
                                         or os.path.abspath(fp) == os.path.abspath(os.path.join(bdir, batch + ".md"))):
                problems.append(f"{batch}: read {fp}")
            elif name in ("Write", "Edit") and not own:
                problems.append(f"{batch}: {'wrote' if name == 'Write' else 'edited'} {fp}")
            elif name == "Write":
                written = str(inp.get("content", ""))
            elif name == "Edit":
                old, new = str(inp.get("old_string", "")), str(inp.get("new_string", ""))
                if written is None or not old or old not in written:
                    written = None if written is None else written + "\x00edit-not-applied"
                else:
                    written = written.replace(old, new) if inp.get("replace_all") else written.replace(old, new, 1)
    if not seen_model:
        problems.append(f"{batch}: no reply from {a.model_version} in the transcript")
    op = os.path.join(odir, batch + ".jsonl")
    if not os.path.exists(op):
        problems.append(f"{batch}: no output")
        continue
    if written is None or written.strip() != open(op, encoding="utf-8").read().strip():
        # the file must be exactly what the model wrote: an answer changed afterwards, by anyone, is refused
        problems.append(f"{batch}: the output file differs from what the transcript wrote")
        continue
    got = []
    for x in open(op, encoding="utf-8"):
        if x.strip():
            try:
                got.append(json.loads(x))
            except json.JSONDecodeError:
                problems.append(f"{batch}: a line is not JSON")
    ids = [g.get("nct_id") for g in got]
    if sorted(ids, key=str) != sorted(lists[batch]):
        problems.append(f"{batch}: {len(got)} lines, not one per trial of the batch")
        continue
    # the line order brings no information: the answers are merged in the batch's order
    by_id = {g["nct_id"]: g for g in got}
    lines += [json.dumps(by_id[n], ensure_ascii=False) for n in lists[batch]]
# every trial of the round must be answered by exactly one checked run; trials taken out of the round are left out
by_trial = {}
for x in lines:
    n = json.loads(x)["nct_id"]
    if n in by_trial:
        problems.append(f"{n}: answered by more than one run in agents.tsv")
    by_trial[n] = x
left = [n for n in round_trials if n not in by_trial]
if left:
    problems.append(f"{len(left)} trials of the round have no checked run, e.g. {', '.join(left[:5])}")
if problems:
    print("\n".join(problems))
    sys.exit(1)
out = [by_trial[n] for n in round_trials]
open(outp, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(len(out), "forecasts merged, one per trial of the round", f"({len(by_trial) - len(out)} for trials no longer in it left out);",
      "every transcript used only Read, Write and Edit, on its own files, and every reply came from", a.model_version)
