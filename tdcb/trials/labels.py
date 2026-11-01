"""Trial result labels: reading, checking and sorting them into question sets.

One label per trial (JSON Lines), as written by the labelling pass:
nct_id, reported (yes/no/unclear), first_public_date, clear_date (when it became clear whether the primary objective
was met; rounds apply it per pass in finalize_labels.py), met (yes/no/not_reported), endpoint,
hr, hr_ci_low, hr_ci_high, p_value, interim, sources, quote, confidence, notes; and, for rounds with question cards,
control_value and effect_value: the published numbers for the card's control measure and effect measure (null when
not published); women_effect and men_effect: the published effect within each sex, for subgroup questions (Round 1
labels give every subgroup in subgroup_effects: {subgroup: {group: value}}); safety_experimental and safety_control:
the % stopping treatment for an adverse event per arm; key_secondary_met: 1 or 0 (the round's labels, from
finalize_labels.py, already read at the pass's deadline).
Later files override earlier ones, so corrections from a manual review go last.
"""
from __future__ import annotations

import datetime as dt
import json
import math

KEYS = ["nct_id", "reported", "first_public_date", "clear_date", "vague_at_deadline", "met", "endpoint", "hr",
        "hr_ci_low", "hr_ci_high",
        "p_value", "interim", "sources", "quote", "confidence", "notes", "control_value", "effect_value",
        "women_effect", "men_effect", "subgroup_effects", "safety_experimental", "safety_control",
        "key_secondary_met", "label_deadline", "labels_as_of"]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _date(x):
    try:
        return dt.date.fromisoformat(str(x)[:10]).isoformat()
    except ValueError:
        return None


def normalise(o: dict) -> dict:
    lab = {k: o.get(k) for k in KEYS}
    lab["nct_id"] = str(lab["nct_id"] or "").strip().upper()
    for k in ("reported", "met", "confidence"):
        lab[k] = str(lab[k] or "").strip().lower() or None
    lab["first_public_date"] = _date(lab["first_public_date"]) if lab["first_public_date"] else None
    lab["clear_date"] = _date(lab["clear_date"]) if lab["clear_date"] else None
    for k in ("label_deadline", "labels_as_of"):      # the pass the label was read for (finalize_labels.py)
        lab[k] = _date(lab[k]) if lab[k] else None
    for k in ("hr", "hr_ci_low", "hr_ci_high", "control_value", "effect_value", "women_effect", "men_effect",
              "safety_experimental", "safety_control"):
        lab[k] = _num(lab[k])
    lab["key_secondary_met"] = lab["key_secondary_met"] if lab["key_secondary_met"] in (0, 1) else None
    se = lab["subgroup_effects"]
    lab["subgroup_effects"] = ({str(s): {str(g): v for g, x in d.items() if (v := _num(x)) is not None}
                                for s, d in se.items() if isinstance(d, dict)} if isinstance(se, dict) else None)
    hr, lo, hi = lab["hr"], lab["hr_ci_low"], lab["hr_ci_high"]
    if hr is not None and not (0.05 < hr < 5):
        lab["hr"] = hr = None
    if hr is None or lo is None or hi is None or not (lo <= hr <= hi):
        lab["hr_ci_low"] = lab["hr_ci_high"] = None
    if not isinstance(lab["sources"], list):
        lab["sources"] = [lab["sources"]] if lab["sources"] else []
    return lab


def load_labels(paths: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(o, dict) and o.get("nct_id"):
                    lab = normalise(o)
                    out[lab["nct_id"]] = {**out.get(lab["nct_id"], {}), **{k: v for k, v in lab.items()
                                                                          if k in o}}
    return out


def assign(lab: dict | None, cutoff: str) -> tuple[str, str]:
    """(set, reason). Sets: post_cutoff, pre_cutoff, open, excluded."""
    if lab is None:
        return "excluded", "no label"
    if lab.get("reported") == "no":
        return "open", "no public result yet"
    if lab.get("reported") != "yes":
        return "excluded", f"reported={lab.get('reported')}"
    if lab.get("met") not in ("yes", "no"):
        return "excluded", f"met={lab.get('met')}"
    if not lab.get("first_public_date"):
        return "excluded", "no first-disclosure date"
    if lab.get("confidence") not in ("high", "medium"):
        return "excluded", f"confidence={lab.get('confidence')}"
    return ("post_cutoff" if lab["first_public_date"] > cutoff else "pre_cutoff"), "resolved"
