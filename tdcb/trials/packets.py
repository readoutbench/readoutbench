"""Question packets for Track C: a registry record rendered as text, without any result.

Left out on purpose: the has-results flag, the registry URL and any posted results. The
overall status is left out of the record part; rounds with operations questions state the
launch-day status in the operations section (it is public on the snapshot date, and the
round leaves out stopped trials). What remains is what anyone could read in the registry
before the readout.
"""
from __future__ import annotations

import re

TTE = re.compile(r"\b(overall survival|progression[- ]free|event[- ]free|disease[- ]free|recurrence[- ]free|"
                 r"metastasis[- ]free|invasive disease[- ]free|failure[- ]free|time to|survival|OS|PFS|EFS|DFS|"
                 r"RFS|MFS|iDFS|TTP|TTF)\b", re.IGNORECASE)
NON_TTE = re.compile(r"\b(response rate|objective response|ORR|pathologic(al)? complete response|pCR|"
                     r"complete remission|MRD|minimal residual|best overall response|rate of)\b", re.IGNORECASE)
LEAKY_WORDS = re.compile(r"\b(met (its|the) primary endpoint|did not meet|topline|statistically significant "
                         r"improvement was|results were presented)\b", re.IGNORECASE)


def _clip(text, n: int) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", str(text)).strip()
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut + " [...]"


def endpoint_kind(rec: dict) -> str:
    """'time_to_event' when the first primary outcome is a time-to-event endpoint, else 'other'."""
    po = (rec.get("primary_outcomes") or [{}])[0] or {}
    text = f"{po.get('measure') or ''} {po.get('description') or ''}"
    if NON_TTE.search(po.get("measure") or "") and not TTE.search(po.get("measure") or ""):
        return "other"
    return "time_to_event" if TTE.search(text) else "other"


def long_date(d: str | None, default: str) -> str:
    """2027-03-31 -> 31 March 2027 (the packets' dates come from the round's manifest)."""
    import datetime as _dt
    try:
        x = _dt.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return default
    return f"{x.day} {x.strftime('%B')} {x.year}"


def card_section(card: dict, deadline: str | None = None, final_deadline: str | None = None) -> list[str]:
    """The question card as packet lines: what the number questions refer to."""
    def v(k):
        x = card.get(k)
        return "not stated" if x in (None, "") else str(x)
    if card.get("design") == "none":
        return ["", "## Question card",
                f"This trial has no efficacy goal to meet ({v('numbers_reason')}), so neither `p_met` nor number "
                "questions are asked for it: only the operations questions below."]
    if card.get("design") == "equivalence":
        L = ["", "## Question card",
             "An equivalence trial. Here `p_met` is the probability that the trial shows equivalence (bioequivalence, "
             "biosimilarity or lot consistency) on its primary outcomes as its protocol defines it; with several "
             "primary outcomes, all must succeed. No number questions are asked.",
             f"- Endpoint: {v('endpoint')}",
             f"- Measure: {v('effect_measure')}",
             f"- Margins: {v('margin') if card.get('margin') not in (None, '') else 'not stated in the record; the protocol defines them'}",
             f"- Test product: {v('experimental_arm')}",
             f"- Reference product: {v('control_arm')}"]
        L += more_questions(card, deadline, final_deadline)
        if card.get("notes"):
            L.append(f"- Notes: {_clip(card['notes'], 600)}")
        return L
    basis = card.get("design_basis")
    design = v("design") + (" (the record does not state the design; the card infers it from the trial's structure)"
                            if basis == "inferred" else "")
    if card.get("design") == "non-inferiority":
        design += f"; margin {v('margin')}" if card.get("margin") not in (None, "") else "; margin not stated in the record"
    L = ["", "## Question card",
         "The card fixes what the number questions refer to. `p_met` follows the round's rules for all of the "
         "trial's primary outcomes, and is met when the sponsor reports the trial's own primary hypothesis met "
         "(superiority, or non-inferiority against its own pre-specified margin); if that differs from the card's "
         "design, the trial's own hypothesis decides.",
         f"- Endpoint: {v('endpoint')}",
         f"- Kind: {v('kind').replace('_', '-')}; design: {design}"
         + f"; two-sided significance level: {v('alpha_two_sided')}",
         f"- Experimental arm: {v('experimental_arm')}",
         f"- Control arm: {v('control_arm')}",
         f"- Planned patients: {v('n_experimental')} experimental, {v('n_control')} control"]
    if card.get("numbers") == "yes" and card.get("measure_basis") == "assumed":
        L.append("- Measure: the record does not fully state the measure (its unit, time point, scale or form); the "
                 "card's reading, given in the notes, is assumed, and the number questions refer to it. A result "
                 "published only in another form leaves the numbers void; p_met is not affected.")
    if card.get("numbers") == "yes":
        L += [f"- Number questions: yes. Give `control` as the {v('control_measure')} ({v('unit')}), and `effect` as "
              f"the {v('effect_measure')}; each as a median and an 80% range. {v('better').capitalize()} values of "
              "the effect favour the experimental arm. Each is the number the trial will publish, given that it "
              "reports after the round closes and publishes that number by the deadline of the pass that scores it "
              f"({long_date(deadline, 'the deadline')} for the ranking); a number published later is not scored in "
              "that pass, and whether and when a number is published can depend on the result."]
        sg = [x for x in (card.get("subgroups") or []) if isinstance(x, dict) and isinstance(x.get("groups"), dict)]
        if sg:
            L.append("- Subgroup questions: yes. Give `subgroups` as {" + ", ".join(
                f"\"{x['id']}\": {{" + ", ".join(f"\"{k}\": …" for k in x["groups"]) + "}" for x in sg)
                + "}: the same effect within each group, each as a median and an 80% range. The groups:")
            for x in sg:
                L.append(f"  - `{x['id']}` ({_clip(x.get('name'), 120)}): "
                         + "; ".join(f"`{k}` = {_clip(lab, 120)}" for k, lab in x["groups"].items()))
    else:
        L += [f"- Number questions: none for this trial ({v('numbers_reason')})."]
    L += more_questions(card, deadline, final_deadline)
    if card.get("notes"):
        L.append(f"- Notes: {_clip(card['notes'], 600)}")
    return L


