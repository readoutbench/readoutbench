"""Evidence packs for Track C: what was published about a trial's drugs and disease before a cut date.

A pack has a drug sheet (what each drug is) and at most `n_drug + n_landscape` PubMed abstracts,
chosen by fixed queries and a fixed score, so no model writes or picks its content. The pack
never contains the trial's own result: articles must have been entered in PubMed by the cut
date (the day before the first public result, or the snapshot date for open trials), and
articles that name the trial's NCT number or acronym are left out.
"""
from __future__ import annotations

import re

DISEASES = [  # (regex on conditions and title, PubMed term, regex for an abstract about the same disease)
    (r"non[- ]?small[- ]?cell|nsclc", "non-small cell lung cancer", r"non[- ]?small[- ]?cell|nsclc"),
    (r"small[- ]?cell lung|\bsclc\b", "small cell lung cancer", r"small[- ]?cell lung|\bsclc\b"),
    (r"mesothelioma", "mesothelioma", r"mesothelioma"),
    (r"hepatocellular|\bhcc\b|liver cancer", "hepatocellular carcinoma", r"hepatocellular|\bhcc\b"),
    (r"biliary|cholangio|gallbladder", "biliary tract cancer", r"biliary|cholangio|gallbladder"),
    (r"pancrea", "pancreatic cancer", r"pancrea"),
    (r"nasopharyn", "nasopharyngeal carcinoma", r"nasopharyn"),
    (r"head and neck|hnscc|oral cavity|laryn|oropharyn|hypopharyn", "head and neck squamous cell carcinoma",
     r"head and neck|hnscc|oropharyn|laryn"),
    (r"esophag|oesophag", "esophageal cancer", r"esophag|oesophag"),
    (r"gastric|gastro-?esophageal junction|gastroesophageal|stomach", "gastric cancer",
     r"gastric|gastro-?(o)?esophageal junction|stomach"),
    (r"colorectal|\bcolon\b|rectal", "colorectal cancer", r"colorectal|\bcolon\b|rectal"),
    (r"breast", "breast cancer", r"breast"),
    (r"prostat", "prostate cancer", r"prostat"),
    (r"urothelial|bladder|upper tract", "urothelial carcinoma", r"urothelial|bladder"),
    (r"renal cell|kidney", "renal cell carcinoma", r"renal cell|kidney"),
    (r"ovar|fallopian|peritoneal", "ovarian cancer", r"ovar"),
    (r"cervical|cervix", "cervical cancer", r"cervical|cervix"),
    (r"endometri|uterine", "endometrial cancer", r"endometri|uterine"),
    (r"melanoma", "melanoma", r"melanoma"),
    (r"glioblastoma|glioma", "glioma", r"glioblastoma|glioma"),
    (r"multiple myeloma|\bmyeloma\b", "multiple myeloma", r"myeloma"),
    (r"acute myeloid|\baml\b", "acute myeloid leukemia", r"acute myeloid|\baml\b"),
    (r"acute lymphoblastic", "acute lymphoblastic leukemia", r"acute lymphoblastic"),
    (r"chronic lymphocytic|\bcll\b|small lymphocytic", "chronic lymphocytic leukemia",
     r"chronic lymphocytic|\bcll\b"),
    (r"chronic myeloid|\bcml\b", "chronic myeloid leukemia", r"chronic myeloid|\bcml\b"),
    (r"myelodysplastic|\bmds\b", "myelodysplastic syndromes", r"myelodysplastic|\bmds\b"),
    (r"myelofibrosis", "myelofibrosis", r"myelofibrosis"),
    (r"hodgkin", "Hodgkin lymphoma", r"hodgkin"),
    (r"diffuse large|dlbcl", "diffuse large B-cell lymphoma", r"diffuse large|dlbcl"),
    (r"follicular", "follicular lymphoma", r"follicular"),
    (r"mantle", "mantle cell lymphoma", r"mantle"),
    (r"lymphoma", "lymphoma", r"lymphoma"),
    (r"neuroendocrine|carcinoid", "neuroendocrine tumors", r"neuroendocrine"),
    (r"gastrointestinal stromal|\bgist\b", "gastrointestinal stromal tumor", r"gastrointestinal stromal|\bgist\b"),
    (r"thyroid", "thyroid cancer", r"thyroid"),
    (r"sarcoma", "sarcoma", r"sarcoma"),
    (r"lung", "lung cancer", r"lung"),
]

CLINICAL_TYPES = re.compile(r"clinical trial|randomized controlled trial|multicenter study|comparative study", re.I)
REVIEW_TYPES = re.compile(r"review|meta-analysis|editorial|comment|letter|news|guideline|practice guideline", re.I)
CASE_TYPES = re.compile(r"case reports", re.I)
RESULT_WORDS = re.compile(r"\b(met (its|the) primary|significantly (improved|prolonged|longer|reduced)|"
                          r"hazard ratio|\bHR\b|did not (significantly )?(improve|meet|prolong)|primary end ?point)\b",
                          re.I)


