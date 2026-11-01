"""Question cards and the number questions of a round.

A round with question cards (``cards.jsonl`` in the round directory) asks four things per trial:

- ``p_met``: the probability that the trial meets its primary objective (every trial; the headline score);
- ``control``: the control arm's result, in the card's ``control_measure`` and ``unit``, as
  {"median", "low80", "high80"} (number questions only);
- ``effect``: the effect the trial will report, in the card's ``effect_measure`` (a ratio for time-to-event
  outcomes, a difference in percentage points for responder outcomes, a difference in means for continuous ones),
  also as {"median", "low80", "high80"} (number questions only);
- ``variability``: the between-patient standard deviation (continuous outcomes) or the number of primary events
  expected at the analysis (time-to-event outcomes); used only for the consistency check.

``main_risk`` (one of MAIN_RISKS) may be added; it is reported, never scored.

Round 1 adds, each shown beside the ranking and never part of the p_met ranking:

- ``subgroups``: the effect within two groups of patients, for each of the card's subgroups (``subgroups`` on the card:
  sex where both sexes are enrolled, and up to two more chosen per trial), on phase 3 cards with number questions;
- ``safety``: the % of patients who stop the study treatment because of an adverse event, in the card's experimental
  and control arms, as {"experimental": range, "control": range} (superiority and non-inferiority cards);
- ``p_key_secondary``: the probability that the card's key secondary endpoint shows a statistically significant
  benefit, given that its result is public by the deadline (cards with ``key_secondary``);
- ``p_next_step``: the probability of the card's next development step by the final deadline (``next_step``: "phase 3"
  for phase 2 trials, "application" for phase 3 trials).

A number question is a card with ``numbers == "yes"``. An entry answers either all of them or none. A number
question resolves when the trial publishes the number for the card's endpoint, arms and comparison by the round's
deadline; otherwise it is void. ``low80``, ``median`` and ``high80`` are the 10th, 50th and 90th percentiles, and
all three are scored with the percentile (pinball) loss. The score is ten times the summed loss, which equals the
interval score of the 80% range (Gneiting and Raftery 2007: the width plus 10 times any miss) plus 5 times the
distance from the median to the result; it is 15 times the weighted interval score of Bracher et al. (2021).
Ratios and times are scored on the log scale. To put trials with different units on one scale, the score is
divided by the width of the reference entry's 80% range for the same question; the reference is fixed before the
round opens, so the score stays proper. A range as wide as the reference's, with the median on the result, scores 1.
"""
from __future__ import annotations

import json
import math
import re

from scipy.stats import norm

KINDS = ("time_to_event", "responder", "continuous")
MAIN_RISKS = ("drug too weak", "control arm too strong", "wrong population", "endpoint or timing",
              "too small or underpowered", "safety or dropouts", "other")
CARD_KEYS = ("nct_id", "endpoint", "kind", "effect_measure", "better", "control_measure", "unit", "experimental_arm",
             "control_arm", "n_experimental", "n_control", "design", "margin", "alpha_two_sided", "numbers",
             "numbers_reason", "notes")
