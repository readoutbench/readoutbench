"""Operations questions of a round: will the trial run late, stop, or post its results?

They are asked for every trial of a round, also the trials with no efficacy goal to meet (safety-only, pilot,
descriptive), and are answered from the trial's ClinicalTrials.gov record as it stands on the round's read date
(``OPS_READ_DATE`` unless the round sets another):

- ``p_late`` ("late per the registry"): the probability that primary completion comes more than 90 days after the
  date registered on launch day, as the registry shows it. Late means that on the read date the record's primary
  completion date is more than ``LATE_DAYS`` after the launch-day date, or the trial is still enrolling (recruiting,
  not yet recruiting, enrolling by invitation) more than ``LATE_DAYS`` after it. Asked only when the launch-day date
  is after the launch day, so it is still an estimate. Void when the trial has stopped (``p_stopped`` covers it), and
  void when the record is stale: its primary completion date is still marked ESTIMATED although it lies more than
  ``LATE_DAYS`` before the read date (the sponsor has not said whether the trial finished; ClinicalTrials.gov gives
  the ESTIMATED/ACTUAL type in API v2 records, see records.from_api_v2). Records without the type are read as before.
- ``p_stopped``: the probability that the record's status is terminated, suspended or withdrawn on the read date.
- ``p_posted``: the probability that results are posted on ClinicalTrials.gov by the read date.

One more question is asked with them, for every trial with a ``p_met`` question (the round's export adds it):

- ``p_public``: the probability that the trial gets a ``p_met`` score in the round's first, ranked pass: a public
  statement on its primary result by the deadline (a press release, filing, congress, paper or posted registry
  results), whether it says the primary objective was met or not, or only calls the result positive or encouraging
  (which counts as not met at the deadline, rule 6); a stop with no public reason counts too, as for ``p_met``. It is
  resolved from the first pass's labels, not from the registry (``public_outcomes``): 1 when the first statement
  comes after the close and by the deadline, 0 when none has come by the deadline; void when it came before the close
  or the trial left the round. With ``p_met`` it gives the chance of a met result by the deadline, p_met x p_public.

Round 1 asks ``p_public`` for each of its three passes: ``p_public_mar`` (31 March 2027, the early pass),
``p_public`` (30 June 2027, the ranked pass) and ``p_public_dec`` (31 December 2027, the final pass); each is its own
all-or-none block, resolved from that pass's labels. It also asks, for every trial:

- ``p_amended``: the probability that between the launch day and the read date the record's primary outcomes change in
  substance (a primary outcome added or removed, or a primary outcome's measure, time point or analysis changed;
  rewording and added detail do not count). Judged by two labellers who compare the record as pulled for the round
  with the record fetched on the read date (``amend_label_instructions.md``), not read automatically; its own block.

The launch-day facts of each trial (status, registered primary completion date, the questions asked) are written
by the round's export to ``operations.jsonl``; outcomes are read later from fresh records with ``resolve``. The
operations answers get their own Brier score; they never enter the p_met ranking. With no history of registry
records to fit a base rate on, the reference is the share in the round itself, computed after the fact.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import json

REGISTRY_QUESTIONS = ("p_late", "p_stopped", "p_posted")   # answered from the registry record on the read date
PUBLIC_QUESTIONS = ("p_public_mar", "p_public", "p_public_dec")   # from the labels of the early, first and final pass
QUESTIONS = REGISTRY_QUESTIONS + PUBLIC_QUESTIONS + ("p_amended",)
BLOCKS = (REGISTRY_QUESTIONS, ("p_public",), ("p_public_mar",), ("p_public_dec",), ("p_amended",))  # each all or none
OUTCOME = {"p_late": "late", "p_stopped": "stopped", "p_posted": "posted", "p_public": "public",
           "p_public_mar": "public", "p_public_dec": "public", "p_amended": "amended"}
LATE_DAYS = 90
OPS_READ_DATE = "2027-08-31"
STOPPED = {"TERMINATED", "SUSPENDED", "WITHDRAWN"}
ENROLLING = {"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"}
STATUS_WORDS = {"RECRUITING": "recruiting", "NOT_YET_RECRUITING": "not yet recruiting",
                "ENROLLING_BY_INVITATION": "enrolling by invitation", "ACTIVE_NOT_RECRUITING": "active, not recruiting",
                "COMPLETED": "completed", "TERMINATED": "terminated", "SUSPENDED": "suspended",
                "WITHDRAWN": "withdrawn", "UNKNOWN": "unknown"}


def parse_date(s) -> _dt.date | None:
    """A registry date: YYYY-MM-DD, or YYYY-MM read as the last day of that month."""
    s = str(s or "").strip()
    try:
        if len(s) == 7:
            y, m = int(s[:4]), int(s[5:7])
            return _dt.date(y, m, calendar.monthrange(y, m)[1])
        return _dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def launch_row(rec: dict, launch_date: str) -> dict | None:
    """The operations questions of a trial on launch day, from its record; None when the trial cannot get them
    (already stopped, results already posted, or no primary completion date)."""
    status = str(rec.get("status") or rec.get("overall_status") or "").upper()
    pcd = parse_date(rec.get("primary_completion_date"))
    if status in STOPPED or rec.get("has_results") or pcd is None:
        return None
    qs = (["p_late"] if pcd > _dt.date.fromisoformat(launch_date) else []) + ["p_stopped", "p_posted"]
    return {"nct_id": str(rec["nct_id"]).upper(), "status": status or None,
            "primary_completion_date": rec.get("primary_completion_date"), "questions": qs}


def resolve(row: dict, rec: dict | None, read_date: str = OPS_READ_DATE) -> dict:
    """Outcomes of one trial's operations questions from its record as fetched on the read date
    (1 = it happened, 0 = it did not, None = void)."""
    out = {"nct_id": row["nct_id"], "late": None, "stopped": None, "posted": None, "read_date": read_date}
    if not rec:
        return out
    status = str(rec.get("status") or rec.get("overall_status") or "").upper()
    stopped = status in STOPPED
    if "p_stopped" in row["questions"]:
        out["stopped"] = int(stopped)
    if "p_posted" in row["questions"]:
        out["posted"] = int(bool(rec.get("has_results")))
    if "p_late" in row["questions"] and not stopped:
        due = parse_date(row["primary_completion_date"]) + _dt.timedelta(days=LATE_DAYS)
        now = parse_date(rec.get("primary_completion_date"))
        rd = _dt.date.fromisoformat(read_date)
        if now is not None:
            late = now > due or (status in ENROLLING and rd > due)
            stale = (str(rec.get("primary_completion_date_type") or "").upper() == "ESTIMATED"
                     and rd > now + _dt.timedelta(days=LATE_DAYS))
            out["late"] = 1 if late else (None if stale else 0)
            if stale and not late:
                out["late_void"] = "primary completion date still estimated, more than 90 days past"
    return out


def load_rows(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                out[str(r["nct_id"]).upper()] = r
    return out


def check_answers(o: dict, row: dict | None, group=REGISTRY_QUESTIONS) -> tuple[list[str], list[str], bool]:
    """(errors, warnings, answered) for one group of operations answers in one forecast line: the registry questions
    (default) or ("p_public",). Each group is all or none on its own."""
    errors, warnings = [], []
    given = [q for q in group if o.get(q) is not None]
    if not given:
        return errors, warnings, False
    asked = [q for q in (row["questions"] if row else []) if q in group]
    for q in given:
        if q not in asked:
            warnings.append(f"{q} is not asked for this trial and is ignored")
            continue
        v = o.get(q)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            errors.append(f"{q} must be a number from 0 to 1")
    for q in asked:
        if o.get(q) is None:
            errors.append(f"{q} is missing (operations answers are all or none)")
    return errors, warnings, bool(set(given) & set(asked))


def public_outcomes(rows: dict, key: dict, closes: str, deadline: str, question: str = "p_public") -> dict:
    """Outcomes of a p_public question from the round's key after its pass's labelling (run it only once the labels
    are as of a day after the pass's deadline): {nct_id: {"public": 1, 0 or None}}. rows: the operations rows; key:
    {nct_id: key row} (set "open" = no public result found; met 0/1 with first_public_date = a result); question:
    p_public, p_public_mar or p_public_dec, with the deadline of its pass."""
    out = {}
    for n, r in rows.items():
        if question not in r.get("questions", []):
            continue
        k = key.get(n)
        if k is None:                                   # left the round (stopped for a reason not about efficacy)
            y = None
        elif k.get("set") == "open":
            y = 0
        elif k.get("met") in (0, 1) and k.get("first_public_date"):
            d = k["first_public_date"]
            y = None if d <= closes else int(d <= deadline)
        else:
            y = None
        out[n] = {"nct_id": n, "public": y}
    return out


def ops_scores(preds: dict, outcomes: dict, questions=REGISTRY_QUESTIONS) -> dict:
    """Brier scores of the operations answers, per question and pooled, with the share in the round itself
    (computed after the fact) as the reference. outcomes: {nct_id: resolve() output}."""
    out, pooled, pooled_ref = {}, [], []
    for q in questions:
        ys = [(nid, o[OUTCOME[q]]) for nid, o in outcomes.items() if o.get(OUTCOME[q]) in (0, 1)]
        share = sum(y for _, y in ys) / len(ys) if ys else None
        sq, sq_ref = [], []
        for nid, y in ys:
            p = (preds.get(nid) or {}).get(q)
            if isinstance(p, (int, float)) and not isinstance(p, bool) and 0 <= p <= 1:
                sq.append((p - y) ** 2)
                sq_ref.append((share - y) ** 2)
        brier = sum(sq) / len(sq) if sq else None
        ref = sum(sq_ref) / len(sq_ref) if sq_ref else None
        out[q] = {"n_resolved": len(ys), "n_scored": len(sq), "share": share, "brier": brier,
                  "brier_share_in_round": ref, "skill": (1 - brier / ref) if sq and ref else None}
        pooled += sq
        pooled_ref += sq_ref
    b = sum(pooled) / len(pooled) if pooled else None
    r = sum(pooled_ref) / len(pooled_ref) if pooled_ref else None
    out["n_scored"] = len(pooled)
    out["brier"] = b
    out["skill"] = (1 - b / r) if pooled and r else None
    return out
