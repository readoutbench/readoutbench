"""Round 1 (rebuilt): the question list.

usage: python3 -I build_list.py <merged_all.jsonl> <results_status.jsonl> <round1 manifest.json> <out dir>
                                [--labels labels.jsonl ...] [--from 2026-07] [--to 2027-03]
A trial of the round is a randomized phase 2 or 3 trial run by a company (sponsor class INDUSTRY), with its primary
completion as registered from July 2026 to March 2027, and no public result of its primary outcome:
- not stopped, not stale status (the record still says recruiting after its primary completion date);
- not "history", "test" or "stopped_no_result" in the results check, nor reported, stopped or left unclear in the
  results check of every trial (label rows passed with --labels: "yes", "stopped_without_result", "unclear").
Every trial gets the operations questions (late, stopped, results posted). Which other questions it gets:
- "main": p_met and, where its card says so, the number questions. Round 2 candidates with default "keep", and
  Round 1 trials ("round 1") in the same window.
- "equivalence": p_met, where met means equivalence shown (EQUIV: biosimilar, bioequivalence and lot-consistency
  trials with a stated equivalence objective).
- "operations only": trials with no efficacy goal to meet (the reader's "drop" trials: safety or pharmacokinetics
  only, descriptive, no comparison group, doses compared with no control; and three Round 1 questions in DROP_R1).
Trials marked "review" by the reader are listed apart (review.json) until they are looked at. Out as well:
NOT_A_TRIAL, sponsors that are individuals or non-profits (INDIVIDUAL, NOT_A_COMPANY), sponsors not expected to give
a verifiable result (SUSPECT_SPONSORS); a single-site trial with 1,000 or more patients stops the build until it is
looked at by hand (BIG_SINGLE_SITE_OK).
Writes <out dir>/questions.json (ordered by primary completion, then NCT number, each with its "questions"),
<out dir>/review.json and <out dir>/funnel.json (the NCT numbers left out at each step).
"""
import argparse
import json
import os
import re
from collections import Counter

DROP_R1 = {
    "NCT05298423": "primary outcomes are adverse events only; drug stopped for lack of efficacy elsewhere",
    "NCT05211895": "objectives descriptive after a protocol amendment",
    "NCT04224493": "treatment stopped and study unblinded after an urgent safety measure; analyses descriptive",
    "NCT06952478": "primary outcome is pharmacokinetic equivalence",
}
EQUIV = {   # equivalence trials with a stated equivalence objective: p_met = equivalence shown (26 Oct: back in)
    "NCT06687369": "MB12, proposed pembrolizumab biosimilar: PK bioequivalence and ORR equivalence",
    "NCT05654454": "bevacizumab (Mabscale) against Avastin: ORR equivalence",
    "NCT06754644": "QL2107 against Keytruda: ORR equivalence",
    "NCT07062978": "QL1206 against Prolia: lumbar spine BMD equivalence",
    "NCT06939595": "CT-P51 against Keytruda: ORR equivalence",
    "NCT06952478": "CT-P44 against Darzalex Faspro: PK equivalence",
    "NCT07074886": "two subcutaneous ocrelizumab formulations: bioequivalence",
    "NCT07199569": "MVA-BN made in quail cells against chicken cells: immunogenicity comparability",
    "NCT06847724": "CYB704 against Ocrevus: PK similarity",
    "NCT07162883": "QL2107 against Keytruda (adjuvant): PK equivalence",
    "NCT06430866": "ABP 234 against Keytruda: PK similarity",
    "NCT06740630": "varicella vaccine: lot-to-lot consistency and comparison with Varivax",
    "NCT05906992": "CT-P53 against Ocrevus: PK and efficacy equivalence",
}
NOT_A_TRIAL = {"NCT07481734": "the record calls itself a mock study"}
# Screens added after the outside reviews (26 Oct). "Company-run" means a company, not just the registry's
# sponsor class INDUSTRY: an individual sponsor-investigator or a non-profit can carry that class too.
INDIVIDUAL = re.compile(r"\bM\.?D\.?\b|\bPh\.?D\.?\b|FAPCR|\bIRB\b|Sponsor-Investigator", re.I)
NOT_A_COMPANY = {"Institut Pasteur": "non-profit research institute"}
SUSPECT_SPONSORS = {   # sponsors whose trials are not expected to give a verifiable public result
    "Hudson Biotech": "six single-site trials registered in the same two weeks on unapproved peptides (BPC-157, "
                      "Melanotan II, GHK-Cu, MOTS-c) and retatrutide, one a copy of Lilly's published SURMOUNT-1 "
                      "(same acronym, 2,539 patients at one site)",
}
# single-site trials with 1,000 or more patients are printed for a look by hand; these were looked at and kept
# (Chinese records often list only the lead site)
BIG_SINGLE_SITE_OK = {"NCT04842617": "Jiangsu HengRui, dalpiciclib phase 3", "NCT06778967": "Gan & Lee, phase 3",
                      "NCT06577519": "Jiangsu vcare, vicagrel phase 3"}
