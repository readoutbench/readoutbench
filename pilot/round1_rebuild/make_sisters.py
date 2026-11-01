"""Round 1 (rebuilt): sister-trial groups for the clustered bootstrap.

usage: python3 -I make_sisters.py <cards.jsonl> <records.jsonl ...> --out <sisters.json>
Trials testing the same experimental drug tend to succeed or fail together, so the bootstrap resamples them as one
group. A trial's drug is its first registered intervention that is not a placebo, standard care or the card's
control, preferring one named in the card's experimental arm; names are lower-cased, with doses, forms and
punctuation removed. Trials with the same drug form one group, whoever the sponsor (licensees and partners
included). ALIASES maps a drug's code to its name where both occur. Only trials with a p_met question are grouped.
Writes {"groups": {group: [nct ids]}, "trial_group": {nct_id: group}} with every p_met trial in it (a trial with no
sister is its own group).
"""
import argparse
import json
import re
from collections import defaultdict

CONTROLISH = re.compile(r"placebo|vehicle|sham|standard (of )?care|best supportive|usual care|control|saline|"
                        r"observation|no treatment|investigator'?s choice|physician'?s choice", re.I)
DOSE = re.compile(r"\b\d+(\.\d+)?\s*(mg/kg|mg|µg|ug|mcg|g|ml|iu|units?|%|mg/m2)\b", re.I)
FORM = re.compile(r"\b(injection|injectable|tablets?|capsules?|oral|subcutaneous|intravenous|iv|sc|solution|"
                  r"suspension|cream|gel|ointment|eye drops?|ophthalmic|low|high|medium|dose [a-z0-9]+|dose|arm [a-z0-9]+|"
                  r"regimen [a-z0-9]+|q\d+w|once (daily|weekly)|twice daily|bid|qd|extended[- ]release|for|plus|sodium|"
                  r"hydrochloride|hcl|mesylate|higher|lower|under inhalational anesthesia|fixed|combination|fdc|the|"
                  r"monotherapy|topical|ocular|will be administered|administered|orally|daily)\b", re.I)
ALIASES = {"ly3437943": "retatrutide", "skb264": "sacituzumabtirumotecan", "mk2870": "sacituzumabtirumotecan",
           "ly3298176": "tirzepatide", "bms986165": "deucravacitinib", "abt494": "upadacitinib",
           "nuvastatic300": "nuvastatic", "sacituzumabgovitecanhziy": "sacituzumabgovitecan",
           "encorafenibandbinimetinib": "encorafenib", "cemiplimabfianlimab": "fianlimab",
           "fixedcemiplimab": "fianlimab", "mk1022": "patritumabderuxtecan", "ds1062a": "datopotamabderuxtecan",
           "ly3437943": "retatrutide", "datodxd": "datopotamabderuxtecan", "dato": "datopotamabderuxtecan"}


SPONSOR_ALIASES = {"Karuna Therapeutics": "Bristol-Myers Squibb", "Tesaro, Inc.": "GlaxoSmithKline",
                   "Genentech, Inc.": "Hoffmann-La Roche", "Merck Sharp & Dohme LLC": "Merck Sharp & Dohme"}
# matched as substrings of the lower-cased sponsor name, first match wins (subsidiaries before parents' own names)
PARENTS = [("karuna", "Bristol-Myers Squibb"), ("celgene", "Bristol-Myers Squibb"),
           ("bristol myers squibb", "Bristol-Myers Squibb"), ("bristol-myers squibb", "Bristol-Myers Squibb"),
           ("verona pharma", "Merck Sharp & Dohme"), ("merck sharp", "Merck Sharp & Dohme"),
           ("shengdi", "Jiangsu HengRui"), ("suncadia", "Jiangsu HengRui"), ("tesaro", "GlaxoSmithKline"),
           ("viiv", "GlaxoSmithKline"), ("genentech", "Hoffmann-La Roche"), ("sanofi", "Sanofi"),
           ("merz ", "Merz"), ("gasherbrum", "Structure Therapeutics"), ("structure therapeutics", "Structure Therapeutics"),
           ("henlius", "Fosun Pharma"), ("fosun", "Fosun Pharma"), ("sunshine guojian", "3SBio"), ("3sbio", "3SBio"),
           ("chia tai tianqing", "Chia Tai Tianqing"), ("innovent", "Innovent Biologics"), ("hengrui", "Jiangsu HengRui"),
           ("hansoh", "Hansoh"), ("akeso", "Akeso"), ("kelun", "Sichuan Kelun"), ("cspc", "CSPC"), ("qilu", "Qilu"),
           ("haisco", "Haisco"), ("bayer", "Bayer"), ("novartis", "Novartis"), ("pfizer", "Pfizer"),
           ("astrazeneca", "AstraZeneca"), ("hoffmann-la roche", "Hoffmann-La Roche"), ("eli lilly", "Eli Lilly"),
           ("janssen", "Johnson & Johnson"), ("boehringer", "Boehringer Ingelheim")]


