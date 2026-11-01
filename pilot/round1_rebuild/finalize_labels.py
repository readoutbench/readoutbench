"""Round 1 (rebuilt): from two independent labellers' outputs to the round's labels.

usage: python3 -I finalize_labels.py <labeller A.jsonl> <labeller B.jsonl> <out dir> --as-of <YYYY-MM-DD>
                                     --deadline <YYYY-MM-DD> --manifest <round>/manifest.json
                                     [--decisions decisions.jsonl]
Each labeller follows label_instructions_r1.md without seeing any forecast. Each row is first read with the round's
rules, at the pass's deadline:
- met "yes"/"no": as given, if it was clear by the deadline (clear_date, which these need); if it became clear only
  after the deadline, the trial was vague at the deadline (below);
- met "endpoint_changed" (rule 7): not met;
- stopped with stop_reason "no public reason" (rule 5): not met; "not about efficacy": dropped when the stop was
  public by the pass's deadline, else open in that pass (no public result: 0 for p_public, as the rules say);
- met "vague" (rules 6, 8), or clear only after the deadline: still open before the deadline; not met once `--as-of`
  is past it;
- reported "no": open.
Numbers count only if published by the deadline (numbers_date, or the clear date when it is missing); later ones are
left out of that pass. Dates are YYYY-MM-DD (YYYY-MM is read as the 1st, as the instructions say); a row with another
date form, a missing clear_date where one is needed, or a clear date before the first date is a conflict.
The two readings agree when they give the same outcome, first-disclosure dates within 7 days and on the same side of
the close and of the deadline (otherwise one labeller's date alone would decide whether the trial is dropped, scored
or late), the same answer to whether the trial was only vague at the deadline, and the same numbers (within 2%).
Agreed trials get their label; disagreements go to <out dir>/disagreements.jsonl for the organiser, whose decisions
(one JSON line per trial, in the labellers' own format) are read with the same rules and checks and applied with
--decisions; a decision that fails the checks stops the run. Writes
<out dir>/labels.jsonl (for tdcb.trials.labels) and <out dir>/agreement.json (published): the agreement rate over the
trials at least one labeller found a result for (two "nothing found" readings are not counted as agreement),
Cohen's kappa over the same trials, and, for reference, kappa over every trial labelled twice; the file states each
denominator.
The secondary answers (the safety shares, whether the key secondary endpoint was met, the subgroup effects) do not
decide whether the readings agree: each counts when both labellers give it, by the deadline (safety_date,
key_secondary_date, subgroup_date; a missing safety or subgroup date falls back to numbers_date, then clear_date), and
agree (numbers within 2%); otherwise it is left out of the label and listed in
<out dir>/secondary_disagreements.jsonl for the organiser, as is any answer that is malformed, undated, or a subgroup
or group not on the round's card (cards.jsonl beside --manifest).
Decisions apply field by field. A decision row with "reported" decides the main label; any of safety_experimental,
safety_control, key_secondary_met (with its date field) and subgroup_effects it carries replaces that field only
(null: none; under subgroup_effects, each subgroup listed replaces that subgroup), and every other secondary field
keeps what the labellers agreed. A row without "reported" decides secondary fields only, for a trial whose main
readings agreed. So a decision row should carry only the fields being decided.
Every label row records the deadline and as-of day it was read for (label_deadline, labels_as_of); the leaderboard
refuses to score a pass with labels read for another.
Run it once per pass, with that pass's deadline: --deadline 2027-03-31 for the early pass, 2027-06-30 for the ranked
first pass, and the final deadline for the supplementary pass, since a vague result counts as not met only after its
pass's deadline.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import numbers as tnum  # noqa: E402

NUM = ("control_value", "effect_value", "women_effect", "men_effect")
REPORTED = ("yes", "no", "stopped_without_result")
STOP_REASONS = ("efficacy", "futility", "harm", "not about efficacy", "no public reason")


class BadDate(ValueError):
    pass


SAFETY = ("safety_experimental", "safety_control")
SEC_DATE = {"safety_experimental": "safety_date", "safety_control": "safety_date",
            "key_secondary_met": "key_secondary_date", "subgroup_effects": "subgroup_date"}


def _num(x):
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _given(x) -> bool:
    return x not in (None, "", {}, [])


def _source_date(o: dict, field: str, deadline: str) -> tuple[bool, str | None]:
    """(counts at the deadline, problem) for a secondary answer that was given. A missing safety or subgroup date falls
    back to numbers_date, then clear_date, as the numbers do; a malformed or missing date is a problem."""
    dk = SEC_DATE[field]
    raw = o.get(dk)
    if raw in (None, "") and dk in ("safety_date", "subgroup_date"):
        raw = o.get("numbers_date") or o.get("clear_date")
    try:
        d = _d(raw)
    except BadDate:
        return False, f"{dk} not YYYY-MM-DD: {raw!r}"
    if not d:
        return False, f"{field} given with no {dk}"
    return d <= deadline, None


def _yes_no(x):
    """key_secondary_met as 1 or 0 ("yes"/"no" in any case, 1/0, true/false), or None for any other form."""
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)) and x in (0, 1):
        return int(x)
    if isinstance(x, str):
        return {"yes": 1, "no": 0}.get(x.strip().lower())
    return None


def secondary(o: dict, deadline: str, groups: dict | None = None) -> dict:
    """One labeller's secondary answers that count at the deadline: the safety shares (0-100), key_secondary_met (1 or
    0) and the subgroup effects ({subgroup: {group: value}}, checked against the card's subgroups `groups` when given).
    An answer whose source is dated after the deadline is left out. One that is malformed, undated or not the card's
    is left out and listed in "_problems" ({field: why}), so that it reaches the organiser instead of vanishing."""
    out = {"safety_experimental": None, "safety_control": None, "key_secondary_met": None, "subgroup_effects": {}}
    bad = {}
    for k in SAFETY:
        x = o.get(k)
        if not _given(x):
            continue
        v = _num(x)
        if v is None or not 0 <= v <= 100:
            bad[k] = f"{k} {x!r} is not a share from 0 to 100"
            continue
        ok, why = _source_date(o, k, deadline)
        if why:
            bad[k] = why
        elif ok:
            out[k] = v
    x = o.get("key_secondary_met")
    if _given(x):
        v = _yes_no(x)
        if v is None:
            bad["key_secondary_met"] = f"key_secondary_met {x!r} is not \"yes\", \"no\" or null"
        else:
            ok, why = _source_date(o, "key_secondary_met", deadline)
            if why:
                bad["key_secondary_met"] = why
            elif ok:
                out["key_secondary_met"] = v
    e = o.get("subgroup_effects")
    if _given(e):
        if not isinstance(e, dict) or not all(isinstance(d, dict) for d in e.values()):
            bad["subgroup_effects"] = f"subgroup_effects is not {{subgroup: {{group: value}}}}: {str(e)[:80]}"
        else:
            ok, why = _source_date(o, "subgroup_effects", deadline)
            if why:
                bad["subgroup_effects"] = why
            elif ok:
                for sid, d in e.items():
                    for g, x in d.items():
                        if not _given(x):
                            continue
                        f = f"subgroup_effects.{sid}.{g}"
                        v = _num(x)
                        if v is None:
                            bad[f] = f"{f} {x!r} is not a number"
                        elif groups is not None and str(g) not in (groups.get(str(sid)) or ()):
                            bad[f] = f"{f}: not a subgroup and group of the card"
                        else:
                            out["subgroup_effects"].setdefault(str(sid), {})[str(g)] = v
    out["_problems"] = bad
    return out


def merge_secondary(x: dict, y: dict) -> tuple[dict, list]:
    """The secondary answers both labellers agree on, and the ones they do not or that have a problem (for the
    organiser)."""
    out, dis = {}, []
    px, py = x.get("_problems") or {}, y.get("_problems") or {}
    for k in SAFETY + ("key_secondary_met",):
        a, b = x.get(k), y.get(k)
        why = "; ".join(p for p in (px.get(k), py.get(k)) if p)
        if why:
            out[k] = None
            dis.append({"field": k, "a": a, "b": b, "why": why})
        elif a is None and b is None:
            out[k] = None
        elif a is not None and b is not None and (a == b if k == "key_secondary_met" else _close(a, b)):
            out[k] = a
        else:
            out[k] = None
            dis.append({"field": k, "a": a, "b": b})
    eff = {}
    xs, ys = x.get("subgroup_effects") or {}, y.get("subgroup_effects") or {}
    for s in sorted(set(xs) | set(ys)):
        ga, gb = xs.get(s, {}), ys.get(s, {})
        for g in sorted(set(ga) | set(gb)):
            if g in ga and g in gb and _close(ga[g], gb[g]):
                eff.setdefault(s, {})[g] = ga[g]
            else:
                dis.append({"field": f"subgroup_effects.{s}.{g}", "a": ga.get(g), "b": gb.get(g)})
    for k in sorted(set(px) | set(py)):
        if k.startswith("subgroup_effects"):
            dis.append({"field": k, "why": "; ".join(p for p in (px.get(k), py.get(k)) if p)})
    out["subgroup_effects"] = eff
    return out, dis


def decision_secondary(row: dict, deadline: str, groups: dict | None) -> tuple[dict, dict]:
    """The secondary fields an organiser's decision row carries, read like a labeller's ({field: value}; null means
    none; under subgroup_effects, each subgroup listed replaces that subgroup's groups), and its problems."""
    sv = secondary(row, deadline, groups)
    carried = {k: sv[k] for k in SAFETY + ("key_secondary_met",) if k in row}
    if "subgroup_effects" in row:
        e = row["subgroup_effects"] if isinstance(row["subgroup_effects"], dict) else {}
        carried["subgroup_effects"] = {str(sid): dict(sv["subgroup_effects"].get(str(sid), {})) for sid in e}
    return carried, sv["_problems"]


def apply_decision(sec: dict, sd: list, d: dict) -> tuple[dict, list]:
    """Overwrite the merged secondary answers with the fields the organiser decided, and drop what that settles."""
    sec = dict(sec, subgroup_effects=dict(sec["subgroup_effects"]))
    for k in SAFETY + ("key_secondary_met",):
        if k in d:
            sec[k] = d[k]
            sd = [z for z in sd if z["field"] != k]
    if "subgroup_effects" in d:
        sd = [z for z in sd if z["field"] != "subgroup_effects"]
    for sid, gs in (d.get("subgroup_effects") or {}).items():
        if gs:
            sec["subgroup_effects"][sid] = gs
        else:
            sec["subgroup_effects"].pop(sid, None)
        sd = [z for z in sd if not z["field"].startswith(f"subgroup_effects.{sid}.")]
    return sec, sd


def _d(x) -> str | None:
    """A label date as YYYY-MM-DD; YYYY-MM is read as the 1st; anything else raises BadDate."""
    if x in (None, ""):
        return None
    s = str(x).strip()
    if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", s):
        raise BadDate(s)
    try:
        if len(s) == 7:
            return dt.date(int(s[:4]), int(s[5:7]), 1).isoformat()
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        raise BadDate(s) from None


def reading(o: dict, as_of: str, deadline: str) -> dict:
    """One labeller's row read with the round's rules at the pass's deadline:
    {state: open|met|not_met|dropped|conflict, first_public_date, clear_date, vague_at_deadline, numbers...};
    a conflict carries `why`."""
    rep, met = o.get("reported"), o.get("met")
    try:
        first, clear, when = (_d(o.get(k)) for k in ("first_public_date", "clear_date", "numbers_date"))
    except BadDate as e:
        return {"state": "conflict", "why": f"date not YYYY-MM-DD: {e}", "first_public_date": None,
                "clear_date": None, "vague_at_deadline": False, **{k: None for k in NUM}}
    when = when or clear
    late_numbers = not when or when > deadline
    base = {"first_public_date": first, "clear_date": clear, "vague_at_deadline": False,
            **{k: (None if late_numbers else o.get(k)) for k in NUM}}
    if rep not in REPORTED:
        return dict(base, state="conflict", why=f"reported {rep!r}")
    if rep in ("yes", "stopped_without_result") and not first:
        return dict(base, state="conflict", why=f"reported {rep} with no first_public_date")
    if rep == "stopped_without_result":
        if o.get("stop_reason") not in STOP_REASONS:
            return dict(base, state="conflict", why=f"stop_reason {o.get('stop_reason')!r}")
        if o.get("stop_reason") == "not about efficacy":
            if first > deadline:      # left the round only after this pass's deadline: no public result in this pass
                return dict(base, state="open", first_public_date=None, clear_date=None)
            return dict(base, state="dropped", clear_date=first)      # left by the deadline: void in this pass
        return dict(base, state="not_met", clear_date=first)
    if rep != "yes":
        return dict(base, state="open")
    if first and clear and clear < first:
        return dict(base, state="conflict", why="clear_date before first_public_date")
    vague_at_deadline = dict(base, state="not_met" if as_of > deadline else "open", clear_date=None,
                             vague_at_deadline=as_of > deadline)
    if met in ("yes", "no", "endpoint_changed"):
        if not clear:                                  # needed: without it the deadline cannot be applied (rule 6)
            return dict(base, state="conflict", why=f"met {met} with no clear_date")
        if clear > deadline:                           # clear only after the deadline: vague in this pass (rule 6)
            return vague_at_deadline
        return dict(base, state="met" if met == "yes" else "not_met")
    if met == "vague":
        return vague_at_deadline
    return dict(base, state="conflict", why=f"met {met!r}")


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 0.02 * max(abs(a), abs(b), 1e-9)


def _days(a, b) -> int:
    return abs((dt.date.fromisoformat(a[:10]) - dt.date.fromisoformat(b[:10])).days)


def agree(x: dict, y: dict, close: str | None = None, deadline: str | None = None) -> bool:
    if x["state"] != y["state"] or "conflict" in (x["state"], y["state"]):
        return False
    if x["state"] in ("met", "not_met"):
        fx, fy = x["first_public_date"], y["first_public_date"]
        if not fx or not fy or _days(fx, fy) > 7:
            return False
        for b in (close, deadline):                    # the same side of every boundary that decides the trial
            if b and (fx <= b) != (fy <= b):
                return False
        cx, cy = x.get("clear_date"), y.get("clear_date")
        if deadline and cx and cy and (cx <= deadline) != (cy <= deadline):
            return False
        if bool(x.get("vague_at_deadline")) != bool(y.get("vague_at_deadline")):   # "vague" against "clearly not met"
            return False
    return all(_close(x[k], y[k]) for k in NUM)


def label(nid: str, r: dict, src: dict) -> dict:
    state = r["state"]
    out = {"nct_id": nid, "reported": {"open": "no", "dropped": "stopped_without_result"}.get(state, "yes"),
           "met": {"met": "yes", "not_met": "no"}.get(state, "not_reported"),
           "first_public_date": r["first_public_date"] if state in ("met", "not_met") else None,
           "clear_date": r["clear_date"] if state in ("met", "not_met") else None,
           "vague_at_deadline": bool(r.get("vague_at_deadline")),
           "confidence": src.get("confidence") or "medium", "sources": src.get("sources") or [],
           "quote": src.get("quote"), "endpoint": src.get("endpoint"), "interim": src.get("interim"),
           "notes": src.get("notes")}
    out.update({k: r[k] for k in NUM})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("out")
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--deadline", required=True)
    ap.add_argument("--manifest", required=True,
                    help="the round's manifest.json: its close (dates either side of it disagree) and its pass "
                         "deadlines, one of which --deadline must be; the round's cards.jsonl beside it gives the "
                         "subgroups each label may carry")
    ap.add_argument("--decisions")
    a = ap.parse_args()
    man = json.load(open(a.manifest))
    a.close = man.get("closes")
    passes = {d for d in (man.get("early_deadline"), man.get("deadline"), man.get("final_deadline")) if d}
    if not a.close or not passes:
        raise SystemExit(f"{a.manifest}: no close or no pass deadlines (is it the round's manifest?)")
    if a.deadline not in passes:
        raise SystemExit(f"--deadline {a.deadline} is not one of the round's pass deadlines {sorted(passes)}")
    load = lambda p: {json.loads(l)["nct_id"]: json.loads(l) for l in open(p) if l.strip()}  # noqa: E731,E741
    cards_path = os.path.join(os.path.dirname(os.path.abspath(a.manifest)), "cards.jsonl")
    groups_of = ({n: tnum.subgroup_groups(c) for n, c in load(cards_path).items()}
                 if os.path.exists(cards_path) else None)
    gr = (lambda n: groups_of.get(n, {})) if groups_of is not None else (lambda n: None)  # noqa: E731
    A, B = load(a.a), load(a.b)
    dec = load(a.decisions) if a.decisions else {}
    # the two labellers' readings, and which trials they agree on
    readings, agreed = {}, set()
    for nid in sorted(set(A) & set(B)):
        x, y = reading(A[nid], a.as_of, a.deadline), reading(B[nid], a.as_of, a.deadline)
        readings[nid] = (x, y)
        if agree(x, y, a.close, a.deadline):
            agreed.add(nid)
    # the organiser's decisions: a row with "reported" decides the main label (read with the same rules and checks);
    # the secondary fields a row carries replace those fields only. Any decision that fails the checks stops the run.
    bad = {n: "not a trial of either labeller's list" for n in dec if n not in A and n not in B}
    dec_main, dec_sec = {}, {}
    for nid, row in dec.items():
        if nid in bad:
            continue
        if "reported" in row:
            r = reading(row, a.as_of, a.deadline)
            if r["state"] == "conflict":
                bad[nid] = r.get("why")
                continue
            dec_main[nid] = label(nid, r, row)
        elif nid not in agreed:
            bad[nid] = "decides only secondary answers, but the main label is not agreed: decide it too"
            continue
        carried, probs = decision_secondary(row, a.deadline, gr(nid))
        if probs:
            bad[nid] = "; ".join(f"{k}: {v}" for k, v in probs.items())
            continue
        if carried:
            dec_sec[nid] = carried
        elif nid not in dec_main:
            bad[nid] = "decides nothing: no \"reported\" and no secondary field"
    if bad:
        raise SystemExit(f"{len(bad)} organiser decisions fail the checks: {bad}")
    os.makedirs(a.out, exist_ok=True)
    labels, dis, sec_dis = [], [], []
    pairs = []                                       # (reading A, reading B) for kappa and resolved agreement
    none = {"safety_experimental": None, "safety_control": None, "key_secondary_met": None, "subgroup_effects": {}}
    for nid in sorted(set(A) | set(B)):
        both = nid in readings
        if both:
            x, y = readings[nid]
            pairs.append((x["state"], y["state"], nid in agreed))
        if nid in dec_main:
            lab = dict(dec_main[nid])
        elif nid in agreed:
            lab = label(nid, readings[nid][0], A[nid])
        else:
            if not both:
                dis.append({"nct_id": nid, "why": "labelled once only", "a": A.get(nid), "b": B.get(nid)})
            else:
                why = "; ".join(r["why"] for r in readings[nid] if r.get("why")) or "the two labellers disagree"
                dis.append({"nct_id": nid, "why": why, "a": A[nid], "b": B[nid], "a_reading": readings[nid][0],
                            "b_reading": readings[nid][1]})
            continue
        # secondary answers count where both labellers give them and agree; the organiser's decided fields win
        sec, sd = (merge_secondary(secondary(A[nid], a.deadline, gr(nid)), secondary(B[nid], a.deadline, gr(nid)))
                   if both else (dict(none, subgroup_effects={}), []))
        if nid in dec_sec:
            sec, sd = apply_decision(sec, sd, dec_sec[nid])
        lab.update(sec)
        lab.update(label_deadline=a.deadline, labels_as_of=a.as_of)     # the pass these labels were read for
        labels.append(lab)
        if sd:
            sec_dis.append({"nct_id": nid, "fields": sd})
    n_both, n_agree = len(readings), len(agreed)
    with open(os.path.join(a.out, "labels.jsonl"), "w") as fh:
        fh.write("".join(json.dumps(l) + "\n" for l in labels))  # noqa: E741
    with open(os.path.join(a.out, "disagreements.jsonl"), "w") as fh:
        fh.write("".join(json.dumps(d) + "\n" for d in dis))
    with open(os.path.join(a.out, "secondary_disagreements.jsonl"), "w") as fh:
        fh.write("".join(json.dumps(d) + "\n" for d in sec_dis))
    resolved = [p for p in pairs if not (p[0] == "open" and p[1] == "open")]
    cats = ["open", "met", "not_met", "dropped", "conflict"]

    def kappa(ps):                     # Cohen's kappa of the two labellers' readings over the pairs given
        n = len(ps)
        if not n:
            return None
        po = sum(p[0] == p[1] for p in ps) / n
        pe = sum((sum(p[0] == c for p in ps) / n) * (sum(p[1] == c for p in ps) / n) for c in cats)
        return (po - pe) / (1 - pe) if pe < 1 else None
    info = {"as_of": a.as_of, "deadline": a.deadline, "n_labelled_twice": n_both, "n_agreed": n_agree,
            "n_with_a_result_found": len(resolved),
            "agreement_rate_where_a_result_was_found": (sum(p[2] for p in resolved) / len(resolved)) if resolved else None,
            "cohen_kappa_where_a_result_was_found": kappa(resolved),
            "cohen_kappa_all_trials_labelled_twice": kappa(pairs),
            "denominators": "agreement and the first kappa: trials where at least one labeller found a result "
                            "(n_with_a_result_found); the second kappa: every trial labelled twice (n_labelled_twice), "
                            "including those both found silent",
            "n_decided_by_organiser": len(dec), "n_left_for_organiser": len(dis),
            "n_trials_with_secondary_disagreements": len(sec_dis)}
    json.dump(info, open(os.path.join(a.out, "agreement.json"), "w"), indent=1)
    print(info)
