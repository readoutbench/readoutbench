"""Live forecasting rounds for Track C.

A round publishes the trials that have no public result yet and takes forecasts until it closes. It is scored
on the trials whose first public result comes after the close date. That set is the same for every entry, so
entries can be compared, and no forecaster can have read about any of its results, so any model, harness or
tool is allowed: on the Open board. The Models board holds single models answering from the packet alone with the
round's instructions, so that models can be compared with each other. Trials that report before the close are dropped from scoring and listed. As results come out
they are labelled, the Track C build is re-run with the new labels (`tdcb trials build`), and the leaderboard
is recomputed from the new key.

A round directory holds:
  manifest.json            round id, dates, the trials, their endpoint kinds and the SHA-256 of every packet
  questions.jsonl          one line per trial: nct_id, endpoint_kind, title, primary_completion_date, packet
  packets/<NCT id>.md      the same packets as files
  cards.jsonl              (optional) one question card per trial: the endpoint, unit, arms and design the number
                           questions refer to, and whether the trial has number questions (see numbers.py)
  operations.jsonl         (optional) the launch-day facts and the operations questions of each trial (operations.py)
  registry.json           the entries received: id, name, team, kind, received date, files, SHA-256, metadata
  entries/<id>/            forecasts.jsonl and meta.json of each entry

  sisters.json             (optional) the sister-trial groups the bootstrap resamples together
  forecast_instructions.md (optional) the round's instructions: the Models board's prompt (SHA-256 in the manifest)

Entries reach the organiser privately through the round's submission page (a Hugging Face Space, see space/), so
nobody can copy them before the close. The list of entries, with each entry's SHA-256 and received time, is public
from the start, and the organiser posts the round's and the reference entries' SHA-256s outside that page before
the round opens; the entries' files are published after the close.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil

from . import numbers as tnum
from . import operations as tops
from . import score as tscore
from .packets import render

MIN_SCORED = 100          # entries are placed in tiers once this many trials are scored
MIN_NUMBERS_SCORED = 100  # and in number tiers once this many number questions are scored
NUMBERS_GAP = 0.05        # number tiers: a number score lower (or higher) than the reference's by more than this
SETTINGS = ("closed", "open")   # closed: the Models board; open: the Open board
BOARDS = {"models": "Models: one model, the round's instructions and the packet only, as declared by the entrant "
                    "(the organiser cannot check it, except for its own runs)",
          "open": "Open: anything else (any harness, tools, web, several models)"}
META_FIELDS = {"team": str, "entry_name": str, "contact": str, "models": list, "harness": str, "setting": str,
               "web_access": bool, "cost_usd_per_trial": (int, float)}
# provenance, required on the Models board (setting "closed" with a model): which model, run how
PROVENANCE = {"model_version": str, "provider": str, "prompt_sha256": str}
PROVENANCE_OPTIONAL = {"run_dates": str, "run_settings": str}
# how an Open board entry was made, required there and shown with it
RETRIEVAL = ("none", "web search", "own document collection", "web search and own collection")
OPEN_METHOD = {"retrieval": str, "human_in_the_loop": bool, "fine_tuned": bool, "ensemble": bool}
# the scoring passes: (manifest key of the deadline, suffix of the p_met and p_public fields asked for it)
PASSES = {"early": ("early_deadline", "_mar"), "first": ("deadline", ""), "final": ("final_deadline", "_dec")}
ASSUMPTIONS_MAX = 3       # optional per-trial checkable assumptions: up to 3 {"claim", "source"}
ASSUMPTION_CHARS = 300
HR_FIELDS = ("hr_median", "hr_low80", "hr_high80")
# every top-level key a forecast line may carry; validate warns on any other (a typo would otherwise be dropped silently)
KNOWN_KEYS = frozenset({"nct_id", "case_id", "p_met", "p_met_mar", "p_met_dec", "control", "effect", "variability",
                        "subgroups", "safety", "p_key_secondary", "p_next_step", "p_late", "p_stopped", "p_posted",
                        "p_public_mar", "p_public", "p_public_dec", "p_amended", "rationale", "evidence", "main_risk",
                        "reason", "assumptions", *HR_FIELDS})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RATIONALE_WORDS = 150     # optional per-trial rationale, never scored
RATIONALE_CHARS = 1500    # and at most this many characters
REASON_CHARS = 400        # the one sentence on main_risk, never scored
# control characters (other than tab and newline), bidirectional overrides and zero-width characters are refused in
# the published free text (rationale, evidence)
BAD_TEXT = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff"
                      "\U000e0000-\U000e007f]")
BAD_SCHEME = re.compile(r"^\s*(javascript|data|vbscript|file):", re.I)
# the entry's free-text metadata: shown on the leaderboard page, so short and with no control characters
META_TEXT_CAPS = {"team": 80, "entry_name": 80, "model_version": 80, "provider": 80, "run_settings": 300,
                  "run_dates": 80, "harness": 1000, "code_url": 300, "contact": 200}
PLACEHOLDER_VERSION = re.compile(r"(^|[^a-z])(latest|default|current|unknown|tbd|n/?a|none)([^a-z]|$)|^\W*$", re.I)
EVIDENCE_MAX = 5          # optional per-trial evidence: up to 5 short references (NCT numbers, PMIDs, links)
EVIDENCE_CHARS = 300
INSTRUCTIONS_FILE = "forecast_instructions.md"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return _sha256_bytes(fh.read())


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def load_forecasts(path: str) -> dict:
    """{NCT id: forecast} from a JSONL file whose lines carry `nct_id` (or `case_id`)."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(o, dict):
                nid = str(o.get("nct_id") or o.get("case_id") or "").strip().upper()
                if nid:
                    out.setdefault(nid, o)
    return out


def export(build: str, out: str, round_id: str, closes: str, opens: str | None = None,
           cards: str | None = None, deadline: str | None = None, operations: str | None = None,
           ops_read: str | None = None, final_deadline: str | None = None, sisters: str | None = None,
           instructions: str | None = None, early_deadline: str | None = None) -> dict:
    """Write a round from the open trials of a Track C build (public registry data only).

    `operations`: the launch-day rows of the operations questions (operations.launch_row, one per trial, JSONL);
    they are answered from the records as they stand on `ops_read` (default operations.OPS_READ_DATE). With
    question cards, every trial with a p_met question also gets p_public for each pass (resolved from the labels),
    and every trial gets p_amended.
    `deadline`: the first, ranked scoring pass counts results up to this date; `early_deadline`: an early pass before
    it; `final_deadline`: a final pass after it.
    `sisters`: the sister-trial groups (make_sisters.py: {"groups", "trial_group"}), published with the round and
    used by the leaderboard's bootstrap. `instructions`: the round's forecast instructions, copied into the round;
    their SHA-256 is the prompt the Models board's entries use."""
    key = _load_json(os.path.join(build, "private", "key_C.json"))
    src = os.path.join(build, "packets", "C", "open")
    ids = sorted(k["nct_id"] for k in key if k["set"] == "open")
    all_cards = tnum.load_cards(cards) if cards else None
    if all_cards is not None:
        missing = [n for n in ids if n not in all_cards]
        bad = {n: tnum.check_card(all_cards[n]) for n in ids if n in all_cards and tnum.check_card(all_cards[n])}
        if missing or bad:
            raise ValueError(f"question cards: {len(missing)} missing (e.g. {missing[:3]}), {len(bad)} unusable "
                             f"(e.g. {list(bad.items())[:2]})")
    ops_rows = tops.load_rows(operations) if operations else None
    ops_read = ops_read or tops.OPS_READ_DATE
    if ops_rows is not None:
        missing = [n for n in ids if n not in ops_rows]
        bad = [n for n in ids if n in ops_rows and (not ops_rows[n].get("questions") or
                                                    set(ops_rows[n]["questions"]) - set(tops.QUESTIONS))]
        if missing or bad:
            raise ValueError(f"operations rows: {len(missing)} missing (e.g. {missing[:3]}), {len(bad)} unusable "
                             f"(e.g. {bad[:3]})")
    if all_cards is not None and ops_rows is not None:
        # p_public: every trial with a p_met question. A round with an early pass (Round 1) asks it for each pass
        # (p_public_mar, p_public, p_public_dec) and asks p_amended of every trial.
        three = bool(early_deadline)
        if three and not (deadline and final_deadline and early_deadline < deadline < final_deadline):
            raise ValueError("an early pass needs a first and a final deadline after it, in that order")
        public = list(tops.PUBLIC_QUESTIONS) if three else ["p_public"]
        for n in ids:
            qs = [q for q in ops_rows[n]["questions"] if q in tops.REGISTRY_QUESTIONS]
            ops_rows[n] = dict(ops_rows[n], questions=qs + (public if tnum.has_p_met(all_cards[n]) else [])
                               + (["p_amended"] if three else []))
    if all_cards is not None:
        no_q = [n for n in ids if not tnum.has_p_met(all_cards[n]) and ops_rows is None]
        if no_q:
            raise ValueError(f"{len(no_q)} trials have no p_met question and the round has no operations questions, "
                             f"e.g. {no_q[:3]}")
    mpath = os.path.join(build, "manifest_C.json")
    snapshot = _load_json(mpath).get("snapshot_date") if os.path.exists(mpath) else None
    os.makedirs(os.path.join(out, "packets"), exist_ok=True)
    questions, hashes, kinds = [], {}, {}
    for nid in ids:
        with open(os.path.join(src, nid + ".md"), encoding="utf-8") as fh:
            md = fh.read()
        pk = _load_json(os.path.join(src, nid + ".json"))
        rec = pk.get("record") or {}
        if (all_cards is not None or ops_rows is not None) and rec.get("primary_outcomes") is not None:
            md = render(dict(rec, nct_id=nid), snapshot, card=all_cards[nid] if all_cards else None,
                        ops=ops_rows[nid] if ops_rows else None, ops_read=ops_read, deadline=deadline,
                        early_deadline=early_deadline, final_deadline=final_deadline)
        with open(os.path.join(out, "packets", nid + ".md"), "w", encoding="utf-8") as fh:
            fh.write(md)
        hashes[nid] = _sha256_bytes(md.encode("utf-8"))
        kinds[nid] = all_cards[nid]["kind"] if all_cards is not None else pk.get("endpoint_kind")
        q = {"nct_id": nid, "endpoint_kind": kinds[nid], "title": rec.get("brief_title") or rec.get("title"),
             "primary_completion_date": rec.get("primary_completion_date"), "packet": md}
        if all_cards is not None:
            q["p_met"] = tnum.has_p_met(all_cards[nid])
        if ops_rows is not None:
            q["operations"] = ops_rows[nid]["questions"]
        questions.append(q)
    card_rows = {}
    if all_cards is not None:
        card_rows = {n: {k: all_cards[n].get(k) for k in tnum.CARD_KEYS} for n in ids}
        for n in ids:          # optional keys: subgroups, the design's and the measure's basis, key secondary, next step
            if tnum.subgroup_groups(all_cards[n]):
                card_rows[n]["subgroups"] = all_cards[n]["subgroups"]
            for k in tnum.OPTIONAL_CARD_KEYS:
                if k != "subgroups" and all_cards[n].get(k):
                    card_rows[n][k] = all_cards[n][k]
        with open(os.path.join(out, "cards.jsonl"), "w", encoding="utf-8") as fh:
            for n in ids:
                fh.write(json.dumps(card_rows[n], ensure_ascii=False) + "\n")
        for q in questions:
            q["card"] = card_rows[q["nct_id"]]
    qpath = os.path.join(out, "questions.jsonl")
    with open(qpath, "w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")
    manifest = {
        "round": round_id, "opens": opens, "closes": closes, "n_trials": len(ids),
        "n_time_to_event": sum(v == "time_to_event" for v in kinds.values()),
        "scoring": "Scored on the trials whose first public result comes after the close date; trials that report "
                   "earlier are dropped. Headline: Brier skill against the base rate (entry ref-b0).",
        "trials": ids, "endpoint_kind": kinds, "packets_sha256": hashes, "questions_sha256": _sha256_file(qpath),
    }
    if all_cards is not None:
        manifest["deadline"] = deadline
        manifest["n_p_met_questions"] = sum(tnum.has_p_met(c) for c in card_rows.values())
        manifest["n_number_questions"] = sum(tnum.is_number_question(c) for c in card_rows.values())
        manifest["n_subgroup_questions"] = sum(bool(tnum.subgroup_groups(c)) for c in card_rows.values())
        manifest["n_subgroups"] = sum(len(tnum.subgroup_groups(c)) for c in card_rows.values())
        manifest["n_safety_questions"] = sum(tnum.has_safety(c) for c in card_rows.values())
        manifest["n_key_secondary_questions"] = sum(bool(tnum.key_secondary(c)) for c in card_rows.values())
        manifest["n_next_step_questions"] = sum(bool(tnum.next_step(c)) for c in card_rows.values())
        if early_deadline:
            manifest["early_deadline"] = early_deadline
        manifest["cards_sha256"] = _sha256_file(os.path.join(out, "cards.jsonl"))
        manifest["scoring"] = ("Scored on the trials whose first public result comes after the close date and on or "
                               "before the deadline; trials that report earlier are dropped and listed, trials still "
                               "silent at the deadline are dropped and counted. Headline: Brier score of p_met (with "
                               "its skill against the base rate, entry ref-b0). Number questions: low80, median and "
                               "high80 are the 10th, 50th and 90th percentiles, all three scored with the percentile "
                               "loss (the interval score of the 80% range plus 5 times the median's distance from the "
                               "result), in units of the reference entry's range width; void when the number is not "
                               "published by the deadline.")
    if ops_rows is not None:
        opath = os.path.join(out, "operations.jsonl")
        with open(opath, "w", encoding="utf-8") as fh:
            for n in ids:
                fh.write(json.dumps(ops_rows[n], ensure_ascii=False) + "\n")
        manifest["operations_read_date"] = ops_read
        manifest["n_operations_questions"] = {q: sum(q in ops_rows[n]["questions"] for n in ids) for q in tops.QUESTIONS}
        manifest["operations_sha256"] = _sha256_file(opath)
        manifest["scoring"] += (f" Operations questions (p_late, p_stopped, p_posted): answered from the registry "
                                f"records as they stand on {ops_read}; their own Brier score, against the share in "
                                "the round itself, shown next to the ranking and never part of it.")
    if final_deadline:
        manifest["final_deadline"] = final_deadline
    if instructions:
        shutil.copyfile(instructions, os.path.join(out, INSTRUCTIONS_FILE))
        manifest["instructions_sha256"] = _sha256_file(os.path.join(out, INSTRUCTIONS_FILE))
    if sisters:
        sis = _load_json(sisters)
        tg = {n: g for n, g in sorted(sis["trial_group"].items()) if n in set(ids)}     # sorted: the same bytes
        groups = {}
        for n, g in tg.items():
            groups.setdefault(g, []).append(n)
        extra = {k: {n: v for n, v in sorted(sis[k].items()) if n in set(ids)} for k in ("trial_sponsor", "trial_china_only", "trial_below_bar")
                 if k in sis}
        _dump_json({"groups": {g: sorted(v) for g, v in sorted(groups.items())}, "trial_group": tg, **extra},
                   os.path.join(out, "sisters.json"))
        manifest["n_sister_groups"] = len(groups)
        manifest["sisters_sha256"] = _sha256_file(os.path.join(out, "sisters.json"))
    if all_cards is not None:
        manifest["scoring"] = _scoring_text(manifest)
    _dump_json(manifest, os.path.join(out, "manifest.json"))
    if not os.path.exists(os.path.join(out, "registry.json")):
        _dump_json([], os.path.join(out, "registry.json"))
    return manifest