def more_questions(card: dict, deadline: str | None = None, final_deadline: str | None = None) -> list[str]:
    """The card's other questions: safety, the key secondary endpoint and the next development step."""
    L = []
    by = long_date(final_deadline, "31 December 2027")
    if card.get("design") in ("superiority", "non-inferiority"):
        L.append("- Safety question: give `safety` as {\"experimental\": …, \"control\": …}: the % of patients in "
                 "each of the two arms above who stop the study treatment (any part of it, for good) because of an "
                 "adverse event, each as a median and an 80% range (0 to 100). It resolves on the first source by the "
                 "deadline that gives the share stopping any study treatment for an adverse event; if none does, the "
                 "share stopping the experimental drug or its placebo; if none, the share leaving the study for an "
                 "adverse event. For an arm with nothing to stop (surveillance, no treatment, delayed treatment, or "
                 "a single dose given at the start), it is the share leaving the study for an adverse event. Void if "
                 "none of these is published by the deadline.")
    ks = card.get("key_secondary")
    if isinstance(ks, dict) and ks.get("endpoint"):
        L.append(f"- Key secondary endpoint: {_clip(ks['endpoint'], 300)}"
                 + (" (named as key in the record)" if ks.get("basis") == "named" else
                    " (chosen by the round's rule: the first efficacy secondary outcome the record lists that is not "
                    "the primary repeated: at another time, in another form (percent instead of absolute change, "
                    "a count of events instead of the time to the first), by another assessor, in another analysis "
                    "set or in a subset; a responder analysis of the primary's measure, the share of patients "
                    "reaching a threshold, counts as an endpoint of its own)")
                 + ". Give `p_key_secondary`: the probability that it is met, given that its result is public by the "
                   "deadline. Met: a source reports it significant in favour of the experimental arm (p below the "
                   "trial's level, two-sided 0.05 if none is stated, or a 95% interval that excludes no effect) and "
                   "does not say it was outside formal testing. Not met: any other reported result, including one "
                   "reported as not significant, as not formally tested (the testing order stopped, the primary was "
                   "not met, or it was outside the testing plan), or without a test. Void: no result public, or a "
                   "result reported only as immature with a later formal analysis planned. A benefit means "
                   "superiority, on non-inferiority cards too.")
    ns = card.get("next_step")
    evidence = ("The announcement must name this trial among the application's bases, or the sponsor must have said "
                "this trial supports it. ")
    if ns == "phase 3":
        L.append(f"- Next step: give `p_next_step`: the probability that, after the launch day and by {by}, a phase 3 "
                 "trial of the experimental drug in the same disease (a condition listed in this trial's record, at "
                 "any stage or line of therapy) is registered in a public trial registry or announced as started "
                 "(a phase 3 registered before the launch day does not count, nor do plans to start), or a marketing "
                 "application that rests at least in part on this trial is announced as submitted, accepted for "
                 f"review or approved. {evidence}Whatever this trial's result. Void if its primary result comes out "
                 "before the round closes.")
    elif ns == "application":
        L.append(f"- Next step: give `p_next_step`: the probability that, after the launch day and by {by}, a "
                 "marketing application (new or supplemental, in any country) that rests at least in part on this "
                 f"trial is announced as submitted, accepted for review or approved. {evidence}Whatever this trial's "
                 "result. Void if its primary result comes out before the round closes.")
    return L


