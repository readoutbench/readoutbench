"""Pilot 3, part A: Pilot 2's 111 reported trials through the Round 1 round code, as if they had been a round.

usage: python3 -I backtest.py <pilot2 dir> <work dir>
Pilot 2's trials all reported between July and October 2026, after the models' training data. The round is exported
with their question cards (every card asks number questions), closing on 30 June 2026 with a deadline of 31 October
2026; the entries are Pilot 2's forecasts; the key holds Pilot 2's labels and the published numbers it extracted
(exact or close matches). Writes <work dir>/leaderboard.json (the round's leaderboard, number score as in the rules)
and <work dir>/leaderboard_interval.json (the same with the old interval score, for comparison). Malformed ranges
(low above high, or a zero-width range) are repaired by sorting and widening, and counted.
"""
import json
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import numbers as tnum  # noqa: E402
from tdcb.trials import round as tround  # noqa: E402

p2, work = sys.argv[1], sys.argv[2]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
J = lambda p: [json.loads(l) for l in open(os.path.join(p2, p)) if l.strip()]  # noqa: E731
rows = json.load(open(os.path.join(p2, "set.json")))
ids = [r["nct_id"] for r in rows]
cards = {c["nct_id"]: dict(c, numbers="yes", numbers_reason=None) for c in J("cards.jsonl")}
ext = {e["nct_id"]: e for e in J("extracted_clean.jsonl") if e.get("match") in ("exact", "close")}

b = os.path.join(work, "build")
os.makedirs(os.path.join(b, "private"))
os.makedirs(os.path.join(b, "packets", "C", "open"))
key = [{"nct_id": n, "set": "open", "endpoint_kind": cards[n]["kind"]} for n in ids]
json.dump(key, open(os.path.join(b, "private", "key_C.json"), "w"))
for n in ids:
    open(os.path.join(b, "packets", "C", "open", n + ".md"), "w").write(f"# Trial {n}\n")
    json.dump({"case_id": n, "endpoint_kind": cards[n]["kind"], "record": {"title": n}},
              open(os.path.join(b, "packets", "C", "open", n + ".json"), "w"))
cpath = os.path.join(work, "cards.jsonl")
open(cpath, "w").write("".join(json.dumps(cards[n]) + "\n" for n in ids))
rd = os.path.join(work, "round")
tround.export(b, rd, "p2-backtest", closes="2026-06-30", cards=cpath, deadline="2026-10-31")

meta = {"team": "Proba", "entry_name": "", "contact": "pilot@example.org", "models": [],
        "harness": "Pilot 2, closed book", "setting": "closed", "web_access": False, "cost_usd_per_trial": 0}
MODEL = {"ref-opus-5-5": "claude-opus-5-5", "sonnet-5-5": "claude-sonnet-5-5", "sonnet-5-5-rerun": "claude-sonnet-5-5",
         "haiku-5-5": "claude-haiku-5-5"}
PROMPT = "0" * 64                     # Pilot 2's prompt is not the round's; the backtest round has no instructions
COST = {"ref-opus-5-5": 0.07, "sonnet-5-5": 0.035, "sonnet-5-5-rerun": 0.035, "haiku-5-5": 0.004}
fixes = {}


def clean(o, nid, name):
    o = dict(o)
    o["nct_id"] = nid
    o.pop("case_id", None)
    for w in ("control", "effect"):
        d = o.get(w)
        if not isinstance(d, dict):
            continue
        v = [tnum.num(d.get(k)) for k in ("median", "low80", "high80")]
        if None in v:
            o.pop(w)
            fixes[name] = fixes.get(name, 0) + 1
            continue
        m, lo, hi = v
        lo, hi = min(lo, hi, m), max(lo, hi, m)
        if lo == hi:
            pad = 0.01 * max(abs(m), 1e-3)
            lo, hi = lo - pad, hi + pad
        if (lo, hi) != (v[1], v[2]):
            fixes[name] = fixes.get(name, 0) + 1
        o[w] = {"median": m, "low80": lo, "high80": hi}
        if tnum.check_range(o[w], cards[nid], w):          # e.g. a ratio at or below 0
            o.pop(w)
            fixes[name] = fixes.get(name, 0) + 1
    if o.get("main_risk") not in tnum.MAIN_RISKS:
        o.pop("main_risk", None)
    v = tnum.num(o.get("variability"))
    if v is None or v <= 0:
        o.pop("variability", None)
    return o