def _scoring_text(m: dict) -> str:
    """The manifest's one-paragraph statement of how the round is scored (fixed when the round is exported)."""
    t = (f"p_met is the chance that the trial meets its primary objective, given that a result is public by the "
         f"deadline ({m.get('deadline')}): reported success under the round's labelling rules (a trial only vague at "
         "the deadline counts as not met; their number, and every score without them, are shown). Ranked result: the first pass, on the trials whose first public result comes "
         f"after the close ({m['closes']}) and on or before the deadline; earlier results are dropped and listed, trials "
         "still silent are dropped and counted. Two boards: Models (one model, the round's instructions "
         f"({INSTRUCTIONS_FILE}, SHA-256 in this manifest) and the packet only: no web, no tools, no other model, one "
         "answer per trial, as declared by the entrant) and Open (anything else). Once "
         f"{MIN_SCORED} trials are scored, every entry is placed in one of three tiers against the registry model "
         f"(ref-b1): clearly better (a Brier score of p_met lower by more than {MIN_GAP}), no clear difference, or clearly "
         f"worse (higher by more than {MIN_GAP}). Each entry is tested on its own, so other entries cannot move its tier: "
         "two one-sided tests fixed in advance, from the standard deviation of a paired bootstrap that resamples "
         "sister-trial groups (sisters.json) together and a normal approximation; the smaller p-value is doubled and "
         "compared with 5%. Each board lists its entries by tier, then by Brier score (calibration counts, as in any "
         "proper score); comparisons between entries are shown as exploratory, never ranked. Shown with each entry, never "
         "ranked: whether it adds to the registry model (exploratory: the Brier gain of a logistic combination of "
         "logit(ref-b1) and logit(entry) over ref-b1 recalibrated alone, both fitted out of fold in "
         f"{ADD_FOLDS} folds of whole sister groups, averaged over {ADD_REPEATS} splits, with an interval from {ADD_BOOT} "
         "resamples that run the same estimator; it adds only if the interval is above 0 and the entry's weight is "
         "positive); its first upload's score next to its last, with both setups, when uploaded more than once. The "
         "organiser's model runs are on the Models board; the base rate (ref-b0) and the registry model (ref-b1), both "
         "matched to each trial's reporting window and published from the opening day, are shown as baselines. Skill "
         "against both with paired intervals; AUROC, reliability, resolution and the level gap shown. Optional rationale "
         "and evidence are published with the entries as plain text, never scored. "
         + (f"An early pass with results up to {m['early_deadline']} (p_met_mar where given, else p_met; B0 and B1 "
            "worked out for that date) shows tiers once enough trials are scored there, as an early look, never the "
            "ranking. " if m.get("early_deadline") else "")
         + (f"A supplementary pass with results up to {m['final_deadline']} "
            + ("(p_met_dec where given, else p_met) " if m.get("early_deadline") else "")
            + "is shown, never ranked. " if m.get("final_deadline") else "")
         + "Number questions: low80, median and high80 are the 10th, 50th and 90th percentiles, all three scored with "
         "the percentile loss (the interval score of the 80% range plus 5 times the median's distance from the result), "
         "divided by the width of the frozen reference entry's (ref-opus-5-5) range, never less than a floor per "
         f"question ({tnum.FLOOR_PCT}th percentile of comparable reference widths); summarised by the plain mean, with "
         "the median and the 5%-trimmed mean shown; void when the number is not published. Subgroup answers: scored "
         "the same way, shown, never ranked."
         + (f" The number score is ranked too: in the first pass, once {MIN_NUMBERS_SCORED} number questions are "
            f"scored, each entry with number answers gets a number tier against ref-opus-5-5 (a number score lower or "
            f"higher by more than {NUMBERS_GAP}), with the same test. Safety answers (the % stopping treatment for an "
            "adverse event, per arm) get the same percentile loss in percentage points; p_key_secondary and "
            "p_next_step their Brier score against the share in the round; assumptions the share their sources "
            "support; all shown, never ranked." if m.get("early_deadline") else ""))
    if m.get("operations_read_date"):
        t += (f" Operations questions (p_late, p_stopped, p_posted): answered from the registry records as they "
              f"stand on {m['operations_read_date']}; their own Brier score, against the share in the round itself, "
              "shown next to the ranking and never part of it.")
        if (m.get("n_operations_questions") or {}).get("p_public"):
            t += (f" p_public (every trial with p_met; its own all-or-none block): the chance that a statement on the "
                  "primary result comes out by "
                  f"{m.get('deadline')}, so that p_met is scored, decided by the labellers from the first pass's labels; "
                  "void when it came before the close; its own Brier score, and the Brier score of p_met x p_public "
                  "against a statement by the deadline and met; neither part of the ranking.")
        if (m.get("n_operations_questions") or {}).get("p_public_mar"):
            t += (" p_public_mar and p_public_dec: the same by the early and final deadlines, each its own block, "
                  "with p_public_mar <= p_public <= p_public_dec. p_amended (every trial, its own block): the chance "
                  "that the record's primary outcomes change in substance by the read date, judged by two labellers "
                  "who compare the record as pulled for the round with the record fetched on the read date.")
    return t


def board(meta: dict, reference: bool = False) -> str:
    """The board an entry belongs to: "models" (setting closed) or "open"; "baseline" for the organiser's references
    with no model (B0, B1)."""
    if reference and (meta or {}).get("models") == []:
        return "baseline"
    return "models" if (meta or {}).get("setting") == "closed" else "open"


