"""Round 1 (rebuilt): one question card per trial of the list.

usage: python3 -I make_cards.py <questions.json> <main cards.jsonl> <records.jsonl ...> --out <cards.jsonl>
                               [--additions <card additions.jsonl>]
- "main" trials: their card from the card agents (card_instructions.md, reviewed and fixed), with design_basis for
  non-inferiority cards and measure_basis "assumed" where the card's notes say the measure's unit, time point or form
  was assumed; the subgroups (sex for phase 3 cards with number questions that enrol both sexes, then the subgroups
  the card-additions agents chose, card_additions_instructions.md, on phase 3 cards with number questions); the key
  secondary endpoint those agents chose; and the next step asked about ("application" for phase 3 trials, "phase 3"
  for the others);
- "equivalence" trials: data/cards_equivalence.jsonl (written by hand from the records; design "equivalence");
- "operations only" trials: a card with design "none", the first primary outcome as the endpoint, and the reason the
  trial has no efficacy goal to meet.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tdcb.trials import numbers as tnum  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NI_WORDS = re.compile(r"non-?inferior|noninferior|not inferior|at least as (effective|good)", re.I)


def design_basis(rec: dict) -> str:
    """'stated' when the record's titles, summaries or primary outcomes say non-inferiority, else 'inferred'."""
    text = json.dumps({k: rec.get(k) for k in ("title", "brief_title", "brief_summary", "detailed_description",
                                               "primary_outcomes")})
    return "stated" if NI_WORDS.search(text) else "inferred"


# measure_basis: "assumed" when the card's own notes say its writer chose the measure's unit, time point, scale or
# form (absolute or percent change) because the record does not state it; the packet then says so
_WHAT = re.compile(r"\bunits?\b|time ?point|\bweek\b|\bmonth|\bday \d|percent(age)? change|absolute change|change from "
                   r"baseline|\bchange\b|transform|\bper (year|month|week|day)\b|measure|\bscale\b|\bscore\b|endpoint|"
                   r"outcome|definition|defined", re.I)
_HOW = re.compile(r"assum|not stated|taken as|read as|interpreted|inferred|unclear|not specified|unspecified|presum|"
                  r"not given|not defined|not reported in the record|without saying|does not say", re.I)
# choices about arms, doses, design or which primary outcome comes first are not about the measure
_SKIP = re.compile(r"allocation|split evenly|randomi[sz]ation ratio|\bdose|\barms?\b|cohort|placebo|design|hypothesis|"
                   r"non-inferiority|superiority|margin|subgroup|first listed|listed first|first efficacy primary|"
                   r"main efficacy primary|second primary|co-primary|dual primary|alpha", re.I)


def measure_basis(card: dict) -> str | None:
    """'assumed' for a card with number questions whose notes record an assumption about the measure, else None.
    Each sentence is read whole and clause by clause (split at semicolons)."""
    if card.get("numbers") != "yes":
        return None
    for sentence in re.split(r"(?<=\.)\s+", card.get("notes") or ""):
        if any(_WHAT.search(x) and _HOW.search(x) and not _SKIP.search(x)
               for x in [sentence] + re.split(r";\s*", sentence)):
            return "assumed"
    return None


REASONS = {
    "safety or pharmacokinetics only": "the primary outcomes are safety or drug levels only",
    "no efficacy hypothesis (descriptive only)": "the efficacy outcomes are descriptive, with no hypothesis",
    "no comparison group": "there is no control group to compare with",
    "doses or schedules compared with each other, no control and no stated hypothesis (rule 4)":
        "doses or schedules are compared with each other, with no control and no stated hypothesis",
    "bioequivalence or manufacturing (lot consistency)": "no equivalence objective or margin is stated",
}


def reason(why: str) -> str:
    why = (why or "").strip()
    if why.startswith("other: "):
        why = why[len("other: "):]
    return REASONS.get(why, why).replace("(", "").replace(")", "")