def disease(rec: dict) -> tuple[str, str]:
    """(PubMed term, abstract regex) for the trial's disease, from its conditions, then its title."""
    texts = [" ".join(rec.get("conditions") or []), rec.get("title") or "", rec.get("brief_title") or ""]
    for text in texts:
        for rx, term, arx in DISEASES:
            if re.search(rx, text, re.I):
                return term, arx
    first = re.sub(r"\(.*?\)", "", (rec.get("conditions") or ["cancer"])[0]).strip()
    if "," in first:                                # MeSH order: "Carcinoma, Non-Small-Cell Lung"
        a, b = first.split(",", 1)
        first = f"{b.strip()} {a.strip()}"
    return first or "cancer", re.escape(first.split()[0]) if first else "cancer"


def pub_date_latest(a: dict) -> str:
    """The latest date the publication date could stand for (a month-only date is its last day)."""
    d = a.get("publication_date") or {}
    y = str(d.get("year") or "9999")
    mo, day = str(d.get("month") or ""), str(d.get("day") or "")
    if not mo:
        return f"{y}-12-31"
    first = pub_date(a)
    if day.isdigit():
        return first
    import calendar
    yy, mm = int(first[:4]), int(first[5:7])
    return f"{first[:7]}-{calendar.monthrange(yy if yy > 0 else 2000, mm)[1]:02d}"