# kept, but disclosed: supplements, probiotics and devices, and trials run by contract research organisations, whose
# reporting habits differ from drug companies'
DISCLOSED = {n: "supplement, probiotic or device trial, or run by a contract research organisation" for n in (
    "NCT05232279", "NCT07241377", "NCT07315516", "NCT07457723", "NCT07669467", "NCT07669454", "NCT07669519",
    "NCT07256743", "NCT07193927", "NCT07029516")}
# stops announced in public before launch, not yet in the registry (web check of the operations-only trials past
# their primary completion date, 27 October; on launch day, of every trial): their p_stopped answer is already known
STOP_ANNOUNCED = {
    "NCT06208306": "2026-07-30: Sanofi and Regeneron ended itepekimab development in COPD, which ends AERIFY-4 early",
    "NCT05805501": "Roche's trial page tells participants to stop study treatment after the main results",
    "NCT05211895": "2026-08-05: Arcus and AstraZeneca will discontinue PACIFIC-8 (Arcus 8-K, Q2 2026 results)",
    "NCT06433219": "2026-04-16 onwards: early termination of DDRiver EOC 302 notified in the EU trials register (CTIS)",
}
CHECKED_BY_HAND = {"NCT07074886": "2026-10-26", "NCT05360446": "2026-10-26"}   # web search, nothing public
OPS_ONLY = {"NCT05909397": "only the safety lead-in enrolled (59 patients); its primary outcomes are safety, and the "
                           "phase 3 part's PFS will not be reported"}
ap = argparse.ArgumentParser()
ap.add_argument("merged")
ap.add_argument("status")
ap.add_argument("r1_manifest")
ap.add_argument("out")
ap.add_argument("--labels", nargs="*", default=[])
ap.add_argument("--from", dest="start", default="2026-07")
ap.add_argument("--to", dest="end", default="2027-03")
ap.add_argument("--today", default="2026-10-25", help="trials with primary completion on or before this date are "
                "past it and need a results check")
a = ap.parse_args()
merged = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.merged) if l.strip()}
status = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.status) if l.strip()}
r1 = set(json.load(open(a.r1_manifest))["trials"])
reported, checked = {}, {}
for p in a.labels:                     # results checks (label rows); "checked_on", when a row has it, is recorded
    for l in open(p):
        if l.strip():
            w = json.loads(l)
            if w.get("reported") in ("yes", "stopped_without_result", "unclear"):
                reported[w["nct_id"]] = w["reported"]
            elif w.get("reported") == "no":
                checked[w["nct_id"]] = w.get("checked_on") or checked.get(w["nct_id"])
checked.update({n: d for n, d in CHECKED_BY_HAND.items() if (checked.get(n) or "") < d})   # the later check counts


def results_check(n, s, pcd):
    if n in checked:
        return "web check: nothing public" + (f" ({checked[n]})" if checked[n] else "")
    return s or ("not finished" if (pcd or "") > a.today else "not checked")


why, keep, review = Counter(), [], []
steps = {}                                          # the NCT numbers left out at each step (funnel.json)


def out(step, n):
    why[step] += 1
    steps.setdefault(step, []).append(n)