def load(path):
    return {json.loads(line)["nct_id"]: json.loads(line) for line in open(path) if line.strip()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("questions")
    ap.add_argument("main_cards")
    ap.add_argument("records", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--additions", help="key secondary endpoints and subgroups (card_additions_instructions.md)")
    a = ap.parse_args()
    adds = load(a.additions) if a.additions else {}
    qs = json.load(open(a.questions))
    main = load(a.main_cards)
    equiv = load(os.path.join(HERE, "data", "cards_equivalence.jsonl"))
    recs = {}
    for p in a.records:                          # later files win, as in stage_round.py
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                recs[r["nct_id"]] = r
    out, problems = [], {}
    for q in qs:
        n = q["nct_id"]
        if q["questions"] == "main":
            c = {k: v for k, v in main[n].items() if k not in ("subgroup", "subgroups", "key_secondary")}
            # subgroups (the effect within two groups of patients): phase 3 cards with number questions; sex where
            # both sexes are enrolled, then up to two more chosen per trial. A review fix in the main card (its own
            # "subgroups" or "key_secondary", null or [] for none) wins over the additions for that field.
            if "subgroups" in main[n]:
                if main[n]["subgroups"]:
                    c["subgroups"] = main[n]["subgroups"]
            elif "PHASE3" in q["phase"] and c.get("numbers") == "yes":
                sg = [tnum.SEX_SUBGROUP] if str(recs[n].get("sex") or "").upper() == "ALL" else []
                sg += [x for x in (adds.get(n) or {}).get("subgroups") or [] if x.get("id") != "sex"][:2]
                if sg:
                    c["subgroups"] = sg
            ks = main[n]["key_secondary"] if "key_secondary" in main[n] else (adds.get(n) or {}).get("key_secondary")
            if isinstance(ks, dict) and ks.get("endpoint"):
                basis = ks.get("basis") if ks.get("basis") in tnum.KEY_SECONDARY_BASES else "first listed"
                c["key_secondary"] = {"endpoint": ks["endpoint"], "basis": basis}
            if c.get("design") == "non-inferiority":   # did the record state the design, or did the card infer it?
                c["design_basis"] = design_basis(recs[n])
            if measure_basis(c):                       # did the card's writer have to assume the measure?
                c["measure_basis"] = measure_basis(c)
        elif q["questions"] == "equivalence":
            c = dict(equiv[n])
        else:
            po = (recs[n].get("primary_outcomes") or [{}])[0]
            c = {k: None for k in tnum.CARD_KEYS}
            c.update(nct_id=n, endpoint=(po.get("measure") or "not stated")[:300], design="none", numbers="no",
                     numbers_reason=reason(q.get("why_no_p_met")))
        if tnum.has_p_met(c):                 # the next development step: a marketing application after a phase 3
            c["next_step"] = "application" if "PHASE3" in q["phase"] else "phase 3"
        if tnum.check_card(c):
            problems[n] = tnum.check_card(c)
        out.append({k: c.get(k) for k in tnum.CARD_KEYS} | {k: c[k] for k in tnum.OPTIONAL_CARD_KEYS if c.get(k)})
    if problems:
        raise SystemExit(f"{len(problems)} unusable cards, e.g. {list(problems.items())[:3]}")
    with open(a.out, "w") as fh:
        for c in out:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(len(out), "cards;", sum(c["design"] == "none" for c in out), "operations only;",
          sum(c["design"] == "equivalence" for c in out), "equivalence;",
          sum(c["numbers"] == "yes" for c in out), "with number questions;",
          sum(bool(c.get("subgroups")) for c in out), "with subgroup questions",
          f"({sum(len(c.get('subgroups') or []) for c in out)} subgroups);",
          sum(bool(c.get("key_secondary")) for c in out), "with a key secondary endpoint;",
          sum(c.get("measure_basis") == "assumed" for c in out), "with the measure assumed")
