You are taking part in a research benchmark of clinical-trial forecasting. You will read the registry record of one randomized phase 3 cancer trial. Its result is not included.

Forecast:

- `p_met`: the probability that the trial meets its primary endpoint, meaning that the sponsor or investigators report that the experimental arm achieved the trial's primary objective against the control arm (a statistically significant improvement, or non-inferiority when that is what the trial was designed to show) on at least one primary endpoint, at an interim or the final analysis.
- If the record says the first primary endpoint is time-to-event: `hr_median`, your best estimate of the hazard ratio that will be reported for it (experimental versus control; below 1 favours the experimental arm), and `hr_low80` and `hr_high80`, an interval that you believe contains the reported hazard ratio with 80% probability. Otherwise give null for all three.
- `recalls_result`: true only if you remember the actual reported result of this specific trial, otherwise false.

Give calibrated forecasts: of all trials you give 0.7, about 70% should meet their endpoint. Use the registry information and what you know about the drugs, the disease and earlier trials. Do not refuse; give your best estimate.

Reply with one JSON object only, no other text:

{"case_id": "<NCT id>", "p_met": 0.00, "hr_median": 0.00, "hr_low80": 0.00, "hr_high80": 0.00, "recalls_result": false, "key_reasons": ["<up to 4 short phrases>"]}
