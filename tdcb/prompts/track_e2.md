You are taking part in a research benchmark on oncology decision support. You will read the case of a patient with advanced cancer at the moment the next line of systemic therapy is being chosen, including the biomarker reports on file.

List the biomarker tests that should still be done now, before the next systemic treatment is chosen: tests that current guidelines (NCCN, ESMO) recommend for this patient at this point, and whose result could change that choice. Read the biomarker reports in the case carefully. Do not list a test whose result is already reported, unless that result is no longer valid for this decision. Do not list tests with no guideline basis for this cancer.

Write each test as it would appear on an order form, one test per list item: the test name only, for example "EGFR mutation", "ALK fusion" or "PD-L1 IHC"; put any reasons in the note. If you would order a panel, list the results you need from it rather than the panel's name. For BRCA1/2 or other inherited-risk genes, say whether you mean germline testing or tumour testing. Return an empty list if nothing is missing.

Reply with one JSON object and nothing else:
{"case_id": "<case id>", "tests_needed": ["<test>", ...], "most_important": "<test or null>", "note": "<one short sentence>"}
