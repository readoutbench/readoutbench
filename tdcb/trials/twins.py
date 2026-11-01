"""One-detail-changed copies of a (names-hidden) trial record, for testing what moves a forecast.

Each change has an expected effect that holds whatever the trial's true result:
- `to_os`: a trial whose only primary endpoint is progression-free survival gets overall
  survival instead. Expected: p_met falls, the hazard ratio moves towards 1.
- `ido1`: the main experimental drug's description becomes an IDO1 inhibitor, a class whose
  phase 3 trials have failed. Expected: p_met falls.
- `half_n`: the enrolment is halved. Expected: p_met falls (less power); the hazard ratio,
  an estimate of the effect, should barely move.
- `same`: no change; the forecast is made again in another batch, to measure the noise.
"""
from __future__ import annotations

import copy
import re

PFS = re.compile(r"progression[- ]free survival|\bPFS\b", re.I)
OS = re.compile(r"overall survival|\bOS\b")
IDO1_LINE = "small molecule; indoleamine 2,3-dioxygenase 1 (IDO1) inhibitor (target: IDO1)"
CHANGES = ("to_os", "ido1", "half_n", "same")


def pfs_only(rec: dict) -> bool:
    po = rec.get("primary_outcomes") or []
    if not po:
        return False
    for o in po:
        text = f"{o.get('measure') or ''} {o.get('description') or ''}"
        if not PFS.search(o.get("measure") or "") or OS.search(text):
            return False
    return True


def _pfs_to_os(text):
    if not text:
        return text
    t = re.sub(r"progression[- ]free survival", "overall survival", str(text), flags=re.I)
    return re.sub(r"\b(i?r?PFS\d?)\b", "OS", t)


def to_os(rec: dict) -> dict:
    r = copy.deepcopy(rec)
    old = [o.get("measure") for o in rec.get("primary_outcomes") or []]
    r["primary_outcomes"] = [{"measure": "Overall survival (OS)",
                              "description": "OS is defined as the time from randomization to death from any cause.",
                              "time_frame": (rec.get("primary_outcomes") or [{}])[0].get("time_frame")}]
    sec = [o for o in rec.get("secondary_outcomes") or [] if not OS.search(o.get("measure") or "")]
    r["secondary_outcomes"] = [{"measure": m} for m in old if m] + sec
    for k in ("title", "brief_summary", "detailed_description"):
        r[k] = _pfs_to_os(rec.get(k))
    return r


def half_n(rec: dict) -> dict:
    r = copy.deepcopy(rec)
    try:
        n = int(float(rec.get("enrollment")))
    except (TypeError, ValueError):
        return r
    r["enrollment"] = max(2, round(n / 2))
    return r


def apply(change: str, rec: dict, drug_lines: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Returns the changed record and drug lines. `ido1` changes the first hidden drug's line."""
    if change == "to_os":
        return to_os(rec), dict(drug_lines)
    if change == "half_n":
        return half_n(rec), dict(drug_lines)
    if change == "ido1":
        lines = dict(drug_lines)
        if lines:
            first = next(iter(lines))
            lines[first] = IDO1_LINE
        return copy.deepcopy(rec), lines
    if change == "same":
        return copy.deepcopy(rec), dict(drug_lines)
    raise ValueError(change)