def ops_section(row: dict, read_date: str, deadline: str | None = None, early_deadline: str | None = None,
                final_deadline: str | None = None) -> list[str]:
    """The operations questions of a trial as packet lines (see operations.py)."""
    from .operations import LATE_DAYS, STATUS_WORDS, parse_date
    import datetime as _dt
    pcd = row.get("primary_completion_date")
    st = STATUS_WORDS.get(str(row.get("status") or "").upper(), str(row.get("status") or "not stated").lower())
    L = ["", "## Operations questions",
         f"Answered from this trial's ClinicalTrials.gov record as it stands on {read_date}. On launch day the record "
         f"says: status {st}; primary completion (as registered) {pcd or 'not stated'}."]
    if "p_late" in row["questions"]:
        due = parse_date(pcd) + _dt.timedelta(days=LATE_DAYS)
        L.append(f"- `p_late` (late per the registry): the probability that primary completion comes more than "
                 f"{LATE_DAYS} days late as the registry shows it: on {read_date} the record gives a primary "
                 f"completion date after {due.isoformat()}, or the trial is still recruiting after that day. Void if "
                 f"the trial has stopped, or if its date is then still marked estimated although more than "
                 f"{LATE_DAYS} days past.")
    else:
        L.append("- `p_late`: not asked (the registered primary completion date has passed).")
    L += ["- `p_stopped`: the probability that the trial is terminated, suspended or withdrawn.",
          "- `p_posted`: the probability that results are posted on ClinicalTrials.gov."]
    if "p_public" in row["questions"]:
        three = "p_public_mar" in row["questions"]
        L.append(f"- `p_public` (decided by the round's labellers, like `p_met`, not from the registry): the "
                 f"probability that a public statement on the trial's primary result comes out by "
                 f"{deadline or 'the deadline'}, so that `p_met` is scored: a press release, filing, congress "
                 "abstract, paper or results posted on ClinicalTrials.gov, whether it says the primary objective was "
                 "met or not or only calls the result positive (which counts as not met); a stop with no public "
                 "reason counts too. Void if the statement comes out before the round closes."
                 + (f" Give it also by {long_date(early_deadline, 'the early deadline')} (`p_public_mar`) and by "
                    f"{long_date(final_deadline, 'the final deadline')} (`p_public_dec`), with `p_public_mar` <= "
                    "`p_public` <= `p_public_dec`." if three else ""))
    if "p_amended" in row["questions"]:
        L.append(f"- `p_amended` (decided by the round's labellers, who compare the record frozen in the round on "
                 f"the launch day with the record as it stands on {read_date}): the probability that the record's "
                 "primary outcomes change in substance in between: a primary outcome measure added or removed "
                 "(splitting or merging entries without changing the measures does not count); the measured "
                 "variable or its scale changed; a fixed assessment time changed (week 24 to week 52, say); or the "
                 "comparison changed (superiority to non-inferiority). A change in the maximum follow-up of a "
                 "time-to-event outcome, rewording and added detail do not count. Void if the record cannot be "
                 "fetched on that day.")
    return L


