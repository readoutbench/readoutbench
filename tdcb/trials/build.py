"""Build the Track C question set from registry records and result labels.

Output (``out``):
  packets/C/post_cutoff/   trials whose result became public after the cutoff (clean for a model with that cutoff)
  packets/C/pre_cutoff/    trials reported before the cutoff (a model may have read the result: a memory check,
                           and the training data for the baselines)
  packets/C/open/          trials with no public result yet: forecasts frozen now, scored when results arrive
  private/key_C.json       labels with dates and sources (do not show to a system being evaluated)
  manifest_C.json          counts, cutoff, snapshot date, exclusions
"""
from __future__ import annotations

import json
import os

from .labels import assign, load_labels
from .packets import endpoint_kind, leak_problems, render
from .records import load_registry

SETS = ("post_cutoff", "pre_cutoff", "open")


def read_exclusions(path: str | None) -> dict[str, str]:
    """NCT id -> reason, from a text file with one 'NCT... reason' per line ('#' starts a comment)."""
    out: dict[str, str] = {}
    if not path:
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if line:
                nct, _, why = line.partition(" ")
                out[nct.upper()] = why.strip() or "excluded by list"
    return out


def build(registry_dir: str, label_paths: list[str], out: str, cutoff: str = "2026-06-30",
          snapshot_date: str | None = None, exclude: dict[str, str] | None = None) -> dict:
    recs = load_registry(registry_dir)
    exclude = exclude or {}
    labels = load_labels(label_paths)
    for s in SETS:
        os.makedirs(os.path.join(out, "packets", "C", s), exist_ok=True)
    os.makedirs(os.path.join(out, "private"), exist_ok=True)
    key, excluded, leaks = [], [], {}
    counts = {s: 0 for s in SETS}
    for nct in sorted(recs):
        rec = recs[nct]
        if nct in exclude:
            excluded.append({"nct_id": nct, "reason": f"out of scope: {exclude[nct]}"})
            continue
        lab = labels.get(nct)
        s, why = assign(lab, cutoff)
        if s == "excluded":
            excluded.append({"nct_id": nct, "reason": why})
            continue
        text = render(rec, snapshot_date)
        bad = leak_problems(text)
        if bad:
            leaks[nct] = bad
        kind = endpoint_kind(rec)
        with open(os.path.join(out, "packets", "C", s, f"{nct}.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(os.path.join(out, "packets", "C", s, f"{nct}.json"), "w", encoding="utf-8") as fh:
            json.dump({"case_id": nct, "endpoint_kind": kind, "record": {k: v for k, v in rec.items()
                                                                         if k not in ("status", "has_results", "url")}},
                      fh, indent=1, ensure_ascii=False)
        counts[s] += 1
        entry = {"nct_id": nct, "set": s, "endpoint_kind": kind, "primary_completion_date": rec.get("primary_completion_date")}
        if s != "open":
            entry.update({"met": 1 if lab["met"] == "yes" else 0, "first_public_date": lab["first_public_date"],
                          "clear_date": lab.get("clear_date"),
                          "vague_at_deadline": bool(lab.get("vague_at_deadline")),
                          "endpoint": lab.get("endpoint"), "hr": lab.get("hr"), "hr_ci_low": lab.get("hr_ci_low"),
                          "hr_ci_high": lab.get("hr_ci_high"), "interim": lab.get("interim"),
                          "confidence": lab.get("confidence"), "sources": lab.get("sources", [])[:5],
                          "control_value": lab.get("control_value"), "effect_value": lab.get("effect_value"),
                          "women_effect": lab.get("women_effect"), "men_effect": lab.get("men_effect"),
                          **{k: lab.get(k) for k in ("subgroup_effects", "safety_experimental", "safety_control",
                                                     "key_secondary_met") if lab.get(k) is not None}})
        entry.update({k: lab[k] for k in ("label_deadline", "labels_as_of") if lab.get(k)})   # the pass read for
        key.append(entry)
    with open(os.path.join(out, "private", "key_C.json"), "w", encoding="utf-8") as fh:
        json.dump(key, fh, indent=1, ensure_ascii=False)
    resolved = [k for k in key if k["set"] != "open"]
    manifest = {
        "track": "C", "cutoff": cutoff, "snapshot_date": snapshot_date, "n_records": len(recs),
        "counts": counts, "excluded": excluded, "leak_phrases": leaks,
        "met_rate": {s: (sum(k["met"] for k in key if k["set"] == s) / max(1, counts[s])) for s in SETS if s != "open"},
        "with_hr": sum(1 for k in resolved if k.get("hr")),
        "rules": {
            "question": "p_met: probability that the sponsor or investigators report that the experimental arm "
                        "achieved the primary objective (superiority, or non-inferiority when designed for it) on at "
                        "least one primary endpoint; hr_median, hr_low80, hr_high80 for the first time-to-event "
                        "primary endpoint.",
            "label_date": "first public disclosure of whether the primary endpoint was met (press release, "
                          "congress abstract, paper or posted registry results)",
            "sets": "post_cutoff if first disclosure after the cutoff, pre_cutoff otherwise, open if not yet reported",
            "packet": "registry record without status, results, has-results flag or URL",
        },
    }
    with open(os.path.join(out, "manifest_C.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False)
    return manifest