def sponsor_key(name: str) -> str:
    """The sponsor's parent company where its subsidiaries register trials under their own names."""
    n = SPONSOR_ALIASES.get(name or "", name or "")
    low = n.lower()
    return next((parent for key, parent in PARENTS if key in low), n)


def norm(name: str) -> str:
    s = re.sub(r"[®™]", "", name or "")
    s = re.sub(r"\(.*?\)", " ", s)
    s = DOSE.sub(" ", s)
    s = FORM.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", "", s.lower())


SPLIT = re.compile(r"\s+(?:in combination with|combined with|together with|with|and|plus)\s+|\s*\+\s*|/", re.I)


def drug(card: dict, rec: dict) -> str | None:
    """The trial's experimental drug: the registered interventions (other than placebo, standard care and the like)
    split into their drugs, preferring one named in the card's experimental arm and not in its control arm, then one
    named in the experimental arm, then the first."""
    squash = lambda t: re.sub(r"[^a-z0-9]+", "", (t or "").lower())  # noqa: E731
    ctrl, exp = squash(card.get("control_arm")), squash(card.get("experimental_arm"))
    parts = []                                     # registered names as written; grouped under their alias
    for name in (i for i in (rec.get("interventions") or []) if isinstance(i, str) and not CONTROLISH.search(i)):
        for part in SPLIT.split(re.sub(r"\(.*?\)", " ", name)):
            d = norm(part)
            if len(d) >= 3 and d not in parts:
                parts.append(d)
    for keep in (lambda d: d in exp and d not in ctrl, lambda d: d in exp, lambda d: True):
        hit = [d for d in parts if keep(d)]
        if hit:
            return ALIASES.get(hit[0], hit[0])
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cards")
    ap.add_argument("records", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cards = [json.loads(line) for line in open(a.cards) if line.strip()]
    recs = {}
    for p in a.records:
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                recs[r["nct_id"]] = r
    groups = defaultdict(list)
    for c in cards:
        if c["design"] == "none":
            continue
        d = drug(c, recs[c["nct_id"]])
        groups[d or c["nct_id"]].append(c["nct_id"])
    trial_group = {n: g for g, ns in groups.items() for n in ns}
    pm = [c["nct_id"] for c in cards if c["design"] != "none"]
    json.dump({"groups": {g: sorted(ns) for g, ns in sorted(groups.items())}, "trial_group": trial_group,
               "trial_sponsor": {n: sponsor_key(recs[n].get("sponsor") or "") for n in pm},
               "trial_china_only": {n: (recs[n].get("countries") or []) == ["China"] for n in pm}},
              open(a.out, "w"), indent=0)
    print(sum(1 for g in groups if g.startswith("NCT")), "trials with no drug name matched (their own group)")
    multi = {g: ns for g, ns in groups.items() if len(ns) > 1}
    print(len(trial_group), "p_met trials in", len(groups), "groups;", len(multi), "groups of 2 or more holding",
          sum(map(len, multi.values())), "trials")
    for g, ns in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:40]:
        print(f"  {len(ns)} {g}: " + ", ".join(f"{n} ({(recs[n].get('sponsor') or '')[:18]})" for n in ns[:6]))