def register(eid, name, preds, kind):
    # all or none: keep number answers only on trials where both control and effect survived, and drop them
    # everywhere if any number question is left without both
    full = all("control" in preds[n] and "effect" in preds[n] for n in ids)
    if not full:
        for n in ids:
            if not ("control" in preds[n] and "effect" in preds[n]):
                preds[n].pop("control", None)
                preds[n].pop("effect", None)
    fp = os.path.join(work, eid + ".jsonl")
    open(fp, "w").write("".join(json.dumps(preds[n]) + "\n" for n in ids))
    mp = os.path.join(work, eid + ".meta.json")
    m = dict(meta, entry_name=name, cost_usd_per_trial=COST.get(eid, 0))
    if eid in MODEL:                                   # the Models board: one model and its provenance
        m.update(models=[MODEL[eid]], model_version=MODEL[eid], provider="Anthropic API", prompt_sha256=PROMPT)
    json.dump(m, open(mp, "w"))
    v = tround.validate(rd, fp, mp, reference=True)
    if not v["ok"]:                      # partial number answers: fall back to p_met only, and say so
        for n in ids:
            preds[n].pop("control", None)
            preds[n].pop("effect", None)
        open(fp, "w").write("".join(json.dumps(preds[n]) + "\n" for n in ids))
        print(eid, "number answers incomplete after repair; scored on p_met only")
    tround.register(rd, eid, fp, mp, "2026-06-30", kind=kind)


b1 = {r["case_id"]: r for r in J("b1.jsonl")}
register("ref-b0", "Base rate (B0)", {n: {"nct_id": n, "p_met": b1[n]["b0"]} for n in ids}, "reference")
register("ref-b1", "Registry model (B1)", {n: {"nct_id": n, "p_met": b1[n]["p_met"]} for n in ids}, "reference")
for eid, name, f in (("ref-opus-5-5", "Claude Opus 5.5, closed book", "forecasts_opus.jsonl"),
                     ("sonnet-5-5", "Claude Sonnet 5.5, closed book", "forecasts_sonnet.jsonl"),
                     ("sonnet-5-5-rerun", "Claude Sonnet 5.5, closed book, second run", "forecasts_sonnet_r2.jsonl"),
                     ("haiku-5-5", "Claude Haiku 5.5, closed book", "forecasts_haiku.jsonl")):
    F = {r["case_id"]: r for r in J(f)}
    register(eid, name, {n: clean(F[n], n, eid) for n in ids}, "reference" if eid.startswith("ref-") else "entry")
print("repaired ranges:", fixes)

lab = {r["nct_id"]: r for r in rows}
for k in key:
    n = k["nct_id"]
    e = ext.get(n, {})
    k.update(set="post_cutoff", met=lab[n]["met"], first_public_date=lab[n]["first_public"],
             control_value=tnum.num(e.get("control_value")), effect_value=tnum.num(e.get("effect_estimate")))
json.dump(key, open(os.path.join(b, "private", "key_C.json"), "w"))
lb = tround.leaderboard(b, rd, n_boot=2000, min_scored=20)
json.dump(lb, open(os.path.join(work, "leaderboard.json"), "w"), indent=1)
tnum.percentile_score = lambda r, y, log: tnum.interval_score(r, y, log)     # the old score, for comparison
json.dump(tround.leaderboard(b, rd, n_boot=0, min_scored=20), open(os.path.join(work, "leaderboard_interval.json"), "w"),
          indent=1)
print(json.dumps(lb["status"]))
for e in lb["entries"] + lb["references"]:
    nb = e.get("numbers") or {}
    add = e.get("adds_to_registry_model") or {}
    print(f"{e['id']:18s} {e['board']:8s} tier {e.get('tier', '-')} brier {e['brier']:.3f} "
          f"bss_b1 {e['bss_vs_registry_model'] if e['bss_vs_registry_model'] is not None else float('nan'):+.3f} "
          f"ci {e['bss_vs_registry_model_ci95']} auroc {e['auroc']} adds {add.get('brier_gain')} {add.get('ci95')} "
          f"numbers {nb.get('score')}")