def render(rec: dict, snapshot_date: str | None = None, card: dict | None = None, ops: dict | None = None,
           ops_read: str | None = None, deadline: str | None = None, early_deadline: str | None = None,
           final_deadline: str | None = None) -> str:
    """The packet. With a question card (rounds with number questions) the header names no phase, the hazard-ratio
    line is left out, and the card is appended; then the operations questions, if the round asks them."""
    snap = snapshot_date or (rec.get("fetched_at") or "")[:10]
    what = ("how this randomized trial runs" if card and card.get("design") == "none"
            else f"the result of this randomized {'' if card else 'phase 3 '}trial")
    L = [f"# Trial {rec['nct_id']}",
         f"Forecast {what}. The information below comes "
         f"from its ClinicalTrials.gov record (snapshot {snap}); no result is included.", "",
         "## Trial"]
    L.append(f"- Title: {_clip(rec.get('title'), 400)}")
    if rec.get("brief_title") and rec.get("brief_title") != rec.get("title"):
        L.append(f"- Short title: {_clip(rec.get('brief_title'), 300)}")
    if rec.get("acronym") and str(rec.get("acronym")) not in ("None", "null"):
        L.append(f"- Acronym: {rec['acronym']}")
    phases = rec.get("phase") or []
    L.append(f"- Phase: {', '.join(p.replace('PHASE', 'Phase ') for p in phases) or 'not stated'}")
    sp = rec.get("sponsor") or "not stated"
    collab = rec.get("collaborators")
    L.append(f"- Sponsor: {sp}" + (f"; collaborators: {collab}" if collab and collab != "None" else ""))
    L.append(f"- Conditions: {'; '.join(rec.get('conditions') or []) or 'not stated'}")
    L.append(f"- Interventions: {'; '.join(rec.get('interventions') or []) or 'not stated'}")
    if rec.get("enrollment"):
        L.append(f"- Enrollment: {rec['enrollment']}")
    countries = rec.get("countries") or []
    if rec.get("n_locations"):
        shown = ", ".join(countries[:12]) + (", ..." if len(countries) > 12 else "")
        L.append(f"- Sites: {rec['n_locations']} in {len(countries)} countries ({shown})")
    L.append(f"- Start: {rec.get('start_date') or 'not stated'}; primary completion (as registered): "
             f"{rec.get('primary_completion_date') or 'not stated'}; study completion (as registered): "
             f"{rec.get('completion_date') or 'not stated'}")
    kind = endpoint_kind(rec)
    if card is None:
        L.append("- First primary endpoint: " + ("time-to-event, so give a hazard ratio" if kind == "time_to_event"
                                                  else "not time-to-event, so no hazard ratio is asked"))
    L += ["", "## Primary outcome(s)"]
    for i, o in enumerate(rec.get("primary_outcomes") or [], 1):
        line = f"{i}. {_clip(o.get('measure'), 300)}"
        if o.get("time_frame"):
            line += f" (time frame: {_clip(o.get('time_frame'), 150)})"
        L.append(line)
        if o.get("description"):
            L.append(f"   {_clip(o.get('description'), 500)}")
    sec = rec.get("secondary_outcomes") or []
    if sec:
        L += ["", "## Main secondary outcomes"]
        L += [f"- {_clip(o.get('measure'), 200)}" for o in sec[:6]]
        if len(sec) > 6:
            L.append(f"- and {len(sec) - 6} more")
    if rec.get("brief_summary"):
        L += ["", "## Summary", _clip(rec["brief_summary"], 1500)]
    dd = rec.get("detailed_description")
    if dd and str(dd) != "None":
        L += ["", "## Detailed description (registry)", _clip(dd, 1500)]
    if rec.get("eligibility_criteria"):
        L += ["", "## Eligibility (abridged)", _clip(rec["eligibility_criteria"], 1800)]
    if card is not None:
        L += card_section(card, deadline, final_deadline)
    if ops is not None:
        L += ops_section(ops, ops_read or "the read date", deadline, early_deadline, final_deadline)
    return "\n".join(L).rstrip() + "\n"


def leak_problems(text: str) -> list[str]:
    """Phrases that would only appear once a result is known."""
    return [m.group(0) for m in LEAKY_WORDS.finditer(text)]
