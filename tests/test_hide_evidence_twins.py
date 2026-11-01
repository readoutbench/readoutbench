import re

import numpy as np

from tdcb.trials import evidence, hide, twins
from tdcb.trials.score import decision

REC = {
    "nct_id": "NCT04720716",
    "title": "A Phase III Study of IBI310 Combined With Sintilimab Versus Sorafenib in First-line HCC (ORIENT-99)",
    "brief_title": "IBI310 plus sintilimab versus sorafenib",
    "acronym": "ORIENT-99",
    "status": "ACTIVE_NOT_RECRUITING",
    "phase": ["PHASE3"],
    "conditions": ["Hepatocellular Carcinoma"],
    "interventions": ["IBI310", "Sintilimab", "Sorafenib"],
    "sponsor": "Innovent Biologics (Suzhou) Co. Ltd.",
    "collaborators": "Some Partner Inc.",
    "enrollment": 344,
    "start_date": "2021-02-07",
    "primary_completion_date": "2025-12-31",
    "completion_date": "2025-12-31",
    "brief_summary": "IBI-310 plus sintilimab (IBI308) against sorafenib; Innovent will assess PFS.",
    "detailed_description": None,
    "eligibility_criteria": "No prior IBI 310.",
    "primary_outcomes": [{"measure": "Progression-free survival (PFS)", "time_frame": "24 months",
                          "description": "PFS by RECIST 1.1"}],
    "secondary_outcomes": [{"measure": "Overall survival (OS)"}, {"measure": "ORR"}],
    "n_locations": 10, "countries": ["China"],
}
DRUGS = [{"name": "IBI310", "aliases": []}, {"name": "sintilimab", "aliases": ["IBI308"], "synonyms": ["Tyvyt"]}]


def make_hider():
    return hide.Hider(REC["nct_id"], DRUGS, ["ORIENT-99"], [REC["sponsor"], REC["collaborators"]])


def test_name_variants():
    assert {"IBI310", "IBI-310", "IBI 310"} <= hide.name_variants("IBI310")
    assert "BLB01D1" in hide.name_variants("BL-B01D1")
    assert hide.name_variants("ab") == set()


def test_hider_replaces_drugs_trial_and_sponsor():
    h = make_hider()
    t = h(REC["brief_summary"])
    assert "IBI" not in t and "sintilimab" not in t.lower() and "Innovent" not in t
    assert "Drug A" in t and "Drug B" in t and "sorafenib" in t and "the sponsor" in t
    assert "ORIENT" not in h(REC["title"]) and "NCT04720716" not in h("see NCT04720716")
    assert h("Tyvyt is approved") == "Drug B is approved"


def test_render_hidden():
    h = make_hider()
    code = hide.case_code("salt", "hidden", REC["nct_id"])
    text = hide.render_hidden(REC, h, code, {"Drug A": "antibody; CTLA-4 inhibitor", "Drug B": "antibody; PD-1"},
                              "2026-10-21")
    assert text.startswith(f"# Trial {code}") and "NCT04720716" not in text
    assert not re.search(r"IBI[- ]?3", text, re.I)
    for w in ("Innovent", "Sintilimab", "ORIENT", "Some Partner"):
        assert w.lower() not in text.lower(), w
    assert "## Hidden drugs" in text and "- Drug A: antibody; CTLA-4 inhibitor" in text
    assert "Sponsor: a company that is not one of the largest pharmaceutical companies (name hidden)" in text
    assert "Enrollment: 344" in text
    start = hide.render_hidden(REC, h, code, {"Drug A": "x"}, "2026-10-21", start_view=True)
    assert "Enrollment" not in start and "primary completion" not in start and "- Start: 2021-02-07" in start
    assert "Sites:" not in start


def test_sponsor_type():
    assert hide.sponsor_type("Merck Sharp & Dohme LLC") == "a large pharmaceutical company"
    assert hide.sponsor_type("Sun Yat-sen University").startswith("an academic")
    assert hide.sponsor_type("Akeso").startswith("a company")


def test_twins():
    assert twins.pfs_only(REC)
    r = twins.to_os(REC)
    assert r["primary_outcomes"][0]["measure"].startswith("Overall survival")
    assert not any("Overall survival" in (o.get("measure") or "") for o in r["secondary_outcomes"])
    assert "OS" in r["brief_summary"] and "PFS" not in r["brief_summary"]
    assert twins.half_n(REC)["enrollment"] == 172
    rec, lines = twins.apply("ido1", REC, {"Drug A": "antibody", "Drug B": "antibody"})
    assert lines["Drug A"] == twins.IDO1_LINE and lines["Drug B"] == "antibody" and rec == REC
    assert not twins.pfs_only({"primary_outcomes": [{"measure": "PFS and OS"}]})


def test_evidence_select_and_render():
    assert evidence.disease(REC)[0] == "hepatocellular carcinoma"
    assert evidence.disease({"conditions": ["Carcinoma, Non-Small-Cell Lung"]})[0] == "non-small cell lung cancer"
    arts = [
        {"pmid": "1", "rank": 0, "title": "A review of IBI310", "abstract": "IBI310 review", "article_types": ["Review"]},
        {"pmid": "2", "rank": 1, "title": "IBI310 in HCC: a phase 2 randomized trial",
         "abstract": "Phase 2 randomized hepatocellular", "article_types": ["Clinical Trial"]},
        {"pmid": "3", "rank": 2, "title": "Other", "abstract": "", "article_types": []},
        {"pmid": "4", "rank": 3, "title": "Second review", "abstract": "IBI310", "article_types": ["Review"]},
    ]
    rx = re.compile(r"IBI310", re.I)
    got = evidence.select(arts, 3, rx, r"hepatocellular", set())
    assert [a["pmid"] for a in got] == ["2", "1"]        # no empty abstract, at most one review
    assert evidence.mentions_trial({"title": "ORIENT-99 design", "abstract": ""}, "NCT1", ["ORIENT-99"])
    assert evidence.pub_date({"publication_date": {"year": "2025", "month": "Mar", "day": ""}}) == "2025-03-01"
    long = " ".join(str(i) for i in range(500))
    assert len(evidence.trim_abstract(long, 100).split()) <= 102
    text = evidence.render_pack("2026-10-21", [("IBI310", "experimental", "an anti-CTLA-4 antibody")], got, [],
                                hider=make_hider())
    assert "IBI310" not in text and "Drug A (experimental): an anti-CTLA-4 antibody" in text and "None found." in text


def test_decision():
    d = decision(np.array([0.1, 0.2, 0.5, 0.9]), np.array([0, 1, 0, 1]))
    assert d == {"threshold": 0.3, "n_cancelled": 2, "failures_avoided": 1, "failures_total": 2,
                 "winners_lost": 1, "winners_total": 2}