for n, r in merged.items():
    if r["sponsor_class"] != "INDUSTRY":
        continue
    pc = (r["primary_completion_date"] or "")[:7]
    if not (a.start <= pc <= a.end):
        continue
    steps.setdefault("candidates", []).append(n)
    s = status.get(n, {}).get("status")
    sponsor = r["sponsor"] or ""
    if n in NOT_A_TRIAL:
        out("not a real trial", n)
        continue
    if INDIVIDUAL.search(sponsor) or sponsor in NOT_A_COMPANY:
        out("not a company (individual or non-profit sponsor)", n)
        continue
    if sponsor in SUSPECT_SPONSORS:
        out("sponsor not expected to report (see SUSPECT_SPONSORS)", n)
        continue
    if n in STOP_ANNOUNCED:
        out("stop announced before launch (see STOP_ANNOUNCED)", n)
        continue
    if r["group"] in ("stale status", "stopped"):
        out(r["group"], n)
        continue
    if s in ("history", "test", "stopped_no_result"):
        out("already reported or stopped", n)
        continue
    if n in reported:                   # the results check of every trial (second check confirmed; see the labels)
        out({"yes": "results check: primary result public before launch",
             "stopped_without_result": "results check: stop announced before launch",
             "unclear": "results check: unclear after the second check, left out to be safe"}[reported[n]], n)
        continue
    if (r.get("locations_count") or 0) <= 1 and (r.get("enrollment") or 0) >= 1000 and n not in BIG_SINGLE_SITE_OK:
        raise SystemExit(f"{n}: single site with {r.get('enrollment')} patients; look at it by hand, then add it to "
                         "BIG_SINGLE_SITE_OK or SUSPECT_SPONSORS / NOT_A_TRIAL")
    if r["default"] == "review" and n not in EQUIV:
        out("reader: review (listed apart)", n)
        q = "main"
    elif n in EQUIV:
        q = "equivalence"
    elif n in DROP_R1 or n in OPS_ONLY or r["default"] in ("drop", "out"):
        q = "operations only"
    elif r["default"] in ("keep", "round 1"):
        q = "main"
    else:
        out(f"reader: {r['default']}", n)
        continue
    row = {"nct_id": n, "questions": q, "primary_completion_date": r["primary_completion_date"], "phase": r["phase"],
           "area": r["area"], "sponsor": r["sponsor"], "comparison": (r.get("reader") or {}).get("comparison"),
           "why_no_p_met": (DROP_R1.get(n) or OPS_ONLY.get(n) or r.get("why")) if q == "operations only" else None,
           "from": "round 1" if (r["default"] == "round 1" or n in r1) else "round 2 candidates",
           "note": DISCLOSED.get(n),
           "results_check": results_check(n, s, r["primary_completion_date"])}
    (review if r["default"] == "review" and n not in EQUIV else keep).append(row)
keep.sort(key=lambda x: (x["primary_completion_date"], x["nct_id"]))
os.makedirs(a.out, exist_ok=True)
json.dump(keep, open(os.path.join(a.out, "questions.json"), "w"), indent=0)
json.dump(review, open(os.path.join(a.out, "review.json"), "w"), indent=0)
steps["in the round"] = [x["nct_id"] for x in keep]
json.dump({k: sorted(v) for k, v in steps.items()}, open(os.path.join(a.out, "funnel.json"), "w"), indent=0)
print(len(keep), "trials;", len(review), "to review; left out:", dict(why))
print("questions:", dict(Counter(x["questions"] for x in keep)))
print("by source:", dict(Counter(x["from"] for x in keep)))
print("by phase:", dict(Counter("phase 3" if "PHASE3" in x["phase"] else "phase 2" for x in keep)))
print("by area:", dict(Counter(x["area"] for x in keep).most_common()))
print("by completion:", dict(Counter("Jul-Oct 2026" if x["primary_completion_date"][:7] <= "2026-10" else
                                     ("Nov-Dec 2026" if x["primary_completion_date"][:7] <= "2026-12" else "Jan-Mar 2027")
                                     for x in keep)))
print("results check:", dict(Counter(x["results_check"] for x in keep)))
