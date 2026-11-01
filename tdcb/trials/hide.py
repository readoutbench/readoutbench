"""Hide the names that identify a trial, keeping what the drugs are.

`hide_record` returns a copy of a registry record in which the trial's acronym, short title
and collaborators are gone, the sponsor is replaced by its type, and the experimental drugs'
names, codes and brand names are replaced by "Drug A", "Drug B" and so on. `render_hidden`
renders it like `packets.render`, under a case code instead of the NCT number, with a
"Hidden drugs" section that says what each hidden drug is (from the drug sheet). The same
`Hider` is applied to the trial's evidence pack, so the record and the pack stay consistent.
"""
from __future__ import annotations

import copy
import hashlib
import re

from .baselines import BIG_PHARMA
from .packets import render

ACADEMIC = re.compile(r"universit|hospital|institut|\bcent(?:er|re)\b|college|\bgroup\b|foundation|society|"
                      r"consortium|alliance|cooperative|co-operative|national|ministry|association|council|"
                      r"cancer research|\bnci\b|eortc|academ|klinik|clinic|school|unicancer|gustave|fondazione|"
                      r"instituto|charit|\bnrg\b|\bswog\b|\becog\b|\bjcog\b|\bgog\b|\baio\b|\bgbg\b|arbeitsgemeinschaft",
                      re.I)
SPONSOR_STOP = {"pharmaceutical", "pharmaceuticals", "pharma", "pharmaceutica", "medicine", "medicines", "medical",
                "biologics", "biological", "biotech", "biotechnology", "biopharma", "biopharmaceutical",
                "biopharmaceuticals", "bioscience", "biosciences", "therapeutics", "oncology", "research",
                "company", "corporation", "group", "holdings", "limited", "international", "global", "china",
                "inc", "ltd", "llc", "gmbh", "corp", "dohme", "sharp", "university", "hospital", "cancer", "center",
                "centre", "institute", "national", "science", "sciences", "technology", "health", "healthcare",
                "development", "clinical", "trials", "foundation", "network", "jiangsu", "zhejiang", "shanghai",
                "beijing", "sichuan", "shandong", "guangdong", "suzhou", "hangzhou", "nanjing", "chengdu",
                "co", "the", "and", "for", "with", "of"}
SPONSOR_ALIASES = [  # short names that a sponsor's full name does not contain
    (re.compile(r"merck sharp|\bmsd\b", re.I), ["MSD", "Merck Sharp & Dohme", "Merck"]),
    (re.compile(r"bristol", re.I), ["BMS", "Bristol-Myers Squibb", "Bristol Myers Squibb", "Celgene"]),
    (re.compile(r"hoffmann|roche|genentech", re.I), ["Roche", "Genentech", "Hoffmann-La Roche", "Chugai"]),
    (re.compile(r"glaxo|\bgsk\b", re.I), ["GSK", "GlaxoSmithKline", "Tesaro"]),
    (re.compile(r"janssen|johnson", re.I), ["Janssen", "Johnson & Johnson", "J&J"]),
    (re.compile(r"daiichi", re.I), ["Daiichi Sankyo", "Daiichi"]),
    (re.compile(r"astrazeneca", re.I), ["AstraZeneca", "MedImmune", "Acerta"]),
    (re.compile(r"beigene|beone", re.I), ["BeiGene", "BeOne"]),
    (re.compile(r"hengrui", re.I), ["Hengrui", "HengRui"]),
    (re.compile(r"eli lilly|\blilly\b|loxo", re.I), ["Lilly", "Eli Lilly", "Loxo"]),
]
COMPANY = re.compile(r"\b(?:inc|ltd|llc|gmbh|co|corp|corporation|s\.?a|ag|plc|limited|company|holdings|k\.?k|"
                     r"pharma\w*|therapeutics|biotech\w*|bio(?:logics|sciences?|pharma\w*|tech)|sciences?|"
                     r"medicines?)\b", re.I)
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
# protocol numbers and other trials' registry numbers: "MK-3475-975", "OT-01-P201", "GCT1184-02", "NCT01234567"
PROTOCOL = re.compile(r"(?<![A-Za-z0-9-])(?:[A-Z0-9]+(?:-[A-Z0-9]+){2,}|[A-Z]{2,5}\d{3,6}-\d{2,3}|NCT\d{8})(?![A-Za-z0-9-])")


