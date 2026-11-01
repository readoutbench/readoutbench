You are taking part in a research benchmark about what language models know about cancer clinical trials. You will read the description of one randomized phase 3 trial: its title, sponsor, drugs, condition and registered primary endpoint. Answer from your own knowledge only.

Say whether, as far as you know, the result for the trial's primary endpoint has been made public:
- `status`: "met" (the sponsor or investigators reported that the primary endpoint was met), "not_met" (reported as not met, including stopping for futility), "no_result_known" (you know this trial but no reported result), or "unknown_trial" (you do not know this trial).
- `hr`: if the status is met or not_met and the primary endpoint is time-to-event, the reported hazard ratio as you remember it; otherwise null.
- `first_public`: the year and month (YYYY-MM) when the result was first made public, or null.
- `confidence`: your probability, from 0 to 1, that your status is correct.

Do not guess a result you do not remember: answering no_result_known or unknown_trial is better than inventing a result.

Reply with one JSON object only, no other text:

{"case_id": "<question id>", "status": "...", "hr": null, "first_public": null, "confidence": 0.0}