def check_meta(meta, reference: bool = False, instructions_sha256: str | None = None) -> list[str]:
    """Errors in an entry's metadata. Setting "closed" puts the entry on the Models board: exactly one model, no web,
    and its provenance (model_version: the exact version the provider names; provider; prompt_sha256: the SHA-256 of
    the round's instructions, which must be used unchanged). The organiser's baselines (references with no model)
    are exempt."""
    errors = []
    if not isinstance(meta, dict):
        return ["meta.json must hold one JSON object"]
    if meta.get("setting") == "closed" and not (reference and meta.get("models") == []):
        if meta.get("web_access") is True:
            errors.append("meta: the Models board (setting closed) allows no web access; choose open")
        if isinstance(meta.get("models"), list) and len(meta["models"]) != 1:
            errors.append("meta: the Models board (setting closed) takes exactly one model; choose open for several")
        for field, typ in PROVENANCE.items():
            v = meta.get(field)
            if not isinstance(v, typ) or not v.strip():
                errors.append(f"meta: {field} is needed on the Models board (setting closed)")
        mv = meta.get("model_version")
        if isinstance(mv, str) and mv.strip() and (PLACEHOLDER_VERSION.search(mv.strip()) or
                                                    not re.search(r"\d", mv)):
            errors.append("meta: model_version must be the exact version as the provider names it (with its date or "
                          "number), not an alias such as \"latest\"")
        ps = str(meta.get("prompt_sha256") or "").strip().lower()
        if ps and not SHA256_RE.match(ps):
            errors.append("meta: prompt_sha256 must be a SHA-256 (64 hex digits)")
        elif ps and instructions_sha256 and ps != instructions_sha256:
            errors.append(f"meta: the Models board uses the round's instructions unchanged ({INSTRUCTIONS_FILE}, "
                          f"SHA-256 {instructions_sha256[:12]}...); with another prompt, choose open")
    for field, typ in PROVENANCE_OPTIONAL.items():
        if meta.get(field) is not None and not isinstance(meta[field], typ):
            errors.append(f"meta: {field} has the wrong type")
    for field, cap in META_TEXT_CAPS.items():
        v = meta.get(field)
        if isinstance(v, str) and (len(v) > cap or BAD_TEXT.search(v)):
            errors.append(f"meta: {field} must be at most {cap} characters, with no control, direction-override or "
                          "zero-width characters")
    if isinstance(meta.get("models"), list) and any(isinstance(m, str) and (len(m) > 80 or BAD_TEXT.search(m))
                                                   for m in meta["models"]):
        errors.append("meta: model names must be at most 80 characters, with no control characters")
    if isinstance(meta.get("code_url"), str) and meta["code_url"].strip() and \
            not re.match(r"^https?://", meta["code_url"].strip()):
        errors.append("meta: code_url must be an http(s) link")
    for field, typ in META_FIELDS.items():
        v = meta.get(field)
        if field == "cost_usd_per_trial" and reference and v is None:
            continue
        if v is None or (isinstance(v, str) and not v.strip()):
            errors.append(f"meta: {field} is missing")
        elif not isinstance(v, typ) or (typ == (int, float) and isinstance(v, bool)):
            errors.append(f"meta: {field} has the wrong type")
    if meta.get("setting") not in (None, *SETTINGS):
        errors.append(f"meta: setting must be one of {', '.join(SETTINGS)}")
    cost = meta.get("cost_usd_per_trial")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and not (0 <= cost and cost == cost
                                                                               and cost != float("inf")):
        errors.append("meta: cost_usd_per_trial must be a number from 0 up")
    if meta.get("setting") == "open" and not reference:     # how an Open board entry was made, shown with it
        for field, typ in OPEN_METHOD.items():
            v = meta.get(field)
            if v is None or not isinstance(v, typ) or (typ is str and not v.strip()):
                errors.append(f"meta: {field} is needed on the Open board"
                              + (f" (one of: {', '.join(RETRIEVAL)})" if field == "retrieval" else " (true or false)"))
        if isinstance(meta.get("retrieval"), str) and meta["retrieval"].strip() and meta["retrieval"] not in RETRIEVAL:
            errors.append(f"meta: retrieval must be one of: {', '.join(RETRIEVAL)}")
        elif meta.get("retrieval") in RETRIEVAL and isinstance(meta.get("web_access"), bool) and \
                ("web search" in meta["retrieval"]) != meta["web_access"]:
            errors.append(f"meta: retrieval \"{meta['retrieval']}\" contradicts web_access {str(meta['web_access']).lower()}"
                          " (web search means web access)")
    if isinstance(meta.get("contact"), str) and meta["contact"].strip() and "@" not in meta["contact"] and not reference:
        errors.append("meta: contact must be an e-mail address")
    if isinstance(meta.get("models"), list) and not all(isinstance(m, str) and m.strip() for m in meta["models"]):
        errors.append("meta: models must be a list of model names")
    return errors


def _round_cards(round_dir: str) -> dict | None:
    path = os.path.join(round_dir, "cards.jsonl")
    return tnum.load_cards(path) if os.path.exists(path) else None


def _round_ops(round_dir: str) -> dict | None:
    path = os.path.join(round_dir, "operations.jsonl")
    return tops.load_rows(path) if os.path.exists(path) else None