OPTIONAL_CARD_KEYS = ("subgroups", "design_basis", "measure_basis", "key_secondary", "next_step")
# design_basis: "stated" or "inferred" (from the trial's structure); measure_basis: "assumed" when the record does not
# fully state the measure (unit, time point, scale or form) and the card's notes give the reading assumed;
# subgroups: [{"id", "name", "groups": {key: label, key: label}, "basis"}]; key_secondary: {"endpoint", "basis"};
# next_step: one of NEXT_STEPS
DESIGNS = ("superiority", "non-inferiority", "equivalence", "none")
NEXT_STEPS = ("phase 3", "application")
KEY_SECONDARY_BASES = ("named", "first listed")   # named key secondary in the record, else the first listed
KEY_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,30}")         # subgroup ids and group keys (always fullmatch)
SAFETY_ARMS = ("experimental", "control")
ALPHA = 0.2                     # 80% ranges
Z80 = norm.ppf(0.9)
TIME_UNIT = re.compile(r"\b(months?|weeks?|days?|years?)\b", re.I)


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def load_cards(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                c = json.loads(line)
                out[str(c["nct_id"]).upper()] = c
    return out


def has_p_met(c: dict | None) -> bool:
    """Every design except "none" asks p_met, and so does every trial of a round without cards."""
    return not c or c.get("design") != "none"


def check_card(c: dict) -> list[str]:
    """Problems with a question card (empty if it is usable).

    design "none" marks a trial with no efficacy goal to meet (safety-only, pilot, descriptive): no p_met and no
    number questions, only the operations questions. design "equivalence" (biosimilars, bioequivalence, lot
    consistency) asks p_met (met = equivalence shown) but no number questions."""
    p = []
    missing = [k for k in CARD_KEYS if k not in c]
    if missing:
        p.append("missing " + ", ".join(missing))
    design = c.get("design")
    if design not in DESIGNS:
        p.append(f"design {design!r}")
    if design in ("equivalence", "none") and c.get("numbers") != "no":
        p.append(f"a {design} card has no number questions")
    p += _check_additions(c)
    if design == "none":
        return p
    if c.get("kind") not in KINDS:
        p.append(f"kind {c.get('kind')!r}")
    if design != "equivalence" and c.get("better") not in ("lower", "higher"):
        p.append(f"better {c.get('better')!r}")
    if c.get("numbers") not in ("yes", "no"):
        p.append(f"numbers {c.get('numbers')!r}")
    for k in ("n_experimental", "n_control"):       # may be null when the record gives no arm sizes
        v = num(c.get(k))
        if c.get(k) is not None and (v is None or v <= 0):
            p.append(f"{k} {c.get(k)!r}")
    a = num(c.get("alpha_two_sided"))
    if (a is None and not (design == "equivalence" and c.get("alpha_two_sided") is None)) or (a is not None and not 0 < a < 0.5):
        p.append(f"alpha_two_sided {c.get('alpha_two_sided')!r}")
    return p


def _check_additions(c: dict) -> list[str]:
    """Problems with the card's subgroups, key secondary endpoint and next step (the Round 1 additions)."""
    p = []
    sg = c.get("subgroups")
    if sg is not None:
        if not isinstance(sg, list) or not sg:
            p.append("subgroups must be a non-empty list")
        else:
            ids = []
            for s in sg:
                g = s.get("groups") if isinstance(s, dict) else None
                if (not isinstance(s, dict) or not KEY_RE.fullmatch(str(s.get("id") or "")) or not str(s.get("name") or "").strip()
                        or not isinstance(g, dict) or len(g) != 2
                        or not all(isinstance(k, str) and KEY_RE.fullmatch(k) and isinstance(v, str) and v.strip() for k, v in g.items())):
                    p.append(f"subgroup {str(s)[:80]!r}: needs an id, a name and exactly two groups with short keys")
                else:
                    ids.append(s["id"])
            if len(set(ids)) != len(ids):
                p.append("subgroup ids repeat")
            if c.get("numbers") != "yes":
                p.append("subgroups ride on number questions; this card has none")
    ks = c.get("key_secondary")
    if ks is not None and not (isinstance(ks, dict) and isinstance(ks.get("endpoint"), str) and ks["endpoint"].strip()):
        p.append("key_secondary needs an endpoint")
    elif ks is not None and ks.get("basis") not in KEY_SECONDARY_BASES:
        p.append(f"key_secondary basis {ks.get('basis')!r}: one of {', '.join(KEY_SECONDARY_BASES)}")
    if "subgroup" in c:                 # the old single-subgroup key: a cards file from before the additions
        p.append("the key \"subgroup\" is from an old cards file; subgroups are now a list (make_cards.py)")
    if c.get("next_step") is not None and c.get("next_step") not in NEXT_STEPS:
        p.append(f"next_step {c.get('next_step')!r}")
    if c.get("design") in ("none", "equivalence") and ks is not None:
        p.append(f"a {c.get('design')} card has no key secondary question")
    if c.get("design") == "none" and c.get("next_step") is not None:
        p.append("a card with no p_met has no next-step question")
    return p


def is_number_question(c: dict | None) -> bool:
    return bool(c) and c.get("numbers") == "yes"


def has_safety(c: dict | None) -> bool:
    """The safety question (stopping treatment for an adverse event, per arm): superiority and non-inferiority cards."""
    return bool(c) and c.get("design") in ("superiority", "non-inferiority")


def key_secondary(c: dict | None) -> str | None:
    """The card's key secondary endpoint (p_key_secondary is asked when there is one), or None."""
    ks = (c or {}).get("key_secondary")
    return ks["endpoint"] if c and has_p_met(c) and isinstance(ks, dict) and ks.get("endpoint") else None


def next_step(c: dict | None) -> str | None:
    """The next development step p_next_step asks about ("phase 3" or "application"), or None."""
    ns = (c or {}).get("next_step")
    return ns if c and has_p_met(c) and ns in NEXT_STEPS else None


def check_safety(d) -> str | None:
    """Why a `safety` answer is malformed, or None: {"experimental": range, "control": range}, in % of patients."""
    if not isinstance(d, dict):
        return "safety must be an object with experimental and control"
    for arm in SAFETY_ARMS:
        r = parse_range(d.get(arm))
        if r is None:
            return (f"safety {arm} needs median, low80 and high80, numbers with low80 <= median <= high80 and "
                    "low80 < high80")
        if not (0 <= r[1] and r[2] <= 100):
            return f"safety {arm} is a percentage of patients, from 0 to 100"
    extra = set(d) - set(SAFETY_ARMS)
    if extra:
        return f"safety has only experimental and control, not {sorted(extra)[0]}"
    return None


def log_scale(card: dict, which: str) -> bool:
    """Ratios (time-to-event effects) and times (control medians in months, weeks, days or years) use the log scale."""
    if card.get("kind") != "time_to_event":
        return False
    if which == "effect":
        return True
    return bool(TIME_UNIT.search(str(card.get("unit") or ""))) and "median" in str(card.get("control_measure") or "").lower()


def parse_range(d) -> tuple[float, float, float] | None:
    if not isinstance(d, dict):
        return None
    m, lo, hi = (num(d.get(k)) for k in ("median", "low80", "high80"))
    if m is None or lo is None or hi is None or not lo <= m <= hi or not lo < hi:
        return None
    return m, lo, hi


def check_range(d, card: dict, which: str) -> str | None:
    """Why an answer to a number question is malformed, or None."""
    r = parse_range(d)
    if r is None:
        return f"{which} needs median, low80 and high80, numbers with low80 <= median <= high80 and low80 < high80"
    lo, hi = r[1], r[2]
    kind = card.get("kind")
    if which == "effect" and kind == "time_to_event" and lo <= 0:
        return "effect is a ratio, so all three numbers must be above 0"
    if which == "control" and log_scale(card, "control") and lo <= 0:
        return "control is a time, so all three numbers must be above 0"
    if which == "control" and kind == "responder" and not (0 <= lo and hi <= 100):
        return "control is a percentage of patients, from 0 to 100"
    if which == "effect" and kind == "responder" and not (-100 <= lo and hi <= 100):
        return "effect is a difference in percentage points, from -100 to 100"
    return None


def _scaled(v: float, log: bool) -> float:
    return math.log(v) if log else v


def interval_score(r: tuple[float, float, float], y: float, log: bool) -> float:
    lo, hi, y = _scaled(r[1], log), _scaled(r[2], log), _scaled(y, log)
    return (hi - lo) + (2 / ALPHA) * max(0.0, lo - y) + (2 / ALPHA) * max(0.0, y - hi)


LEVELS = (ALPHA / 2, 0.5, 1 - ALPHA / 2)    # low80, median, high80 are these percentiles


def pinball(q: float, tau: float, y: float) -> float:
    return ((1.0 if y < q else 0.0) - tau) * (q - y)


def percentile_score(r: tuple[float, float, float], y: float, log: bool) -> float:
    """(2 / ALPHA) times the summed percentile loss of (low80, median, high80) at the 10th, 50th and 90th
    percentiles: the interval score of the range plus 5 times |result - median| (on the log scale if `log`)."""
    m, lo, hi = (_scaled(v, log) for v in r)
    y = _scaled(y, log)
    return (2 / ALPHA) * (pinball(lo, LEVELS[0], y) + pinball(m, LEVELS[1], y) + pinball(hi, LEVELS[2], y))


def width(r: tuple[float, float, float], log: bool) -> float:
    return _scaled(r[2], log) - _scaled(r[1], log)


SEX_SUBGROUP = {"id": "sex", "name": "sex", "groups": {"women": "women", "men": "men"},
                "basis": "every phase 3 trial with number questions that enrols both sexes"}


def subgroup_groups(c: dict | None) -> dict:
    """The subgroups a card asks the effect for: {subgroup id: (group key, group key)}, empty when it asks none.
    Subgroup questions ride on number questions: the effect, in the card's effect measure, within each group."""
    if not is_number_question(c) or not isinstance(c.get("subgroups"), list):
        return {}
    return {s["id"]: tuple(s["groups"]) for s in c["subgroups"]
            if isinstance(s, dict) and s.get("id") and isinstance(s.get("groups"), dict)}


def check_subgroups(d, card: dict) -> str | None:
    """Why a `subgroups` answer is malformed, or None: {subgroup id: {group key: range}} for every subgroup of the
    card, each range in the card's effect measure."""
    groups = subgroup_groups(card)
    if not isinstance(d, dict):
        return "subgroups must be an object with " + ", ".join(groups)
    for sid, gs in groups.items():
        dd = d.get(sid)
        if not isinstance(dd, dict):
            return f"subgroups: {sid} must be an object with " + " and ".join(gs)
        for g in gs:
            why = check_range(dd.get(g), card, "effect")
            if why:
                return f"subgroups {sid} {g}: {why.replace('effect', 'the effect', 1)}"
        extra = set(dd) - set(gs)
        if extra:
            return f"subgroups {sid}: {sorted(extra)[0]} is not one of its groups ({', '.join(gs)})"
    extra = set(d) - set(groups)
    if extra:
        return f"subgroups: {sorted(extra)[0]} is not one of this card's subgroups ({', '.join(groups)})"
    return None


TRIM = 0.05          # the trimmed mean (shown, not used for ranking) leaves out the top and bottom 5% of questions
FLOOR_PCT = 10       # no reference width counts as narrower than the 10th percentile of comparable widths


def summarise(vals: list) -> dict:
    """Plain mean (`score`: the average of a proper score, so it rewards honest ranges), with the median and the
    5%-trimmed mean shown beside it as robustness checks. Trimming is not used to rank: it drops exactly the large
    misses that honest wide ranges protect against, so it would reward ranges narrower than the forecaster believes."""
    if not vals:
        return {"score": None, "mean": None, "median": None, "trimmed_mean": None}
    v = sorted(vals)
    n = len(v)
    k = int(n * TRIM)
    core = v[k:n - k] if n - 2 * k > 0 else v
    mid = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    mean = sum(v) / n
    return {"score": mean, "mean": mean, "median": mid, "trimmed_mean": sum(core) / len(core)}


def _unit_scale(ref: dict | None, nid: str, card: dict) -> float | None:
    """A size in the question's own unit, for continuous cards (whose units differ from card to card): the reference
    entry's |control median| plus its control range width. None when the reference gives no control range."""
    rc = parse_range(((ref or {}).get(nid) or {}).get("control"))
    if rc is None:
        return None
    s = abs(rc[0]) + width(rc, False)
    return s if s > 0 else None


def width_floors(ref: dict | None, cards: dict) -> dict:
    """The smallest reference width that counts, per question: {(nct_id, "control"|"effect"): floor}.
    Time-to-event and responder widths share a unit within their kind and scale (a log-scale median time or hazard
    ratio, percentage points, or a count rate such as events per patient-year), so their floor is the FLOOR_PCT-th percentile of the reference's widths over the
    round's questions of that kind, scale and part.
    Continuous widths do not share a unit, so they are compared relative to each question's own size (_unit_scale):
    the floor is that question's size times the FLOOR_PCT-th percentile of width/size over the round's continuous
    questions. Computed from the frozen reference and the cards alone, so fixed before any result."""
    pools: dict = {}
    items = []
    for nid, card in cards.items():
        if not is_number_question(card):
            continue
        for which in ("control", "effect"):
            log = log_scale(card, which)
            rr = parse_range(((ref or {}).get(nid) or {}).get(which))
            if rr is None or (log and rr[1] <= 0):
                continue
            w = width(rr, log)
            if w <= 0:
                continue
            if card.get("kind") == "continuous":
                sc = _unit_scale(ref, nid, card)
                if sc is None:
                    continue
                pools.setdefault((which, "continuous"), []).append(w / sc)
                items.append((nid, which, "continuous", sc))
            else:
                # a time-to-event control can be a median time (log scale) or an event rate (percentage points):
                # widths share a unit only within the same scale, so the pool is split by it
                unit = str(card.get("unit") or "").lower()
                scale = "log" if log else ("percent" if "%" in unit or "percent" in unit else "rate")
                kind = (card.get("kind"), scale)
                pools.setdefault((which, kind), []).append(w)
                items.append((nid, which, kind, 1.0))
    pct = {}
    for g, ws in pools.items():
        ws = sorted(ws)
        pct[g] = ws[min(len(ws) - 1, int(len(ws) * FLOOR_PCT / 100))]
    return {(nid, which): pct[(which, kind)] * sc for nid, which, kind, sc in items}


def _scale(rr, log, floors, nid, which) -> float:
    w = width(rr, log)
    return max(w, (floors or {}).get((nid, which), 0.0))


def subgroup_effects(t: dict | None) -> dict:
    """The published subgroup effects of a label row: {subgroup id: {group key: value}}. Older label rows carry the
    sex subgroup as women_effect and men_effect."""
    t = t or {}
    out = {k: dict(v) for k, v in (t.get("subgroup_effects") or {}).items() if isinstance(v, dict)}
    if "sex" not in out and (t.get("women_effect") is not None or t.get("men_effect") is not None):
        out["sex"] = {"women": t.get("women_effect"), "men": t.get("men_effect")}
    return out


def subgroup_kind(card: dict | None, sid: str) -> str:
    """"sex"; "record" for a subgroup the record gives (a stratification factor or a subgroup it names); "experimental"
    for one chosen as commonly reported in the disease, whose cut-off a publication may well not use."""
    if sid == "sex":
        return "sex"
    for s in (card or {}).get("subgroups") or []:
        if isinstance(s, dict) and s.get("id") == sid:
            return "experimental" if str(s.get("basis") or "").startswith("commonly reported") else "record"
    return "record"


def subgroup_scores(preds: dict, ref: dict | None, cards: dict, truth: dict, floors: dict | None = None) -> dict:
    """Score the subgroup answers like effect answers: percentile score of each group's effect, scaled by the
    reference entry's range width for the same group (with the effect floor). truth: {nct_id: label row with
    "subgroup_effects": {subgroup id: {group key: value}}}. Shown beside the ranking, never part of it. The overall
    score covers sex and the subgroups the record gives; the commonly reported ones are shown apart, as experimental
    (by_kind: sex, record, experimental)."""
    vals, cover, n_pub, by = [], [], 0, {}
    for nid, t in truth.items():
        card = cards.get(nid)
        log = log_scale(card or {}, "effect")
        eff = subgroup_effects(t)
        for sid, gs in subgroup_groups(card).items():
            for g in gs:
                y = num((eff.get(sid) or {}).get(g))
                if y is None or (log and y <= 0):
                    continue
                n_pub += 1
                r = parse_range((((preds.get(nid) or {}).get("subgroups") or {}).get(sid) or {}).get(g))
                rr = (parse_range(((((ref or {}).get(nid) or {}).get("subgroups") or {}).get(sid) or {}).get(g))
                      if ref else None)
                if r is None or rr is None or (log and min(r[1], rr[1]) <= 0):
                    continue
                w = _scale(rr, log, floors, nid, "effect")
                if w <= 0:
                    continue
                s = percentile_score(r, y, log) / w
                kind = subgroup_kind(card, sid)
                by.setdefault(kind, []).append(s)
                if kind != "experimental":
                    vals.append(s)
                    cover.append(r[1] <= y <= r[2])
    return {"n_published": n_pub, "n_scored": len(vals), **summarise(vals),
            "coverage80": sum(cover) / len(cover) if cover else None,
            "by_kind": {k: {"n_scored": len(v), **summarise(v)} for k, v in sorted(by.items())}}


def per_question(preds: dict, ref: dict | None, cards: dict, truth: dict, floors: dict | None = None) -> dict:
    """The entry's score on each number question it can be scored on: {(nct_id, "control"|"effect"): (score, inside
    its 80% range)}, plus {("n_published", part): count}. A question counts when it is a number question, its value was
    published, and both the entry and the reference answered it; the percentile score is divided by the reference
    entry's range width, never less than the question's floor (width_floors)."""
    out = {}
    for which, field in (("control", "control_value"), ("effect", "effect_value")):
        n_pub = 0
        for nid, t in truth.items():
            card = cards.get(nid)
            y = num((t or {}).get(field))
            if not is_number_question(card) or y is None:
                continue
            log = log_scale(card, which)
            if log and y <= 0:
                continue
            n_pub += 1
            r = parse_range((preds.get(nid) or {}).get(which))
            rr = parse_range((ref or {}).get(nid, {}).get(which)) if ref else None
            if r is None or rr is None or (log and min(r[1], rr[1]) <= 0):
                continue
            w = _scale(rr, log, floors, nid, which)
            if w <= 0:
                continue
            out[(nid, which)] = (percentile_score(r, y, log) / w, r[1] <= y <= r[2])
        out[("n_published", which)] = n_pub
    return out


def number_scores(preds: dict, ref: dict | None, cards: dict, truth: dict, floors: dict | None = None) -> dict:
    """Score the number answers of one entry.

    truth: {nct_id: {"control_value": x or None, "effect_value": y or None}} for the trials scored in the round.
    Each question's percentile score is divided by the reference entry's range width (per_question), so 1 = a range as
    wide as the reference's with the median on the result; lower is better. `score` is the plain mean; the median and
    the 5%-trimmed mean are shown with it. Overall and for control and effect, with coverage of the 80% ranges and the
    counts."""
    q = per_question(preds, ref, cards, truth, floors)
    out, allv = {}, []
    for which in ("control", "effect"):
        got = [v for k, v in q.items() if k[0] != "n_published" and k[1] == which]
        vals = [s for s, _ in got]
        allv += vals
        out[which] = {"n_published": q[("n_published", which)], "n_scored": len(vals), **summarise(vals),
                      "coverage80": sum(c for _, c in got) / len(got) if got else None}
    out["n_scored"] = len(allv)
    out.update(summarise(allv))
    return out


def safety_scores(preds: dict, truth: dict) -> dict:
    """Score the safety answers: the percentile score of each arm's % of patients stopping treatment for an adverse
    event, in percentage points (a unit every trial shares, so no scaling). truth: {nct_id: label row with
    "safety_experimental" and "safety_control"}. Shown beside the ranking, never part of it."""
    out, allv = {}, []
    for arm in SAFETY_ARMS:
        vals, cover, n_pub = [], [], 0
        for nid, t in truth.items():
            y = num((t or {}).get(f"safety_{arm}"))
            if y is None:
                continue
            n_pub += 1
            r = parse_range(((preds.get(nid) or {}).get("safety") or {}).get(arm))
            if r is None:
                continue
            vals.append(percentile_score(r, y, False))
            cover.append(r[1] <= y <= r[2])
        allv += vals
        out[arm] = {"n_published": n_pub, "n_scored": len(vals), **summarise(vals),
                    "coverage80": sum(cover) / len(cover) if cover else None}
    out["n_scored"] = len(allv)
    out.update(summarise(allv))
    return out


def implied_p_met(f: dict, c: dict) -> float | None:
    """P(the trial reports success) implied by the entry's own control, effect and variability answers and the card's
    design (normal approximation; non-inferiority against the card's margin). None when an input is missing."""
    kind = c.get("kind")
    ne, nc = num(c.get("n_experimental")), num(c.get("n_control"))
    if not ne or not nc or kind not in KINDS or c.get("design") not in ("superiority", "non-inferiority"):
        return None
    alpha = num(c.get("alpha_two_sided")) or 0.05
    z = norm.ppf(1 - alpha / 2)
    better = c.get("better")
    ef = parse_range(f.get("effect"))
    if ef is None or better not in ("lower", "higher"):
        return None
    log = kind == "time_to_event"
    if log and ef[1] <= 0:
        return None
    mu = _scaled(ef[0], log)
    sig = max(width(ef, log) / (2 * Z80), 1e-9)
    if kind == "time_to_event":
        d = num(f.get("variability"))
        if not d or d <= 0:
            return None
        r = ne / (ne + nc)
        se = math.sqrt(1 / (d * r * (1 - r)))
    elif kind == "continuous":
        s = num(f.get("variability"))
        if not s or s <= 0:
            return None
        se = s * math.sqrt(1 / ne + 1 / nc)
    else:
        cf = parse_range(f.get("control"))
        if cf is None:
            return None
        pc = min(max(cf[0] / 100, 0.001), 0.999)
        pe = min(max(pc + ef[0] / 100, 0.001), 0.999)
        se = 100 * math.sqrt(pc * (1 - pc) / nc + pe * (1 - pe) / ne)
    margin = num(c.get("margin"))
    if c.get("design") == "non-inferiority" and margin is None:
        return None                     # success is defined by a margin the card does not know
    if c.get("design") == "non-inferiority":
        m = abs(math.log(margin)) if log and margin > 0 else (None if log else abs(margin))
        if m is None:
            return None
        t = (m - z * se) if better == "lower" else (-m + z * se)
    else:
        t = -z * se if better == "lower" else z * se
    return float(norm.cdf((t - mu) / sig) if better == "lower" else 1 - norm.cdf((t - mu) / sig))


def consistency(preds: dict, cards: dict, ids) -> dict:
    """How far the entry's stated p_met is from the p_met its own numbers imply (reported, never scored)."""
    gaps = []
    for nid in ids:
        f, c = preds.get(nid), cards.get(nid)
        if not f or not is_number_question(c):
            continue
        p = num(f.get("p_met"))
        q = implied_p_met(f, c)
        if p is not None and q is not None:
            gaps.append(abs(p - q))
    return {"n": len(gaps), "mean_abs_gap": sum(gaps) / len(gaps) if gaps else None,
            "share_gap_over_0.2": sum(g > 0.2 for g in gaps) / len(gaps) if gaps else None}