def pub_date(a: dict) -> str:
    d = a.get("publication_date") or {}
    y = str(d.get("year") or "0000")
    mo = str(d.get("month") or "01")
    months = {m: f"{i:02d}" for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
    mo = months.get(mo[:3].lower(), mo.zfill(2) if mo.isdigit() else "01")
    day = str(d.get("day") or "01")
    day = day.zfill(2) if day.isdigit() else "01"
    return f"{y}-{mo}-{day}"


def trim_abstract(text: str, max_words: int = 300) -> str:
    words = re.sub(r"\s+", " ", text or "").strip().split(" ")
    if len(words) <= max_words:
        return " ".join(words)
    head = max_words // 4
    return " ".join(words[:head]) + " [...] " + " ".join(words[-(max_words - head):])


def mentions_trial(a: dict, nct_id: str, trial_names: list[str]) -> bool:
    text = " ".join([a.get("title") or "", a.get("abstract") or ""])
    if nct_id.lower() in text.lower():
        return True
    for t in trial_names or []:
        t = (t or "").strip()
        if len(t) >= 4 and re.search(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", text, re.I):
            return True
    return False


def score(a: dict, drug_rx: re.Pattern | None, disease_rx: str, rank: int) -> tuple:
    title = a.get("title") or ""
    abstract = a.get("abstract") or ""
    types = " ".join(a.get("article_types") or [])
    s = 0
    if drug_rx is not None:
        if drug_rx.search(title):
            s += 3
        elif drug_rx.search(abstract):
            s += 1
    if re.search(disease_rx, title + " " + abstract, re.I):
        s += 2
    if CLINICAL_TYPES.search(types):
        s += 2
    if re.search(r"\bphase\b", abstract, re.I):
        s += 1
    if re.search(r"\brandomi[sz]", abstract, re.I):
        s += 1
    if REVIEW_TYPES.search(types):
        s -= 2
    if CASE_TYPES.search(types):
        s -= 1
    return (-s, rank)


def select(cands: list[dict], n: int, drug_rx, disease_rx: str, exclude: set, max_reviews: int = 1) -> list[dict]:
    """cands: articles with 'pmid', 'rank' (PubMed relevance order); returns at most n, best first."""
    pool = [a for a in cands if a.get("pmid") not in exclude and (a.get("abstract") or "").strip()]
    pool.sort(key=lambda a: score(a, drug_rx, disease_rx, a.get("rank", 99)))
    out, reviews = [], 0
    for a in pool:
        if REVIEW_TYPES.search(" ".join(a.get("article_types") or [])):
            if reviews >= max_reviews:
                continue
            reviews += 1
        out.append(a)
        if len(out) >= n:
            break
    return out


# Other trials' names ("KEYNOTE-671", "DESTINY-Lung01", "IMpower010", "CheckMate 816", "(CLEOPATRA)",
# "the MATTERHORN trial") point to the drug behind them, so the names-hidden packs leave them out:
# (1) a word of five letters or more, with at least two capitals, that runs into a number; (2) a
# word in capitals in parentheses, unless it abbreviates the words before it ("non-small cell lung
# cancer (NSCLC)"); (3) a word in capitals just before "trial", "study" and the like; (4) other
# registries' numbers; (5) any other word of five or more capitals ("PEARLS", "CROWN"). Gene
# names, drug names and common abbreviations are kept.
TRIAL_NAME = re.compile(r"(?<![A-Za-z0-9-])([A-Za-z]{5,}(?:-[A-Za-z]+)?)([- ]?)(\d{1,4}[A-Za-z]{0,3})(?![A-Za-z0-9])")
CAPS_IN_PARENS = re.compile(r"\s*\(([A-Z][A-Za-z]*[A-Z][A-Za-z0-9-]*)\)")
CAPS_BEFORE_TRIAL = re.compile(r"(?<![A-Za-z0-9-])([A-Z][A-Za-z]*[A-Z][A-Za-z0-9-]*)(?=\s+(?:phase\s+(?:[123]|I+|III)\s+)?"
                               r"(?:trial|study|studies|program|programme|regimen|cohort|population|data|results)\b)",
                               re.I)
REGISTRY_NO = re.compile(r"\b(?:ISRCTN\s?\d{6,}|ACTRN\s?\d{10,}|ChiCTR[-\w]*\d{6,}|jRCT\w*\d{6,}|UMIN\d{6,}|"
                         r"EudraCT[:\s]*(?:number[:\s]*)?\d{4}-\d{6}-\d{2}|\d{4}-\d{6}-\d{2})\b", re.I)
NOT_TRIAL_NAMES = {"RECIST", "SMARCA", "CEACAM", "SLAMF", "TACSTD", "NECTIN", "COVID", "TNFRSF", "LILRB", "SIGLEC",
                   "MAGEA", "CDKN", "ARID", "GPRC", "FOLFOX", "FOLFIRI", "FOLFIRINOX", "FOLFOXIRI", "XELOX", "CAPOX",
                   "CAPEOX", "GEMOX", "CAPTEM", "NSCLC", "SCLC", "DLBCL", "HNSCC", "SCCHN", "CTCAE", "EORTC", "HIPEC",
                   "NMIBC", "MIBC", "PCNSL", "MCRPC", "MHSPC", "HGBCL", "IWCLL", "HRQOL", "WOCBP", "TURBT", "NCCN",
                   "ESMO", "ASCO", "PHASE", "STUDY", "TRIAL", "TRIALS", "RANDOMIZED", "RANDOMISED", "CLINICAL",
                   "CONTROLLED", "MULTICENTER", "MULTICENTRE", "BLIND", "DOUBLE", "OPEN", "LABEL", "PIVOTAL", "GLOBAL",
                   "PILOT", "CANCER", "PATIENTS", "RESULTS", "METHODS", "BACKGROUND", "CONCLUSIONS", "CONCLUSION",
                   "FINDINGS", "INTERPRETATION", "FUNDING", "PURPOSE", "OBJECTIVE", "DESIGN", "SETTING",
                   "OBJECTIVES", "INTRODUCTION", "SUMMARY", "ABSTRACT", "DISCUSSION", "IMPORTANCE", "EXPOSURES",
                   "PARTICIPANTS", "INTERVENTIONS", "MEASURES", "OUTCOMES", "RELEVANCE", "REGISTRATION", "SIGNIFICANCE",
                   "CRITERIA", "CLINICALTRIALS", "INFORMATION", "VERSUS", "PLACEBO", "THERAPY", "PATIENT", "GROUP",
                   "CHEMOTHERAPY", "IMMUNOTHERAPY", "MONOTHERAPY", "COMBINATION", "METASTATIC", "ADVANCED", "LOCALLY",
                   "RELAPSED", "REFRACTORY", "UNRESECTABLE", "TREATED", "PREVIOUSLY", "RESISTANT", "CASTRATION",
                   "PROSTATE", "MULTIPLE", "MYELOMA", "MELANOMA", "EFFICACY", "SAFETY", "INCLUSION", "EXCLUSION",
                   "NSCLS", "SCCHN", "PCNSL", "MASLD", "PROTAC", "ADCOMS", "DPOAE", "HDACI", "IASLC", "AASLD",
                   "ANOVA", "ANCOVA", "ELISA", "ELISPOT", "CRISPR", "MEDLINE", "EMBASE", "PRISMA", "NIHSS", "MADRS",
                   "SCORAD", "GMFCS", "ETDRS", "FACIT", "PROMIS", "MENQOL", "NONMEM", "STEMI", "IBCFS", "DIPSS",
                   "FLIPI", "RANKL", "TIGIT", "VEGFA", "VEGFR", "PDGFR", "PDGFRA", "PDGFRB", "KRASM", "GNRHR",
                   "NSABP", "CALGB", "GERCOR", "ARCAGY", "NCORP", "ACCRU", "SWOG", "ECOG", "VENTANA", "QIAGEN",
                   "MCRPC", "MHSPC", "NMCRPC", "SPECT", "DOTATATE", "HGCSG", "SOXRC", "MFSAF", "PPROC", "RCCEP",
                   "LTBFL", "HNSTD", "VGPRR", "POCBP", "NTMPD", "CD34HSPC", "LARVOL", "EJNMMI", "ACGME", "ASBMR",
                   "DEGRO", "IWCLL", "RAPNO", "TABLE", "GRADE", "ADULT", "DIRECTED", "MUTATED", "TRIPLE"}
DRUGLIKE = re.compile(r"(?:mab|nib|lib|parib|ciclib|stat|platin|taxel|rubicin|vedotin|deruxtecan|govitecan|tecan|"
                      r"mustine|sertib|lisib|degib|zomib|lutamide|rasib|sone|olone|mide|abine|mycin|trexate|xifene|"
                      r"zole|relin|cept|kin|ase|tide|cin|rone|terone|amine|ine)$", re.I)
ALL_CAPS = re.compile(r"(?<![A-Za-z0-9-])([A-Z]{5,})(?![A-Za-z0-9-])")


def _abbreviates(abbr: str, before: str) -> bool:
    letters = [ch for ch in abbr.lower() if ch.isalpha()]
    words = re.findall(r"[A-Za-z]+", before)[-12:]
    initials = "".join(w[0].lower() for w in words)
    k = 0
    for ch in initials:
        if k < len(letters) and ch == letters[k]:
            k += 1
    return k == len(letters)


def strip_trial_names(text: str, keep: frozenset = frozenset()) -> str:
    """keep: more words to keep (gene symbols, drug names)."""
    def digits(m):
        word = m.group(1)
        if sum(ch.isupper() for ch in word) < 2 or word.upper() in NOT_TRIAL_NAMES:
            return m.group(0)
        return ""

    def parens(m):
        w = m.group(1)
        if (sum(ch.isalpha() for ch in w) < 4 or w.upper().rstrip("S") in NOT_TRIAL_NAMES
                or _abbreviates(w, t[max(0, m.start() - 160):m.start()])):
            return m.group(0)
        return ""

    def before_trial(m):
        w = m.group(1)
        if sum(ch.isalpha() for ch in w) < 5 or w.upper() in NOT_TRIAL_NAMES or not w[1:2].isupper() and \
                sum(ch.isupper() for ch in w) < 2:
            return m.group(0)
        return ""

    t = REGISTRY_NO.sub("", text or "")
    t = TRIAL_NAME.sub(digits, t)
    t = CAPS_IN_PARENS.sub(parens, t)
    t = CAPS_BEFORE_TRIAL.sub(before_trial, t)

    def caps(m):                                        # (5) "PEARLS", "MATTERHORN", "CROWN" in capitals
        w = m.group(1)
        if w in NOT_TRIAL_NAMES or w.rstrip("S") in NOT_TRIAL_NAMES or w in keep or DRUGLIKE.search(w):
            return m.group(0)
        return ""

    t = ALL_CAPS.sub(caps, t)
    t = re.sub(r"\(\s*[,;/]?\s*\)", "", t)
    return re.sub(r"(?:,\s*){2,}", ", ", t)


def render_pack(cut: str, sheet: list[tuple[str, str, str]], drug_articles: list[dict], land_articles: list[dict],
                hider=None, start_view: bool = False, keep: frozenset = frozenset()) -> str:
    """sheet: (name, role, description) per drug. hider: a hide.Hider for the names-hidden version,
    which also leaves out other trials' names (keep: words that are never taken for one)."""
    h = (lambda t: hider(strip_trial_names(t, keep))) if hider else (lambda t: t)
    when = "the trial's start date" if start_view else "the forecast date"
    # No dates are shown: for a trial that has reported, the cut date (the day before its first
    # result) and the newest abstract's date would hint at when, and so how, it reported.
    L = [f"## Evidence pack (PubMed abstracts from before {when}; this trial's own result is never included)",
         "", "### Drug sheet"]
    for name, role, desc in sheet:
        L.append(f"- {h(name)} ({role}): {h(desc)}")
    for head, arts in (("### Earlier studies of the experimental drugs", drug_articles),
                       ("### Randomised phase 3 trials in the same disease", land_articles)):
        L += ["", head]
        if not arts:
            L.append("None found.")
        for k, a in enumerate(arts, 1):
            jt = (a.get("journal") or {}).get("iso_abbreviation") or (a.get("journal") or {}).get("title") or ""
            L.append(f"{k}. {h(a.get('title') or '').strip()} {jt}.")
            L.append(f"   {h(trim_abstract(a.get('abstract') or ''))}")
    return "\n".join(L).rstrip() + "\n"