def _loose_numbers(o: dict) -> list[str]:
    """Fields that should be JSON numbers but are strings or booleans ("0.5", true)."""
    bad = []
    def isnum(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    for k in ("p_met", "p_met_mar", "p_met_dec", "p_key_secondary", "p_next_step", "variability", *tops.QUESTIONS):
        if o.get(k) is not None and not isnum(o[k]):
            bad.append(k)
    ranges = [(w, o.get(w)) for w in ("control", "effect")]
    if isinstance(o.get("safety"), dict):
        ranges += [(f"safety.{a}", d) for a, d in o["safety"].items()]
    if isinstance(o.get("subgroups"), dict):
        for s, dd in o["subgroups"].items():
            if isinstance(dd, dict):
                ranges += [(f"subgroups.{s}.{g}", d) for g, d in dd.items()]
    for w, d in ranges:
        if isinstance(d, dict):
            bad += [f"{w}.{k}" for k in ("median", "low80", "high80") if d.get(k) is not None and not isnum(d[k])]
    return bad


def check_assumptions(o: dict) -> list[str]:
    """Errors in the optional assumptions: a list of up to ASSUMPTIONS_MAX {"claim", "source"} objects, each a short
    text (a fact the forecast rests on that anyone can check, and where it comes from). Never scored; checked by the
    organiser after the close and published with the entry."""
    a = o.get("assumptions")
    if a is None:
        return []
    if not isinstance(a, list) or not all(isinstance(x, dict) for x in a):
        return ["assumptions must be a list of {\"claim\": ..., \"source\": ...} objects"]
    if len(a) > ASSUMPTIONS_MAX:
        return [f"assumptions: at most {ASSUMPTIONS_MAX}"]
    for x in a:
        if set(x) - {"claim", "source"}:
            return ["assumptions: each has only claim and source"]
        for k in ("claim", "source"):
            v = x.get(k)
            if not isinstance(v, str) or not v.strip() or len(v) > ASSUMPTION_CHARS:
                return [f"assumptions: each {k} is a text of 1 to {ASSUMPTION_CHARS} characters"]
            if BAD_TEXT.search(v):
                return ["assumptions have control, direction-override or zero-width characters"]
        if BAD_SCHEME.search(x["source"]):
            return ["assumptions: links must be http(s); javascript:, data:, vbscript: and file: are refused"]
    return []


def check_rationale(o: dict) -> list[str]:
    """Errors in the optional rationale (text, up to RATIONALE_WORDS words) and evidence (a list of up to
    EVIDENCE_MAX short strings: NCT numbers, PMIDs, DOIs or links). Never scored; published with the entry."""
    errors = []
    r = o.get("rationale")
    if r is not None:
        if not isinstance(r, str):
            errors.append("rationale must be text")
        elif len(r.split()) > RATIONALE_WORDS or len(r) > RATIONALE_CHARS:
            errors.append(f"rationale has {len(r.split())} words and {len(r)} characters; at most {RATIONALE_WORDS} "
                          f"words and {RATIONALE_CHARS} characters")
        elif BAD_TEXT.search(r):
            errors.append("rationale has control, direction-override or zero-width characters")
    r = o.get("reason")                 # the one sentence on main_risk: published with the entry, never scored
    if r is not None:
        if not isinstance(r, str):
            errors.append("reason must be text")
        elif len(r) > REASON_CHARS:
            errors.append(f"reason has {len(r)} characters; at most {REASON_CHARS}")
        elif BAD_TEXT.search(r):
            errors.append("reason has control, direction-override or zero-width characters")
    ev = o.get("evidence")
    if ev is not None:
        if not isinstance(ev, list) or not all(isinstance(x, str) and x.strip() for x in ev):
            errors.append("evidence must be a list of short texts (NCT numbers, PMIDs, DOIs or links)")
        elif len(ev) > EVIDENCE_MAX or any(len(x) > EVIDENCE_CHARS for x in ev):
            errors.append(f"evidence: at most {EVIDENCE_MAX} items of at most {EVIDENCE_CHARS} characters each")
        elif any(BAD_TEXT.search(x) for x in ev):
            errors.append("evidence has control, direction-override or zero-width characters")
        elif any(BAD_SCHEME.search(x) for x in ev):
            errors.append("evidence: links must be http(s); javascript:, data:, vbscript: and file: are refused")
    return errors


def validate(round_dir: str, forecasts_path: str, meta_path: str | None = None, reference: bool = False) -> dict:
    """Check a submission against a round: every trial with a p_met question once, p_met in [0, 1], and the other
    answers well formed.

    Rounds with question cards: control and effect ranges for the number questions (all of them or none),
    variability a positive number, main_risk one of the listed reasons; and, each block all or none on its own, the
    subgroup answers, the safety answers, p_key_secondary and p_next_step; p_met_mar and p_met_dec (optional, trial by
    trial: where left out, p_met is used for that pass). Rounds with operations questions: p_late, p_stopped and
    p_posted in [0, 1] wherever asked (all of them or none; trials with no p_met question then need a line too); each
    p_public question and p_amended a block of its own; p_public_mar <= p_public <= p_public_dec where given. Optional
    rationale, evidence and assumptions. With metadata: on the Models board, every trial with p_met needs a rationale.
    Rounds without cards: hazard ratios."""
    man = _load_json(os.path.join(round_dir, "manifest.json"))
    trials = set(man["trials"])
    cards = _round_cards(round_dir)
    ops = _round_ops(round_dir)
    pm = {n for n in trials if tnum.has_p_met((cards or {}).get(n))}
    tte = {n for n, k in man["endpoint_kind"].items() if k == "time_to_event"}
    nq = {n for n in trials if cards and tnum.is_number_question(cards.get(n))}
    blocks = {      # optional card-level blocks, each all or none: (trials asking it, how to check one answer)
        "subgroups": ({n for n in trials if cards and tnum.subgroup_groups(cards.get(n))},
                      lambda v, c: tnum.check_subgroups(v, c)),
        "safety": ({n for n in trials if cards and tnum.has_safety(cards.get(n))}, lambda v, c: tnum.check_safety(v)),
        "p_key_secondary": ({n for n in trials if cards and tnum.key_secondary(cards.get(n))}, lambda v, c: _prob(v)),
        "p_next_step": ({n for n in trials if cards and tnum.next_step(cards.get(n))}, lambda v, c: _prob(v)),
    }
    block_answered = {k: set() for k in blocks}
    meta, meta_errors = None, []
    if meta_path:
        try:
            meta = _load_json(meta_path)
        except (OSError, json.JSONDecodeError) as e:
            meta_errors.append(f"meta: cannot read {meta_path} ({e.__class__.__name__})")
        else:
            meta_errors += check_meta(meta, reference, man.get("instructions_sha256"))
    # the Models board's entries follow the round's instructions, which ask a rationale for every trial with p_met
    need_rationale = (isinstance(meta, dict) and meta.get("setting") == "closed" and cards is not None
                      and not (reference and meta.get("models") == []))
    errors, warnings, seen, no_hr, answered = [], [], set(), 0, set()
    n_rationale, n_assumptions, no_rationale = 0, 0, []
    ops_done = {b: set() for b in tops.BLOCKS}
    with open(forecasts_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {i}: not valid JSON")
            continue
        if not isinstance(o, dict):
            errors.append(f"line {i}: not a JSON object")
            continue
        nid = str(o.get("nct_id") or o.get("case_id") or "").strip().upper()
        if nid not in trials:
            errors.append(f"line {i}: {nid or 'no nct_id'} is not a trial of round {man['round']}")
            continue
        if nid in seen:
            errors.append(f"line {i}: {nid} appears more than once")
            continue
        seen.add(nid)
        unknown = sorted(set(o) - KNOWN_KEYS)
        if unknown:
            warnings.append(f"line {i}: {nid}: unknown key(s) {', '.join(unknown)} are ignored (a typo?)")
        loose = _loose_numbers(o)
        if loose:
            errors.append(f"line {i}: {nid}: {', '.join(loose)} must be JSON numbers (not strings or true/false)")
        errors += [f"line {i}: {nid}: {e}" for e in check_rationale(o) + check_assumptions(o)]
        if o.get("rationale") or o.get("evidence"):
            n_rationale += 1
        if o.get("assumptions"):
            n_assumptions += 1
        if nid in pm and tscore._p(o) is None:
            errors.append(f"line {i}: {nid}: p_met must be a number from 0 to 1")
        elif nid not in pm and o.get("p_met") is not None:
            warnings.append(f"line {i}: {nid} has no p_met question; its p_met is ignored")
        for k in ("p_met_mar", "p_met_dec"):
            if o.get(k) is None:
                continue
            if nid not in pm or cards is None or not man.get("early_deadline"):
                warnings.append(f"line {i}: {nid}: {k} is not asked here and is ignored")
            elif _prob(o[k]):
                errors.append(f"line {i}: {nid}: {k} must be a number from 0 to 1")
        if need_rationale and nid in pm and not (isinstance(o.get("rationale"), str) and o["rationale"].strip()):
            no_rationale.append(nid)
        if ops is not None:                 # blocks, each all or none: the registry questions, each p_public, p_amended
            for group in tops.BLOCKS:
                e_, w_, did = tops.check_answers(o, ops.get(nid), group)
                errors += [f"line {i}: {nid}: {e}" for e in e_]
                warnings += [f"line {i}: {nid}: {w}" for w in w_]
                if did:
                    ops_done[group].add(nid)
            asked_q = set((ops.get(nid) or {}).get("questions") or ())     # answers not asked are ignored: unchecked
            pp = [o.get(q) if q in asked_q else None for q in tops.PUBLIC_QUESTIONS]
            vals = [v for v in pp if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1]
            if len(vals) == len([v for v in pp if v is not None]) and any(
                    a is not None and b is not None and a > b + 1e-9 for a, b in ((pp[0], pp[1]), (pp[1], pp[2]), (pp[0], pp[2]))):
                errors.append(f"line {i}: {nid}: p_public_mar <= p_public <= p_public_dec (a result public by March "
                              "is public by June, and by December)")
        if cards is None:
            if any(o.get(k) is not None for k in HR_FIELDS):
                if tscore._hr(o) is None:
                    errors.append(f"line {i}: {nid}: a hazard ratio needs hr_median, hr_low80 and hr_high80, all above "
                                  "0, with low <= median <= high")
            elif nid in tte:
                no_hr += 1
            continue
        card = cards.get(nid)
        for k, (asked, check) in blocks.items():
            if o.get(k) is None:
                continue
            if nid not in asked:
                warnings.append(f"line {i}: {nid} has no {k} question; its {k} answer is ignored")
                continue
            why = check(o.get(k), card)
            if why:
                errors.append(f"line {i}: {nid}: {why if k in ('subgroups', 'safety') else k + ' ' + why}")
            else:
                block_answered[k].add(nid)
        given = [w for w in ("control", "effect") if o.get(w) is not None]
        if given and nid not in nq:
            warnings.append(f"line {i}: {nid} has no number questions; its control and effect are ignored")
        elif given:
            answered.add(nid)
            for w in ("control", "effect"):
                why = tnum.check_range(o.get(w), card, w) if o.get(w) is not None else f"{w} is missing"
                if why:
                    errors.append(f"line {i}: {nid}: {why}")
        v = o.get("variability")
        if v is not None and (tnum.num(v) is None or tnum.num(v) <= 0):
            errors.append(f"line {i}: {nid}: variability must be a positive number or null")
        r = o.get("main_risk")
        if r is not None and r not in tnum.MAIN_RISKS:
            errors.append(f"line {i}: {nid}: main_risk must be one of: {', '.join(tnum.MAIN_RISKS)}")
    missing = sorted(pm - seen)
    if missing:
        errors.append(f"{len(missing)} trials have no forecast, e.g. {', '.join(missing[:5])}")
    if no_rationale:
        errors.append(f"rationale: the Models board follows the round's instructions, which ask a rationale for every "
                      f"trial with p_met; {len(no_rationale)} have none, e.g. {', '.join(no_rationale[:5])}")
    ops_answered = ops_done[tops.REGISTRY_QUESTIONS]
    if ops is not None and ops_answered:
        left = sorted(set(ops) & trials - ops_answered)
        if left:
            errors.append(f"operations: answer the operations questions of all {len(set(ops) & trials)} trials or of "
                          f"none; {len(left)} are missing, e.g. {', '.join(left[:5])}")
    elif ops is not None:
        warnings.append("no operations answers: the entry is not scored on the operations questions")
        extra = sorted(seen - pm)
        if extra and not ops_done[("p_amended",)]:
            warnings.append(f"{len(extra)} lines are for trials with operations questions only, and have no "
                            "operations answers")
    if ops is not None:
        for group in tops.BLOCKS[1:]:
            q = group[0]
            asked = {n for n in set(ops) & trials if q in ops[n].get("questions", [])}
            done = ops_done[group]
            if done and done != asked:
                left = sorted(asked - done)
                errors.append(f"{q}: give it for all {len(asked)} trials that ask it or for none; {len(left)} are "
                              f"missing, e.g. {', '.join(left[:5])}")
            elif asked and not done:
                warnings.append(f"no {q} answers: the entry gets no {q} score"
                                + (" or met-by-the-deadline score" if q == "p_public" else ""))
    if no_hr:
        warnings.append(f"{no_hr} time-to-event trials have no hazard ratio; they count for p_met only")
    if cards is not None and answered and answered != nq:
        left = sorted(nq - answered)
        errors.append(f"numbers: give control and effect for all {len(nq)} number questions or for none; "
                      f"{len(left)} are missing, e.g. {', '.join(left[:5])}")
    if cards is not None and not answered and nq:
        warnings.append(f"no number answers: the entry is scored on p_met only ({len(nq)} number questions left blank)")
    for k, (asked, _) in blocks.items():
        done = block_answered[k]
        if done and done != asked:
            left = sorted(asked - done)
            errors.append(f"{k}: give it for all {len(asked)} trials that ask it or for none; {len(left)} are missing "
                          f"or malformed, e.g. {', '.join(left[:5])}")
    errors += meta_errors
    return {"ok": not errors, "errors": errors, "warnings": warnings, "n_forecasts": len(seen),
            "n_number_answers": len(answered), "n_subgroup_answers": len(block_answered["subgroups"]),
            "n_safety_answers": len(block_answered["safety"]),
            "n_key_secondary_answers": len(block_answered["p_key_secondary"]),
            "n_next_step_answers": len(block_answered["p_next_step"]),
            "n_operations_answers": len(ops_answered), "n_p_public_answers": len(ops_done[("p_public",)]),
            "n_p_public_mar_answers": len(ops_done[("p_public_mar",)]),
            "n_p_public_dec_answers": len(ops_done[("p_public_dec",)]),
            "n_p_amended_answers": len(ops_done[("p_amended",)]),
            "n_rationales": n_rationale, "n_assumptions": n_assumptions,
            "board": board(meta) if isinstance(meta, dict) else None,
            "sha256": _sha256_file(forecasts_path), "round": man["round"]}


def _prob(v) -> str | None:
    """Why v is not a probability, or None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
        return "must be a number from 0 to 1"
    return None


def read_sha256_file(path: str) -> str | None:
    """The SHA-256 in a file as `sha256sum` writes it ("<64 hex digits>  forecasts.jsonl"); None if malformed."""
    with open(path, encoding="utf-8") as fh:
        tokens = fh.read().split()
    tok = tokens[0].lower() if tokens else ""
    return tok if SHA256_RE.match(tok) else None


def check_sealed(meta_path: str, sha256_path: str, reference: bool = False,
                 instructions_sha256: str | None = None) -> dict:
    """Check a sealed submission: the metadata and the SHA-256 of a forecast file that is sent separately.
    `instructions_sha256`: the round's (manifest), which a Models board entry's prompt_sha256 must match."""
    errors = []
    try:
        meta = _load_json(meta_path)
    except (OSError, json.JSONDecodeError) as e:
        errors.append(f"meta: cannot read {meta_path} ({e.__class__.__name__})")
    else:
        errors += check_meta(meta, reference, instructions_sha256)
    sha = None
    try:
        sha = read_sha256_file(sha256_path)
    except OSError as e:
        errors.append(f"cannot read {sha256_path} ({e.__class__.__name__})")
    else:
        if sha is None:
            errors.append("forecasts.sha256 must start with the 64-character SHA-256 of forecasts.jsonl, "
                          "as `sha256sum forecasts.jsonl` prints it")
    return {"ok": not errors, "errors": errors, "sha256": sha}


def register(round_dir: str, entry_id: str, forecasts_path: str, meta_path: str, received: str,
             kind: str = "entry", expect_sha256: str | None = None, of: str | None = None) -> dict:
    """Add a checked entry to the round's registry. `received` is the date it was received (UTC), from the
    submission page's server record (space/pull_entries.py passes it), never from the submitter; for the organiser's
    own reference entries, the day they were registered, published with their SHA-256 before the round opens.
    `expect_sha256` is the SHA-256 the entrant posted in public beforehand; the forecasts must match it.
    kind "first_upload" (with `of`: the entry's id): the first upload of an entry uploaded more than once, scored next
    to the last and never ranked."""
    man = _load_json(os.path.join(round_dir, "manifest.json"))
    if not entry_id or not all(c.isalnum() or c in "-_." for c in entry_id):
        raise ValueError("entry id: letters, digits, '-', '_' and '.' only")
    if kind not in ("entry", "reference", "first_upload") or (kind == "first_upload") != bool(of):
        raise ValueError("kind is entry, reference or first_upload; first_upload needs `of`, the others not")
    _dt.date.fromisoformat(received)
    if received > man["closes"]:
        raise ValueError(f"received {received}, after the round closed on {man['closes']}")
    v = validate(round_dir, forecasts_path, meta_path, reference=(kind == "reference"))
    if not v["ok"]:
        raise ValueError("submission does not pass the checks: " + "; ".join(v["errors"][:5]))
    if expect_sha256 is not None and v["sha256"] != expect_sha256.strip().lower():
        raise ValueError(f"the forecasts' SHA-256 is {v['sha256']}, not the {expect_sha256.strip().lower()} posted for "
                         "this entry")
    reg_path = os.path.join(round_dir, "registry.json")
    reg = _load_json(reg_path)
    if any(e["id"] == entry_id for e in reg):
        raise ValueError(f"entry {entry_id} is already registered")
    dest = os.path.join(round_dir, "entries", entry_id)
    os.makedirs(dest, exist_ok=True)
    shutil.copyfile(forecasts_path, os.path.join(dest, "forecasts.jsonl"))
    meta = _load_json(meta_path)
    if kind != "reference":                 # the contact stays with the organiser; entries are published later
        _dump_json({k: v for k, v in meta.items() if k != "contact"}, os.path.join(dest, "meta.json"))
    else:
        shutil.copyfile(meta_path, os.path.join(dest, "meta.json"))
    entry = {"id": entry_id, "name": meta["entry_name"], "team": meta["team"], "kind": kind, "received": received,
             "forecasts": f"entries/{entry_id}/forecasts.jsonl", "meta": f"entries/{entry_id}/meta.json",
             "sha256": v["sha256"], "setting": meta["setting"], "board": board(meta, kind == "reference"),
             "web_access": meta["web_access"], "models": meta["models"],
             "model_version": meta.get("model_version"), "cost_usd_per_trial": meta.get("cost_usd_per_trial")}
    entry.update({k: meta.get(k) for k in (*OPEN_METHOD, "harness")})   # how the entry was made, shown with it
    entry["meta_sha256"] = _sha256_file(os.path.join(dest, "meta.json"))
    if of:
        entry["of"] = of
    reg.append(entry)
    _dump_json(reg, reg_path)
    return entry


def resolve_operations(round_dir: str, records: dict, read_date: str | None = None) -> dict:
    """Outcomes of the round's operations questions from records fetched on the read date: {nct_id: outcome}."""
    man = _load_json(os.path.join(round_dir, "manifest.json"))
    rows = _round_ops(round_dir) or {}
    rd = read_date or man.get("operations_read_date") or tops.OPS_READ_DATE
    return {n: tops.resolve(r, records.get(n), rd) for n, r in rows.items()}


def _round_sisters(round_dir: str, key: str = "trial_group") -> dict | None:
    """A map from sisters.json: trial_group (the sister groups), trial_sponsor, trial_china_only, or trial_below_bar
    (the trials kept although no results check reached the bar; every score is also shown without them)."""
    path = os.path.join(round_dir, "sisters.json")
    return _load_json(path).get(key) if os.path.exists(path) else None


MIN_GAP = 0.005          # "clearly better/worse" needs a Brier gap larger than this, fixed in advance
ALPHA = 0.05             # level of each entry's own two-sided tier test (2.5% per direction)
FAMILY_ALPHA = ALPHA     # kept for the exploratory pairwise comparisons (Holm over all pairs)
ADD_FOLDS = 10           # folds of whole sister groups for the "adds to the registry model" combination
ADD_REPEATS = 5          # fold splits averaged for its point estimate
ADD_BOOT = 500           # sister-group resamples, each refitting the whole cross-validation, for its interval
ADD_CLIP = 0.01          # probabilities kept within [0.01, 0.99] before the logit
ADD_RIDGE = 0.01         # small ridge on the combination's weights (not the intercept)
TIER_NAMES = {1: "clearly better than the registry model", 2: "no clear difference from the registry model",
              3: "clearly worse than the registry model"}


def _cluster_boot(se: dict, ids: list, clusters: dict | None, n_boot: int, seed: int):
    """Bootstrap Brier scores of several entries on the same resamples of whole sister groups.
    se: {entry: per-trial squared errors (array, in `ids` order)}. Returns {entry: array of n_boot Brier scores}."""
    import numpy as np
    gid = [(clusters or {}).get(n, n) for n in ids]
    _, inv = np.unique(np.array(gid, dtype=str), return_inverse=True)
    G = int(inv.max()) + 1
    size = np.bincount(inv, minlength=G).astype(float)
    rng = np.random.default_rng(seed)
    counts = rng.multinomial(G, np.full(G, 1.0 / G), size=n_boot).astype(float)       # n_boot x G
    den = counts @ size
    return {e: (counts @ np.bincount(inv, weights=v, minlength=G)) / den for e, v in se.items()}


def _holm(pvals: dict, alpha: float = FAMILY_ALPHA) -> set:
    """Holm's step-down procedure: the keys whose hypotheses are rejected at family-wise level alpha."""
    out, m = set(), len(pvals)
    for i, (k, p) in enumerate(sorted(pvals.items(), key=lambda kv: kv[1])):
        if p > alpha / (m - i):
            break
        out.add(k)
    return out


def _phi(z: float) -> float:
    import math
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _two_way(d: float, sd: float, gap: float) -> tuple[float, float]:
    """One-sided p-values for a Brier difference d (entry minus anchor; below 0 = entry better) being below -gap
    ("better") and above +gap ("worse"), from a normal approximation with the bootstrap standard deviation sd."""
    import math
    if not sd or not math.isfinite(sd) or sd <= 0:                 # no variation: the difference is exact
        return (0.0 if d < -gap else 1.0), (0.0 if d > gap else 1.0)
    return _phi((d + gap) / sd), 1.0 - _phi((d - gap) / sd)


def _sq_errors(preds: dict, ids: list, y):
    import numpy as np
    return {e: (np.array([tscore._p(p.get(n)) if tscore._p(p.get(n)) is not None else 0.5 for n in ids]) - y) ** 2
            for e, p in preds.items()}


def tiers(preds: dict, scored: list, clusters: dict | None, anchor: dict, n_boot: int = 2000, seed: int = 0,
          min_gap: float = MIN_GAP, alpha: float = ALPHA) -> dict:
    """Each entry's tier against the anchor (the registry model): 1 clearly better, 2 no clear difference, 3 clearly
    worse.

    Each entry is tested on its own, so its tier depends on nothing but its forecasts and the anchor's (other
    entries, or copies of the anchor, cannot move it). Two one-sided tests fixed in advance: Brier(entry) <
    Brier(anchor) - min_gap, and Brier(entry) > Brier(anchor) + min_gap. Their p-values come from a normal
    approximation with the standard deviation of the paired difference over a bootstrap that resamples sister groups
    together; the smaller is doubled, so neither direction is chosen after seeing the data, and compared with `alpha`.
    With many entries a few tiers can be chance: an entry whose true gap is at the margin is placed clearly better or
    worse at most `alpha`/2 of the time. Tier 2 means the data cannot tell the entry from the anchor, not that the two
    are equal."""
    import numpy as np
    ids = [k["nct_id"] for k in scored]
    y = np.array([float(k["met"]) for k in scored])
    se = _sq_errors(dict(preds, **{"\0anchor": anchor}), ids, y)
    boots = _cluster_boot(se, ids, clusters, n_boot, seed) if ids and n_boot > 1 else {}
    out = {}
    for e in preds:
        d = float(se[e].mean() - se["\0anchor"].mean())
        db = boots[e] - boots["\0anchor"] if boots else None
        sd = float(db.std(ddof=1)) if db is not None else 0.0
        pb, pw = _two_way(d, sd, min_gap)
        p = min(1.0, 2.0 * min(pb, pw))
        out[e] = {"brier_minus_registry_model": d, "sd": sd,
                  "ci95": [float(np.percentile(db, 2.5)), float(np.percentile(db, 97.5))] if db is not None else None,
                  "p_better": pb, "p_worse": pw, "p": p,
                  "gain_needed_for_tier_1": float(min_gap + 1.959964 * sd) if sd else None,
                  "tier": (1 if pb < pw else 3) if p < alpha else 2}
    return {"by_entry": out, "n_boot": n_boot, "min_gap": min_gap, "alpha": alpha, "n_entries_tested": len(out),
            "correction": "none across entries: each entry is tested on its own; per entry the smaller one-sided "
                          "p-value, doubled, against alpha"}


def _logit(p):
    import numpy as np
    p = np.clip(p, ADD_CLIP, 1 - ADD_CLIP)
    return np.log(p / (1 - p))


def _fit_logistic(X, y, w=None, ridge: float = ADD_RIDGE, iters: int = 100):
    """Logistic regression by Newton's method, with case weights `w` (default 1) and a small ridge on every weight
    but the intercept (column 0)."""
    import numpy as np
    w = np.ones(len(y)) if w is None else w
    b = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], ridge)
    pen[0] = 1e-9
    for _ in range(iters):
        mu = 1 / (1 + np.exp(-(X @ b)))
        g = X.T @ (w * (mu - y)) + pen * b
        H = X.T @ (X * (w * mu * (1 - mu))[:, None]) + np.diag(pen)
        step = np.linalg.solve(H, g)
        b = b - step
        if np.max(np.abs(step)) < 1e-10:
            break
    return b


def _cv_gain(X_a, X_c, y, gid, w, folds: int, seed: int) -> float:
    """Out-of-fold Brier gain (anchor recalibrated minus combination), folds of whole groups (gid: group index of each
    trial), with case weights w (a bootstrap resample's group counts; copies of a group share its fold)."""
    import numpy as np
    G = int(gid.max()) + 1
    rng = np.random.default_rng(seed)
    fold_of = np.empty(G, dtype=int)
    fold_of[rng.permutation(G)] = np.arange(G) % folds
    f = fold_of[gid]
    num = 0.0
    for k in range(folds):
        tr, te = (f != k) & (w > 0), (f == k) & (w > 0)
        if not te.any() or not tr.any():
            continue
        pa = 1 / (1 + np.exp(-(X_a[te] @ _fit_logistic(X_a[tr], y[tr], w[tr]))))
        pc = 1 / (1 + np.exp(-(X_c[te] @ _fit_logistic(X_c[tr], y[tr], w[tr]))))
        num += float(np.sum(w[te] * ((pa - y[te]) ** 2 - (pc - y[te]) ** 2)))
    return num / float(np.sum(w))


def adds_to(entry: dict, anchor: dict, scored: list, clusters: dict | None, folds: int = ADD_FOLDS,
            n_boot: int = ADD_BOOT, seed: int = 0, repeats: int = ADD_REPEATS) -> dict | None:
    """Does the entry add to the registry model? Exploratory, shown, never ranked.

    A logistic regression of the outcome on logit(anchor) and logit(entry), fitted out of fold in `folds` folds of
    whole sister groups, against the same regression on logit(anchor) alone (the anchor recalibrated, so
    recalibration gains nothing by itself). The Brier gain (anchor alone minus combination; above 0 = the entry adds)
    is averaged over `repeats` random fold splits. Its uncertainty comes from `n_boot` resamples of whole sister
    groups, each running the same estimator (the same `repeats` fold splits, every fold refitted), so it carries the
    uncertainty of the fitting as well as of the trials. The 95% interval is the gain plus or minus 1.96 bootstrap
    standard deviations (steadier than a percentile from a few tail draws; the percentile interval is shown too).
    "adds" needs that interval above 0 and a positive weight on the entry: an entry that is informative only when
    turned upside down does not add, and its gain is not shown. None with too few trials or groups."""
    import numpy as np
    ids = [k["nct_id"] for k in scored]
    gnames = [str((clusters or {}).get(n, n)) for n in ids]
    _, gid = np.unique(np.array(gnames), return_inverse=True)
    G = int(gid.max()) + 1 if len(ids) else 0
    if G < folds or len(ids) < 2 * folds:
        return None
    y = np.array([float(k["met"]) for k in scored])
    pa = np.array([tscore._p(anchor.get(n)) if tscore._p(anchor.get(n)) is not None else 0.5 for n in ids])
    pe = np.array([tscore._p(entry.get(n)) if tscore._p(entry.get(n)) is not None else 0.5 for n in ids])
    one = np.ones(len(ids))
    X_a = np.column_stack([one, _logit(pa)])
    X_c = np.column_stack([one, _logit(pa), _logit(pe)])
    def estimate(w):                                     # the reported estimator: the mean over the same fold splits
        return [_cv_gain(X_a, X_c, y, gid, w, folds, seed + r) for r in range(repeats)]
    gains = estimate(np.ones(len(ids)))
    gain = float(np.mean(gains))
    ci = pct = sd = None
    if n_boot > 1:
        rng = np.random.default_rng(seed + 1000)
        counts = rng.multinomial(G, np.full(G, 1.0 / G), size=n_boot).astype(float)
        bg = np.array([np.mean(estimate(counts[b][gid])) for b in range(n_boot)])
        sd = float(bg.std(ddof=1))
        ci = [gain - 1.959964 * sd, gain + 1.959964 * sd]
        pct = [float(np.percentile(bg, 2.5)), float(np.percentile(bg, 97.5))]
    b = _fit_logistic(X_c, y)
    positive = bool(b[2] > 0)
    return {"brier_gain": gain if positive else None, "brier_gain_any_sign": gain, "ci95": ci if positive else None,
            "ci95_percentile": pct if positive else None, "sd": sd, "adds": bool(positive and ci and ci[0] > 0),
            "weight_registry_model": float(b[1]), "weight_entry": float(b[2]), "positive_weight": positive,
            "folds": folds, "repeats": repeats, "n_boot": n_boot, "gain_by_split": [float(x) for x in gains],
            "exploratory": True}


def pairwise(preds: dict, scored: list, clusters: dict | None, n_boot: int, seed: int = 0,
             min_gap: float = MIN_GAP, alpha: float = FAMILY_ALPHA) -> dict:
    """Exploratory comparisons between entries, never used for the ranking: for each pair, the same two one-sided
    tests as the tiers (gap `min_gap`, bootstrap standard deviation, normal approximation, smaller p doubled),
    Holm-corrected over all pairs. Returns {"pairs": [...], ...}; each pair has the Brier difference a minus b, its
    95% interval, the p-value and which entry, if either, is clearly better."""
    import numpy as np
    ids = [k["nct_id"] for k in scored]
    y = np.array([float(k["met"]) for k in scored])
    names = list(preds)
    se = _sq_errors(preds, ids, y)
    boots = _cluster_boot(se, ids, clusters, n_boot, seed) if ids and n_boot > 1 else {}
    pairs, pv = {}, {}
    for i_, a in enumerate(names):
        for b in names[i_ + 1:]:
            d = float(se[a].mean() - se[b].mean())
            db = boots[a] - boots[b] if boots else None
            sd = float(db.std(ddof=1)) if db is not None else 0.0
            pa_, pb_ = _two_way(d, sd, min_gap)
            pv[(a, b)] = min(1.0, 2.0 * min(pa_, pb_))
            pairs[(a, b)] = {"a": a, "b": b, "brier_a_minus_b": d, "p": pv[(a, b)], "_a_better": pa_ < pb_,
                             "ci95": [float(np.percentile(db, 2.5)), float(np.percentile(db, 97.5))]
                             if db is not None else None}
    rejected = _holm(pv, alpha) if pv else set()
    for k, r in pairs.items():
        r["clearly_better"] = (r["a"] if r.pop("_a_better") else r["b"]) if k in rejected else None
    return {"pairs": list(pairs.values()), "n_boot": n_boot, "min_gap": min_gap, "alpha": alpha,
            "correction": "Holm over all pairs", "exploratory": True}


def _pass_view(preds: dict, suffix: str) -> dict:
    """The forecasts a pass scores. In the early and final passes, `p_met` is the entry's p_met_mar or p_met_dec where
    it gave one (else its p_met), and `p_public` is its p_public_mar or p_public_dec (no fallback: a block of its own)."""
    if not suffix:
        return preds
    out = {}
    for n, o in preds.items():
        v = dict(o)
        if tscore._p({"p_met": o.get("p_met" + suffix)}) is not None:
            v["p_met"] = o["p_met" + suffix]
        v["p_public"] = o.get("p_public" + suffix)
        out[n] = v
    return out


def _brier_share(preds: dict, ys: dict, field: str) -> dict:
    """Brier score of one probability field against outcomes ys ({nct_id: 1 or 0}), with the share in the round itself
    (computed after the fact) as the reference. Shown, never ranked."""
    share = sum(ys.values()) / len(ys) if ys else None
    sq, sq_ref = [], []
    for n, y in ys.items():
        p = (preds.get(n) or {}).get(field)
        if isinstance(p, (int, float)) and not isinstance(p, bool) and 0 <= p <= 1:
            sq.append((p - y) ** 2)
            sq_ref.append((share - y) ** 2)
    b = sum(sq) / len(sq) if sq else None
    r = sum(sq_ref) / len(sq_ref) if sq_ref else None
    return {"n_resolved": len(ys), "n_scored": len(sq), "share": share, "brier": b, "brier_share_in_round": r,
            "skill": (1 - b / r) if b is not None and r else None}


def number_tiers(preds: dict, ref: dict, cards: dict, truth: dict, floors: dict | None, clusters: dict | None,
                 n_boot: int = 2000, seed: int = 0, min_gap: float = NUMBERS_GAP, alpha: float = ALPHA,
                 min_scored: int = MIN_NUMBERS_SCORED) -> dict:
    """Each entry's number tier against the frozen reference entry (ref-opus-5-5): 1 clearly better (a number score
    lower by more than min_gap), 2 no clear difference, 3 clearly worse; None with fewer than min_scored number answers
    (a control or an effect value counts as one) scored for both. The same test as `tiers`, on the paired difference of
    the scaled percentile scores over the answers both gave, resampling whole sister groups."""
    import numpy as np
    rq = {k: v[0] for k, v in tnum.per_question(ref, ref, cards, truth, floors).items() if k[0] != "n_published"}
    out = {}
    for e, p in preds.items():
        q = {k: v[0] for k, v in tnum.per_question(p, ref, cards, truth, floors).items() if k[0] != "n_published"}
        keys = sorted(k for k in q if k in rq)
        n_trials = len({n for n, _ in keys})
        if len(keys) < max(min_scored, 2):
            out[e] = {"n": len(keys), "n_questions": n_trials, "tier": None}
            continue
        ids = [f"{n}|{w}" for n, w in keys]
        cl = {f"{n}|{w}": (clusters or {}).get(n, n) for n, w in keys}
        se = {"e": np.array([q[k] for k in keys]), "a": np.array([rq[k] for k in keys])}
        d = float(se["e"].mean() - se["a"].mean())
        b = _cluster_boot(se, ids, cl, n_boot, seed) if n_boot > 1 else None
        sd = float((b["e"] - b["a"]).std(ddof=1)) if b else 0.0
        pb, pw = _two_way(d, sd, min_gap)
        pv = min(1.0, 2.0 * min(pb, pw))
        out[e] = {"n": len(keys), "n_questions": n_trials, "score_minus_reference": d, "sd": sd, "p_better": pb, "p_worse": pw, "p": pv,
                  "ci95": ([float(np.percentile(b["e"] - b["a"], 2.5)), float(np.percentile(b["e"] - b["a"], 97.5))]
                           if b else None),
                  "tier": (1 if pb < pw else 3) if pv < alpha else 2}
    return {"by_entry": out, "n_boot": n_boot, "min_gap": min_gap, "alpha": alpha, "min_scored": min_scored}


def _joint_score(preds: dict, y: dict) -> dict:
    """Brier score of p_met x p_public against "a statement on the primary result after the close and by the deadline,
    and met" (y: {nct_id: 1 or 0}, over the trials whose p_public is resolved), with the share in the round itself as
    the reference. Shown, never ranked."""
    share = sum(y.values()) / len(y) if y else None
    sq, sq_ref = [], []
    for n, v in y.items():
        o = preds.get(n) or {}
        pm, pp = tscore._p(o), o.get("p_public")
        if pm is None or isinstance(pp, bool) or not isinstance(pp, (int, float)) or not 0 <= pp <= 1:
            continue
        sq.append((pm * pp - v) ** 2)
        sq_ref.append((share - v) ** 2)
    complete = len(sq) == len(y)                    # shown only for an entry that answered every resolved trial
    b = sum(sq) / len(sq) if sq and complete else None
    r = sum(sq_ref) / len(sq_ref) if sq_ref and complete else None
    return {"n_resolved": len(y), "n_scored": len(sq), "share": share, "brier": b, "brier_share_in_round": r,
            "skill": (1 - b / r) if b is not None and r else None}


SETUP_KEYS = ("models", "model_version", "harness", "setting", "web_access", "run_settings")


def load_void(round_dir: str, trials) -> dict:
    """The organiser's void list (void.jsonl in the round folder), checked: every line a JSON object with an nct_id
    of this round (upper-cased), a non-empty reason and a date (YYYY-MM-DD); no trial twice. Anything else stops with
    the line number, so that a typo can never leave a trial scored while the output calls it void."""
    path = os.path.join(round_dir, "void.jsonl")
    if not os.path.exists(path):
        return {}
    known, out = set(trials), {}
    for i, line in enumerate(open(path, encoding="utf-8-sig"), 1):      # a BOM (Windows editors) is read as nothing
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"void.jsonl line {i}: not valid JSON ({e.msg})") from None
        if not isinstance(o, dict):
            raise ValueError(f"void.jsonl line {i}: not a JSON object")
        nid = str(o.get("nct_id") or "").strip().upper()
        if nid not in known:
            raise ValueError(f"void.jsonl line {i}: {nid or 'no nct_id'} is not a trial of this round")
        if nid in out:
            raise ValueError(f"void.jsonl line {i}: {nid} is listed twice")
        if not (isinstance(o.get("reason"), str) and o["reason"].strip()):
            raise ValueError(f"void.jsonl line {i}: {nid} needs a reason")
        if not (isinstance(o.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", o["date"])):
            raise ValueError(f"void.jsonl line {i}: {nid} needs a date as YYYY-MM-DD")
        try:
            _dt.date.fromisoformat(o["date"])
        except ValueError:
            raise ValueError(f"void.jsonl line {i}: {nid}: {o['date']} is not a date") from None
        out[nid] = dict(o, nct_id=nid)
    return out


def leaderboard(build: str, round_dir: str, n_boot: int = 2000, min_scored: int = MIN_SCORED, seed: int = 0,
                ref_id: str = "ref-b0", b1_id: str = "ref-b1", numbers_ref_id: str = "ref-opus-5-5",
                ops_outcomes: str | None = None, scoring_pass: str = "first",
                labels_as_of: str | None = None, next_step_outcomes: str | None = None,
                amend_outcomes: str | None = None, assumption_checks: str | None = None,
                min_numbers_scored: int = MIN_NUMBERS_SCORED) -> dict:
    """Score every registered entry on the trials that reported after the round closed and on or before the pass's
    deadline (`scoring_pass` "early": the manifest's early_deadline; "first": its deadline; "final": its
    final_deadline). Each pass scores the forecasts asked for it (_pass_view: p_met_mar or p_met_dec where given, else
    p_met). The first pass ranks; the early pass shows tiers too, as an early look, and the final pass none.

    Two boards: "models" (setting closed: one model, the round's instructions, the packet only, as declared by the
    entrant; the organiser's model runs are on it) and "open" (everything else). In the first pass, once `min_scored`
    trials are scored, every entry is placed in a tier against the registry model (`b1_id`; see `tiers`: each entry
    tested on its own), and each board lists its rows by tier, then by Brier score. The final pass is supplementary and never ranks. The base rate (`ref_id`) and the registry model are
    baselines, listed apart. Every row has the skill against both with paired 95% intervals from a bootstrap that
    resamples sister-trial groups together (sisters.json), the same against the registry model with sponsor-level
    clusters (a sensitivity check) and split by China-only trials (the registry model leans on that feature), AUROC,
    the Brier score's reliability, resolution and level gap, and whether it adds to the registry model (`adds_to`).
    An entry uploaded more than once is also scored on its first upload (kind "first_upload"), shown next to the
    last. Rounds with question cards also get the number score (against the frozen reference entry `numbers_ref_id`,
    with width floors), the subgroup score and the consistency check; rounds with operations questions their
    operations score once `ops_outcomes` (JSONL of operations.resolve outputs) is given. In the first pass, given
    `labels_as_of` (the day the first pass's labels are as of; there is no default) after the deadline, also the
    p_public score and the joint score of p_met x p_public against "a statement on the primary result by the deadline,
    and met". Only the tiers rank; comparisons between entries and the "adds to" test are exploratory."""
    import numpy as np
    man = _load_json(os.path.join(round_dir, "manifest.json"))
    reg = _load_json(os.path.join(round_dir, "registry.json"))
    key = {k["nct_id"]: k for k in _load_json(os.path.join(build, "private", "key_C.json"))}
    closes = man["closes"]
    cards = _round_cards(round_dir)
    ops_rows = _round_ops(round_dir)
    clusters = _round_sisters(round_dir)
    sponsors = _round_sisters(round_dir, "trial_sponsor")
    china = _round_sisters(round_dir, "trial_china_only")
    below = _round_sisters(round_dir, "trial_below_bar") or {}
    # the organiser's void list (void.jsonl in the round folder, one {"nct_id", "reason", "date"} per line): trials
    # found after launch to have had a public statement on a registered primary before the round opened (a safety
    # statement on a safety primary, say), which the labels' first_public_date does not catch. They are scored on
    # nothing: not p_met, not the numbers, not the operations questions.
    voided = load_void(round_dir, man["trials"])
    if voided and ops_rows:
        ops_rows = {n: r for n, r in ops_rows.items() if n not in voided}
    if scoring_pass not in PASSES:
        raise ValueError("scoring_pass is 'early', 'first' or 'final'")
    deadline_key, suffix = PASSES[scoring_pass]
    if suffix and not man.get("early_deadline"):     # a round staged without the early deadline asks no p_met_dec,
        suffix = ""                                  # p_public_mar or p_public_dec (validate ignores them)
    deadline = man.get(deadline_key) or (man.get("deadline") if scoring_pass == "final" else None)
    if scoring_pass == "early" and not deadline:
        raise ValueError("this round has no early pass")
    # the labels must have been read for this pass (finalize_labels.py writes the deadline and as-of day it used)
    read_for = sorted({k["label_deadline"] for k in key.values() if k.get("label_deadline")})
    if deadline and read_for and read_for != [deadline]:
        raise ValueError(f"the build's labels were read for the deadline {', '.join(read_for)}, not this pass's "
                         f"({deadline}): build the key from this pass's labels")
    as_of_seen = sorted({k["labels_as_of"] for k in key.values() if k.get("labels_as_of")})
    if len(as_of_seen) > 1 or (labels_as_of and as_of_seen and as_of_seen != [labels_as_of]):
        raise ValueError(f"labels_as_of {labels_as_of} does not match the build's labels (as of {', '.join(as_of_seen)})")
    labels_as_of = labels_as_of or (as_of_seen[0] if as_of_seen else None)
    pm_trials = [n for n in man["trials"] if tnum.has_p_met((cards or {}).get(n)) and n not in voided]
    resolved = [key[n] for n in pm_trials
                if n in key and key[n].get("met") in (0, 1) and key[n].get("first_public_date")]
    scored = [k for k in resolved if k["first_public_date"] > closes and (not deadline or k["first_public_date"] <= deadline)]
    dropped = sorted(k["nct_id"] for k in resolved if k["first_public_date"] <= closes)
    late = sorted(k["nct_id"] for k in resolved if deadline and k["first_public_date"] > deadline)
    outcomes = tops.load_rows(ops_outcomes) if ops_outcomes else None
    if outcomes and voided:
        outcomes = {n: o for n, o in outcomes.items() if n not in voided}
    # p_public of this pass and the joint score: from this pass's labels, once they are as of after its deadline
    public_q = "p_public" + suffix
    public = (tops.public_outcomes(ops_rows, key, closes, deadline, public_q)
              if ops_rows and deadline and labels_as_of and labels_as_of > deadline
              and (scoring_pass == "first" or suffix)       # each pass scores the p_public asked for its own date
              and any(public_q in r.get("questions", []) for r in ops_rows.values()) else None)
    joint_y = ({n: int(o["public"] == 1 and key[n].get("met") == 1) for n, o in public.items() if o["public"] in (0, 1)}
               if public is not None else None)
    truth = {k["nct_id"]: {f: k.get(f) for f in ("control_value", "effect_value", "women_effect", "men_effect",
                                                 "subgroup_effects", "safety_experimental", "safety_control")}
             for k in scored}
    # the key secondary endpoint: scored where its result is public by the deadline (key rows carry key_secondary_met)
    ks_y = {k["nct_id"]: int(k["key_secondary_met"]) for k in scored if k.get("key_secondary_met") in (0, 1)
            and tnum.key_secondary((cards or {}).get(k["nct_id"]))}
    # questions read later, from files of their own: the next step (by the final deadline), amendments (read date)
    in_round, before_close = set(man["trials"]) - set(voided), set(dropped)
    next_y = ({n: int(o["next_step"]) for n, o in tops.load_rows(next_step_outcomes).items()
               if o.get("next_step") in (0, 1) and not o.get("void") and n in in_round and n in key
               and n not in before_close
               and tnum.next_step((cards or {}).get(n))}  # void if it reported before the close; a trial that left
              # the round is void too: the organiser marks it "void" in the outcome file (next_step_label_instructions)
              if next_step_outcomes else None)
    amended = tops.load_rows(amend_outcomes) if amend_outcomes else None
    if amended and voided:
        amended = {n: o for n, o in amended.items() if n not in voided}
    checks = None
    if assumption_checks:                       # one row per entry: {"entry", "n_checked", "n_supported", ...}
        with open(assumption_checks, encoding="utf-8") as fh:
            checks = {r["entry"]: r for r in (json.loads(x) for x in fh if x.strip())}
    vague_only = [k["nct_id"] for k in scored if k.get("vague_at_deadline")]   # only vague at the deadline: not met
    scored_wo = [k for k in scored if not k.get("vague_at_deadline")]
    scored_nb = [k for k in scored if not below.get(k["nct_id"])]     # without the trials kept below the bar
    raw_of = {e["id"]: load_forecasts(os.path.join(round_dir, e["forecasts"])) for e in reg}
    if scoring_pass == "early":         # B0 and B1 must be worked out for the early date (make_baselines.py)
        short = {i: sum(tscore._p({"p_met": (raw_of[i].get(n) or {}).get("p_met_mar")}) is None for n in pm_trials)
                 for i in (ref_id, b1_id) if i in raw_of}
        if any(short.values()):
            raise ValueError("the early pass needs the baselines worked out for its date: p_met_mar is missing in "
                             + ", ".join(f"{i} ({k} trials)" for i, k in short.items() if k)
                             + "; re-run make_baselines.py on the round staged with --early-deadline")
    preds_of = {i: _pass_view(p, suffix) for i, p in raw_of.items()}

    nref = preds_of.get(numbers_ref_id) if cards else None
    floors = tnum.width_floors(nref, cards) if nref else None
    left_out = sorted(n for n in pm_trials if n not in key)
    sets = tuple(sorted({k["set"] for k in scored})) or ("post_cutoff",)
    # the December pass has no skill against B0 or B1: their June forecasts are not matched to its windows
    refs = ({name: preds_of[i] for name, i in (("base_rate", ref_id), ("registry_model", b1_id)) if i in preds_of}
            if scoring_pass != "final" else {})
    b1 = refs.get("registry_model")
    boot = n_boot if len(scored) >= 2 else 0
    rows = []
    for e in reg:
        preds = preds_of[e["id"]]
        rep = tscore.score(preds, scored, None, cutoff=None, sets=sets, n_boot=boot, seed=seed, refs=dict(refs),
                           clusters=clusters, strict=bool(scored))
        if suffix:          # the share of the entry's p_met answers this pass takes from p_met (no p_met_mar/p_met_dec)
            raw = raw_of[e["id"]]
            gave = [n for n in pm_trials if tscore._p(raw.get(n) or {}) is not None]
            fb = sum(tscore._p({"p_met": (raw.get(n) or {}).get("p_met" + suffix)}) is None for n in gave)
        prob = rep.get("probability", {})
        ci = rep.get("ci95") or {}
        row = {k: e.get(k) for k in ("id", "name", "team", "kind", "received", "setting", "web_access", "models",
                                     "model_version", "cost_usd_per_trial", "sha256", "of", *OPEN_METHOD,
                                     "harness")}
        row["board"] = ("baseline" if e["id"] in (ref_id, b1_id) else None if e["kind"] == "first_upload"
                        else board(e, e["kind"] == "reference"))
        row["p_met_fallback_share"] = (fb / len(gave) if gave else None) if suffix else None
        row.update({"n_scored": rep.get("n_questions", 0), "brier": prob.get("brier"), "brier_ci95": ci.get("brier"),
                    "bss_vs_base_rate": prob.get("bss_vs_base_rate"), "bss_vs_base_rate_ci95": ci.get("bss_vs_base_rate"),
                    "bss_vs_registry_model": prob.get("bss_vs_registry_model"),
                    "bss_vs_registry_model_ci95": ci.get("bss_vs_registry_model"),
                    "log_loss": prob.get("log_loss"),
                    "auroc": prob.get("auroc") if rep.get("n_questions", 0) >= 10 else None,
                    "auroc_ci95": ci.get("auroc") if rep.get("n_questions", 0) >= 10 else None,
                    "reliability": prob.get("reliability"), "resolution": prob.get("resolution"),
                    "level_gap": prob.get("level_gap"), "mean_p_met": prob.get("mean_pred"),
                    "calibration_slope": prob.get("calibration_slope"), "hazard_ratio": rep.get("hazard_ratio")})
        if e["kind"] == "first_upload":
            rows.append(row)
            continue
        if sponsors and boot:                               # sensitivity: sponsor-level clusters instead of sisters
            rs = tscore.score(preds, scored, None, cutoff=None, sets=sets, n_boot=boot, seed=seed,
                              refs={k: v for k, v in refs.items() if k == "registry_model"}, clusters=sponsors,
                              strict=True)
            row["bss_vs_registry_model_ci95_sponsor_clusters"] = (rs.get("ci95") or {}).get("bss_vs_registry_model")
        if china and b1 is not None:
            row["bss_vs_registry_model_by_china_only"] = {}
            for flag, name in ((True, "china_only"), (False, "other")):
                sub = [k for k in scored if bool(china.get(k["nct_id"])) == flag]
                rc = tscore.score(preds, sub, None, cutoff=None, sets=sets, n_boot=n_boot if len(sub) >= 2 else 0,
                                  seed=seed, refs={"registry_model": b1}, clusters=clusters) if sub else {}
                row["bss_vs_registry_model_by_china_only"][name] = {
                    "n": len(sub), "bss": (rc.get("probability") or {}).get("bss_vs_registry_model"),
                    "ci95": (rc.get("ci95") or {}).get("bss_vs_registry_model")}
        if vague_only and len(scored_wo) >= 2:            # sensitivity: without the vague-only readouts
            rv = tscore.score(preds, scored_wo, None, cutoff=None, sets=sets, n_boot=boot, seed=seed,
                              refs={"registry_model": b1} if b1 is not None else None, clusters=clusters, strict=True)
            row["without_vague_only"] = {"n": len(scored_wo), "brier": (rv.get("probability") or {}).get("brier"),
                                         "bss_vs_registry_model": (rv.get("probability") or {}).get(
                                             "bss_vs_registry_model"),
                                         "bss_vs_registry_model_ci95": (rv.get("ci95") or {}).get(
                                             "bss_vs_registry_model")}
        if any(below.get(k["nct_id"]) for k in scored) and len(scored_nb) < 2:   # said, not left out silently
            row["without_below_bar"] = {"n": len(scored_nb), "not_computable": "fewer than 2 scored trials without "
                                        "the below-bar trials"}
        elif any(below.get(k["nct_id"]) for k in scored):   # Brier, skill vs the registry model and tier without them
            rb = tscore.score(preds, scored_nb, None, cutoff=None, sets=sets, n_boot=boot, seed=seed,
                              refs={"registry_model": b1} if b1 is not None else None, clusters=clusters, strict=True)
            row["without_below_bar"] = {"n": len(scored_nb), "brier": (rb.get("probability") or {}).get("brier"),
                                        "bss_vs_registry_model": (rb.get("probability") or {}).get(
                                            "bss_vs_registry_model"),
                                        "bss_vs_registry_model_ci95": (rb.get("ci95") or {}).get(
                                            "bss_vs_registry_model")}
        if b1 is not None and e["id"] != b1_id:
            row["adds_to_registry_model"] = adds_to(preds, b1, scored, clusters, n_boot=ADD_BOOT if boot else 0,
                                                    seed=seed)
        if cards is not None:
            row.pop("hazard_ratio")
            row["numbers"] = tnum.number_scores(preds, nref, cards, truth, floors) if nref else None
            row["subgroups"] = tnum.subgroup_scores(preds, nref, cards, truth, floors) if nref else None
            # the stated p_met (not this pass's p_met_mar or p_met_dec) against the p_met its own numbers imply
            row["consistency"] = tnum.consistency(raw_of[e["id"]], cards, [k["nct_id"] for k in scored])
            row["safety"] = tnum.safety_scores(preds, {n: t for n, t in truth.items()
                                                       if tnum.has_safety(cards.get(n))})
            row["key_secondary"] = _brier_share(preds, ks_y, "p_key_secondary")
            if next_y is not None:
                row["next_step"] = _brier_share(preds, next_y, "p_next_step")
        if outcomes is not None:
            row["operations"] = tops.ops_scores(preds, outcomes)
        if amended is not None:
            row["amended"] = tops.ops_scores(preds, amended, questions=("p_amended",))["p_amended"]
        if public is not None:
            row["p_public"] = tops.ops_scores(preds, public, questions=("p_public",))["p_public"]
            row["met_by_deadline"] = _joint_score(preds, joint_y)
        if checks is not None and e["id"] in checks:        # the organiser's check of the entry's assumptions
            row["assumptions"] = {k: checks[e["id"]].get(k) for k in ("n_checked", "n_supported", "n_not_supported",
                                                                      "n_not_checkable", "share_supported")}
        rows.append(row)
    # first uploads: scored next to the last upload, on the same trials, never ranked
    firsts = {r["of"]: r for r in rows if r["kind"] == "first_upload"}
    rows = [r for r in rows if r["kind"] != "first_upload"]
    ids = [k["nct_id"] for k in scored]
    for r in rows:
        f = firsts.get(r["id"])
        if f is None:
            continue
        r["first_upload"] = {k: f[k] for k in ("id", "received", "sha256", "brier", "bss_vs_registry_model")}
        # the setups of both uploads: a change of model or harness is not "more time to forecast"
        m_last, m_first = (_load_json(os.path.join(round_dir, "entries", i, "meta.json")) for i in (r["id"], f["id"]))
        r["first_upload"]["setup"] = {k: m_first.get(k) for k in SETUP_KEYS}
        r["first_upload"]["setup_last"] = {k: m_last.get(k) for k in SETUP_KEYS}
        r["first_upload"]["same_setup"] = all(m_first.get(k) == m_last.get(k) for k in SETUP_KEYS)
        if ids:
            y = np.array([float(k["met"]) for k in scored])
            se = _sq_errors({"last": preds_of[r["id"]], "first": preds_of[f["id"]]}, ids, y)
            r["first_upload"]["brier_last_minus_first"] = float(se["last"].mean() - se["first"].mean())
            if boot:
                b = _cluster_boot(se, ids, clusters, boot, seed)
                d = b["last"] - b["first"]
                r["first_upload"]["ci95"] = [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]
    # the June pass ranks, in tiers on each board; the March pass shows tiers as an early look; the December pass is
    # supplementary and has none. The number score has tiers of its own against the reference entry, in June only.
    # Tiers are shown only once the pass's labels are complete (as of after its deadline): the monthly updates before
    # that show scores and intervals, since repeated looks would multiply the chance of a false "clearly better".
    labels_complete = not deadline or bool(labels_as_of and labels_as_of > deadline)   # a round with no deadline: always
    tiered = scoring_pass in ("early", "first") and len(scored) >= min_scored and labels_complete
    ranked = scoring_pass == "first" and tiered
    number_tier_tests = {}
    tier_tests = {}
    boards = {}
    for bd in BOARDS:
        members = [r for r in rows if r["board"] == bd]
        if tiered and b1 is not None and members and boot:
            t = tiers({r["id"]: preds_of[r["id"]] for r in members}, scored, clusters, b1, n_boot=boot, seed=seed)
            for r in members:
                r["tier"] = t["by_entry"][r["id"]]["tier"]
                r["tier_test"] = t["by_entry"][r["id"]]
            tier_tests[bd] = {k: v for k, v in t.items() if k != "by_entry"}
            if vague_only and len(scored_wo) >= 2:      # the tier each would get without them: a sensitivity check
                t2 = tiers({r["id"]: preds_of[r["id"]] for r in members}, scored_wo, clusters, b1, n_boot=boot,
                           seed=seed)
                for r in members:
                    if r.get("without_vague_only"):
                        r["without_vague_only"]["tier"] = t2["by_entry"][r["id"]]["tier"]
            if any(r.get("without_below_bar") for r in members) and len(scored_nb) >= 2:   # and without the below-bar
                t3 = tiers({r["id"]: preds_of[r["id"]] for r in members}, scored_nb, clusters, b1, n_boot=boot,
                           seed=seed)
                for r in members:
                    if r.get("without_below_bar") and "not_computable" not in r["without_below_bar"]:
                        r["without_below_bar"]["tier"] = t3["by_entry"][r["id"]]["tier"]
            for r in members:                       # how many entries were tested, for reading the exploratory test
                if r.get("adds_to_registry_model"):
                    r["adds_to_registry_model"]["n_entries_tested_on_board"] = len(members)
            members.sort(key=lambda r: (r["tier"], r["brier"] if r["brier"] is not None else 1e9, r["id"]))
        elif tiered:
            members.sort(key=lambda r: (r["brier"] if r["brier"] is not None else 1e9, r["id"]))
        else:
            members.sort(key=lambda r: (r["received"], r["id"]))
        # the second ranking: number tiers against the reference entry, in the first pass only, on their own gate
        # (min_numbers_scored number questions), whether or not the p_met tiers are shown yet
        if scoring_pass == "first" and labels_complete and nref is not None and cards is not None and members and boot:
            with_numbers = {r["id"]: preds_of[r["id"]] for r in members if r["id"] != numbers_ref_id
                            and (r.get("numbers") or {}).get("n_scored")}
            if with_numbers:
                nt = number_tiers(with_numbers, nref, cards, truth, floors, clusters, n_boot=boot, seed=seed,
                                  min_scored=min_numbers_scored)
                for r in members:
                    if r["id"] in nt["by_entry"]:
                        r["number_tier"] = nt["by_entry"][r["id"]]["tier"]
                        r["number_tier_test"] = nt["by_entry"][r["id"]]
                number_tier_tests[bd] = {k: v for k, v in nt.items() if k != "by_entry"}
        boards[bd] = [r["id"] for r in members]
    order = {i: n for n, i in enumerate(boards["models"] + boards["open"])}
    entries = sorted((r for r in rows if r["kind"] == "entry"), key=lambda r: order.get(r["id"], 1e9))
    references = sorted((r for r in rows if r["kind"] == "reference"), key=lambda r: (order.get(r["id"], 1e9), r["id"]))
    pw = None
    if len(rows) >= 2 and boot:
        pw = pairwise({r["id"]: preds_of[r["id"]] for r in rows if r["board"] in BOARDS}, scored, clusters, boot,
                      seed) if sum(r["board"] in BOARDS for r in rows) >= 2 else None
    y = [k["met"] for k in scored]
    return {"round": man["round"], "closes": closes, "scoring_pass": scoring_pass,
            "computed_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": {"n_trials": man["n_trials"], "n_p_met_questions": len(pm_trials), "n_scored": len(scored),
                       "share_met_among_scored": (sum(y) / len(y)) if y else None,
                       "n_vague_only_scored_not_met": len(vague_only),
                       "n_below_bar_scored": len(scored) - len(scored_nb),
                       "n_sister_groups_scored": len({(clusters or {}).get(k["nct_id"], k["nct_id"]) for k in scored}),
                       "n_dropped_reported_before_close": len(dropped),
                       "n_left_out_by_later_build": len(left_out), "n_reported_after_deadline": len(late),
                       "n_pending": len(pm_trials) - len(scored) - len(dropped) - len(left_out) - len(late),
                       "ranked": ranked, "tiers_shown": tiered, "early_look": scoring_pass == "early",
                       "labels_complete": labels_complete,
                       "min_scored_to_rank": min_scored, "deadline": deadline,
                       "n_key_secondary_resolved": len(ks_y),
                       "numbers_reference": numbers_ref_id if cards is not None else None,
                       "operations_resolved": ({q: sum(o.get(tops.OUTCOME[q]) in (0, 1) for o in outcomes.values())
                                                for q in tops.REGISTRY_QUESTIONS} if outcomes is not None else None),
                       "p_public_resolved": (sum(o["public"] in (0, 1) for o in public.values())
                                             if public is not None else None),
                       "labels_as_of": labels_as_of,
                       "share_met_by_deadline": (sum(joint_y.values()) / len(joint_y) if joint_y else None),
                       "share_public_by_deadline": ((lambda v: sum(v) / len(v) if v else None)(
                           [o["public"] for o in public.values() if o["public"] in (0, 1)])
                                                    if public is not None else None)},
            "supplementary": scoring_pass == "final", "number_tier_rule": number_tier_tests or None,
            "dropped": dropped, "void": sorted(voided), "left_out": left_out, "reported_after_deadline": late,
            "boards": boards, "board_names": BOARDS, "tier_names": TIER_NAMES, "tier_rule": tier_tests or None,
            "entries": entries, "references": references,
            "pairwise_exploratory": pw}
