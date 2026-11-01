"""Registry records: the trimmed form the benchmark keeps, and conversion from ClinicalTrials.gov.

A record is a dict with the keys in ``FIELDS``. ``from_api_v2`` converts one study from
the ClinicalTrials.gov API v2 (``GET https://clinicaltrials.gov/api/v2/studies/<NCT id>``)
into that form; ``fetch`` downloads and converts a list of studies (needs internet access).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os

FIELDS = ["nct_id", "title", "brief_title", "acronym", "status", "phase", "study_type", "conditions",
          "interventions", "sponsor", "collaborators", "enrollment", "start_date", "primary_completion_date",
          "primary_completion_date_type", "completion_date", "brief_summary", "detailed_description", "eligibility_criteria", "minimum_age",
          "maximum_age", "sex", "primary_outcomes", "secondary_outcomes", "url", "has_results", "n_locations",
          "countries", "fetched_at"]

API = "https://clinicaltrials.gov/api/v2/studies/"


def _date(struct) -> str | None:
    return struct.get("date") if isinstance(struct, dict) else None


def _outcomes(lst) -> list[dict]:
    return [{"measure": o.get("measure"), "time_frame": o.get("timeFrame"), "description": o.get("description")}
            for o in (lst or []) if isinstance(o, dict)]


def from_api_v2(study: dict, fetched_at: str | None = None) -> dict:
    """Convert one API v2 study object into a record."""
    ps = study.get("protocolSection", {})
    idm, st = ps.get("identificationModule", {}), ps.get("statusModule", {})
    sp, desc = ps.get("sponsorCollaboratorsModule", {}), ps.get("descriptionModule", {})
    des, arms = ps.get("designModule", {}), ps.get("armsInterventionsModule", {})
    out, el = ps.get("outcomesModule", {}), ps.get("eligibilityModule", {})
    locs = ps.get("contactsLocationsModule", {}).get("locations", []) or []
    collab = [c.get("name") for c in sp.get("collaborators", []) or [] if c.get("name")]
    nct = idm.get("nctId")
    return {
        "nct_id": nct, "title": idm.get("officialTitle") or idm.get("briefTitle"), "brief_title": idm.get("briefTitle"),
        "acronym": idm.get("acronym"), "status": st.get("overallStatus"), "phase": des.get("phases", []),
        "study_type": des.get("studyType"), "conditions": ps.get("conditionsModule", {}).get("conditions", []),
        "interventions": [i.get("name") for i in arms.get("interventions", []) or [] if i.get("name")],
        "sponsor": sp.get("leadSponsor", {}).get("name"), "collaborators": ", ".join(collab) or None,
        "enrollment": (des.get("enrollmentInfo") or {}).get("count"),
        "start_date": _date(st.get("startDateStruct")),
        "primary_completion_date": _date(st.get("primaryCompletionDateStruct")),
        "primary_completion_date_type": (st.get("primaryCompletionDateStruct") or {}).get("type"),   # ACTUAL/ESTIMATED
        "completion_date": _date(st.get("completionDateStruct")),
        "brief_summary": desc.get("briefSummary"), "detailed_description": desc.get("detailedDescription"),
        "eligibility_criteria": el.get("eligibilityCriteria"), "minimum_age": el.get("minimumAge"),
        "maximum_age": el.get("maximumAge"), "sex": el.get("sex"),
        "primary_outcomes": _outcomes(out.get("primaryOutcomes")),
        "secondary_outcomes": _outcomes(out.get("secondaryOutcomes")),
        "url": f"https://clinicaltrials.gov/study/{nct}" if nct else None,
        "has_results": bool(study.get("hasResults")),
        "n_locations": len(locs),
        "countries": sorted({loc.get("country") for loc in locs if isinstance(loc, dict) and loc.get("country")}),
        "fetched_at": fetched_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def fetch(nct_ids: list[str], out_dir: str, timeout: float = 60) -> list[str]:
    """Download studies from ClinicalTrials.gov and write <out_dir>/<NCT id>.json; returns the IDs written."""
    import httpx
    os.makedirs(out_dir, exist_ok=True)
    done = []
    with httpx.Client(timeout=timeout) as client:
        for nct in nct_ids:
            r = client.get(API + nct, params={"format": "json"})
            r.raise_for_status()
            rec = from_api_v2(r.json())
            with open(os.path.join(out_dir, f"{rec['nct_id']}.json"), "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=1, ensure_ascii=False)
            done.append(rec["nct_id"])
    return done


def load_registry(directory: str) -> dict[str, dict]:
    recs = {}
    for path in sorted(glob.glob(os.path.join(directory, "NCT*.json"))):
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        if str(rec.get("nct_id", "")).startswith("NCT"):
            recs[rec["nct_id"]] = rec
    return recs
