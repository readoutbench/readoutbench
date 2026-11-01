You are taking part in a research benchmark of oncology outcome forecasting. You will read one de-identified case packet. It describes a patient with advanced or metastatic cancer at day 0, the day a new line of systemic therapy starts, using only information recorded before that day.

Estimate three probabilities for the regimen started on day 0:

- `p_next_line_or_death_6m`: probability that a new line of systemic therapy starts, or the patient dies, within 183 days of day 0.
- `p_death_12m`: probability of death from any cause within 365 days of day 0.
- `p_progression_6m`: probability that radiology reports progression (later than 28 days after day 0), or the patient dies, within 183 days of day 0.

Give calibrated probabilities: across many similar patients, events should happen about as often as you predict. Use everything in the packet. Do not refuse; give your best estimate.

Reply with one JSON object only, no other text:

{"case_id": "<case id from the packet>", "p_next_line_or_death_6m": 0.00, "p_death_12m": 0.00, "p_progression_6m": 0.00, "key_drivers": ["<up to 5 short phrases>"], "rationale": "<at most 60 words>"}