def sponsor_type(sponsor: str | None) -> str:
    s = sponsor or ""
    if BIG_PHARMA.search(s):
        return "a large pharmaceutical company"
    if ACADEMIC.search(s):
        return "an academic institution or cooperative group"
    return "a company that is not one of the largest pharmaceutical companies"


def name_variants(name: str) -> set[str]:
    """Spellings of a drug name or code: 'IBI310', 'IBI-310', 'IBI 310'."""
    n = re.sub(r"\s+", " ", (name or "").replace("®", "").replace("™", "")).strip()
    if len(n) < 3:
        return set()
    out = {n}
    m = re.match(r"^([A-Za-z]{1,6})[- ]?(\d[\w\-.]*)$", n)
    if m:
        a, b = m.groups()
        out |= {f"{a}{b}", f"{a}-{b}", f"{a} {b}"}
    if "-" in n:
        out.add(n.replace("-", ""))
        out.add(n.replace("-", " "))
    return {x for x in out if len(x) >= 3}


def _pattern(words) -> re.Pattern | None:
    ws = sorted({w for w in words if w}, key=len, reverse=True)
    if not ws:
        return None
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(w) for w in ws) + r")(?![A-Za-z0-9])", re.I)


def sponsor_tokens(sponsor) -> list[str]:
    """Names to hide for a sponsor or collaborator: the full name, acronyms (in parentheses or in
    capitals), short names, and, for a company, its distinctive words. The words of an academic
    or cooperative group's name ("European", "Ovarian", "Trial") are not hidden one by one."""
    if isinstance(sponsor, (list, tuple)):
        return [t for x in sponsor for t in sponsor_tokens(x)]
    s = str(sponsor or "")
    if s in ("None", "null") or not s.strip():
        return []
    toks = re.findall(r"\(([A-Za-z][A-Za-z0-9&\-]{1,15})\)", s)              # "(ENGOT)"
    toks += [t for t in re.findall(r"\b[A-Z][A-Z0-9&\-]{2,}\b", s) if t.lower() not in SPONSOR_STOP]
    if BIG_PHARMA.search(s) or (COMPANY.search(s) and not ACADEMIC.search(s)):
        toks += [t for t in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", s) if t.lower() not in SPONSOR_STOP]
    for rx, names in SPONSOR_ALIASES:
        if rx.search(s):
            toks += names
    full = re.sub(r"[,.]?\s*(inc|ltd|llc|gmbh|co|corp|s\.?a\.?|ag|plc)\.?$", "", s.strip(), flags=re.I)
    toks += [full, re.sub(r"\s*\([^()]*\)", "", full).strip()]
    return [t for t in toks if len(t) >= 3]


class Hider:
    """Replaces one trial's identifying names in any text.

    drugs: list of {"name", "aliases", "synonyms"} for the drugs to hide, in the order they get
    their letters. trial_names: acronyms and protocol numbers. sponsors: sponsor and collaborators.
    """

    def __init__(self, nct_id: str, drugs: list[dict], trial_names: list[str], sponsors: list[str]):
        self.nct_id = nct_id
        self.labels = {}
        self._drug_rx = []
        for k, d in enumerate(drugs):
            label = f"Drug {LETTERS[k]}" if k < len(LETTERS) else f"Drug {k + 1}"
            words = set()
            for w in [d.get("name")] + list(d.get("aliases") or []) + list(d.get("synonyms") or []):
                words |= name_variants(w or "")
            rx = _pattern(words)
            if rx:
                self._drug_rx.append((rx, label))
                self.labels[d.get("name")] = label
        trial_words = set()
        for t in trial_names or []:
            trial_words |= name_variants(t)
        trial_words.add(nct_id)
        self._trial_rx = _pattern(trial_words)
        sw = []
        for s in sponsors or []:
            sw += sponsor_tokens(s)
        self._sponsor_rx = _pattern(sw)

    def __call__(self, text):
        if not text:
            return text
        t = str(text)
        for rx, label in self._drug_rx:
            t = rx.sub(label, t)
        if self._trial_rx:
            t = self._trial_rx.sub("", t)
        if self._sponsor_rx:
            t = self._sponsor_rx.sub("the sponsor", t)
        t = PROTOCOL.sub(lambda m: m.group(0) if sum(ch.isdigit() for ch in m.group(0)) < 2 else "", t)
        t = re.sub(r"NCT\d{8}", "", t)                       # registry numbers, even run into a word
        t = re.sub(r"\(\s*[/,;:\- ]*\s*\)", "", t)          # "( )" or "(/)" left by a removed name
        t = re.sub(r"\[\s*\]", "", t)
        t = re.sub(r"^\s*[:\-–]\s*", "", t)
        t = re.sub(r"\s+([,.;:)])", r"\1", t)
        t = re.sub(r"[ \t]{2,}", " ", t)
        return t.strip()


def case_code(salt: str, setting: str, nct_id: str) -> str:
    return "X-" + hashlib.sha256(f"{salt}|{setting}|{nct_id}".encode()).hexdigest()[:8].upper()


def hide_record(rec: dict, hider: Hider, start_view: bool = False) -> dict:
    r = copy.deepcopy(rec)
    r["title"] = hider(rec.get("title"))
    r["brief_title"] = None
    r["acronym"] = None
    r["collaborators"] = None
    r["sponsor"] = sponsor_type(rec.get("sponsor"))
    r["interventions"] = [hider(x) for x in rec.get("interventions") or []]
    r["conditions"] = [hider(x) for x in rec.get("conditions") or []]
    for k in ("brief_summary", "detailed_description", "eligibility_criteria"):
        r[k] = hider(rec.get(k)) if rec.get(k) and str(rec.get(k)) != "None" else rec.get(k)
    for k in ("primary_outcomes", "secondary_outcomes"):
        r[k] = [{kk: (hider(vv) if isinstance(vv, str) else vv) for kk, vv in (o or {}).items()}
                for o in rec.get(k) or []]
    if start_view:
        r["enrollment"] = None
        r["n_locations"] = None
        r["countries"] = []
        r["primary_completion_date"] = None
        r["completion_date"] = None
    return r


def render_hidden(rec: dict, hider: Hider, code: str, drug_lines: dict[str, str], snapshot: str,
                  start_view: bool = False) -> str:
    """drug_lines: label ("Drug A") -> what the drug is."""
    text = render(hide_record(rec, hider, start_view), snapshot)
    text = text.replace(f"# Trial {rec['nct_id']}", f"# Trial {code}", 1)
    if start_view:
        text = re.sub(r"comes from its ClinicalTrials\.gov record \(snapshot [0-9-]+\); no result is included\.",
                      "comes from its ClinicalTrials.gov record, with names hidden and without the enrolment, "
                      "sites and dates that may have changed after the trial started; no result is included.", text)
        text = re.sub(r"- Start: ([0-9-]+|not stated); primary completion.*", r"- Start: \1", text)
    else:
        text = re.sub(r"\(snapshot ([0-9-]+)\); no result is included\.",
                      r"(snapshot \1), with names hidden; no result is included.", text)
    text = re.sub(r"- Sponsor: (.*)", r"- Sponsor: \1 (name hidden)", text, count=1)
    if drug_lines:
        block = ["## Hidden drugs"] + [f"- {lab}: {line}" for lab, line in drug_lines.items()] + [""]
        text = text.replace("## Primary outcome(s)", "\n".join(block) + "\n## Primary outcome(s)", 1)
    return text
