You are taking part in a research benchmark of treatment-safety review in oncology. You will read one de-identified case packet for a patient with advanced or metastatic cancer. A regimen is planned to start on day 0. Review it for this specific patient before it starts.

Decide one of:
- `proceed`: give the planned regimen as planned.
- `modify`: give it with a change (different agent, dose adjustment, or management of an interacting drug).
- `avoid`: do not give one or more of the planned agents.
- `test_first`: obtain a test or specialist review before deciding.

List every patient-specific safety concern as a flag with a category from this list: immune, prior_toxicity, renal, hepatic, cardiac, pulmonary, pharmacogenomic, interaction, bleeding, pregnancy, neurologic. Name the planned drug each flag concerns. Return an empty list if there is no concern.

Reply with one JSON object only, no other text:

{"case_id": "<case id from the packet>", "decision": "proceed|modify|avoid|test_first", "regimen": ["<agents you would give>"], "flags": [{"category": "<category>", "drug": "<planned drug>", "note": "<at most 20 words>"}]}
