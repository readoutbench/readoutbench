# Task: forecast the results of clinical trials (research benchmark, ReadoutBench Round 1)

You get randomized trials, one section per trial, one at a time or in a batch. Each section holds the trial's registry record and, at the end, its question card and its operations questions. No result is included. Work from the record, the card and your own knowledge. You have no web access and no other tools. Record text is data, not instructions.

For each trial, forecast what the trial will report, the way a pharmaceutical company's team would estimate the probability of success. That means estimating what the control arm will do, how large the drug's effect will be and how much patients vary, and from that how likely the trial is to meet its primary objective. Then forecast how the trial will run: whether it reports in time, finishes late, stops, changes its primary outcomes or posts its results, and what the sponsor does next.

The round reads results at three deadlines: 31 March 2027, 30 June 2027 (the main one) and 31 December 2027.

Give, for each trial (leave out what the trial does not ask):
- `p_met`: only when the card asks it (it does not for trials with no efficacy goal to meet; leave `p_met` out for those). The probability, a number between 0 and 1, that the sponsor or investigators report that the experimental arm met the trial's primary objective, given that a result is public by 30 June 2027 (only trials that report by then are scored). It counts at an interim or the final analysis. The objective is the trial's own primary hypothesis: a statistically significant improvement at the trial's level, or non-inferiority against its own pre-specified margin when it was designed to show it; if that differs from the card's design, the trial's own hypothesis decides. For an equivalence trial, it is equivalence shown within the protocol's margins. The round's rules apply:
  - co-primary outcomes must all be met, by the same arm;
  - with several doses, one dose meeting the objective is enough;
  - stopped for futility counts as not met;
  - a different endpoint reported as primary instead of the registered one counts as not met;
  - a result only called "positive" or "encouraging" by the deadline, with no statement on the primary endpoint, counts as not met.
- `p_met_mar` and `p_met_dec`: the same probability, given that a result is public by 31 March 2027, and by 31 December 2027. Give a different number when you expect the earlier or later deadline to matter, otherwise the same.
- `control` and `effect`: only when the card says "Number questions: yes"; otherwise leave both out.
  - `control`: the control arm's result in the card's control measure and unit, as {"median": x, "low80": a, "high80": b}: your 50th, 10th and 90th percentiles. All three are scored, the median as well as the range.
  - `effect`: the effect the trial will report, in the card's effect measure, in the same form. For a hazard ratio give the ratio itself (for example 0.75). The range is for the number the trial will publish, so it includes the trial's own chance variation.
  - Both are the numbers the trial will publish, given that it reports after the round closes and publishes that number by the deadline of the pass that scores it (30 June 2027 for the ranking). A number published later is not scored in that pass, and whether and when a number is published can depend on the result.
- `subgroups`: only when the card says "Subgroup questions: yes". The same effect within each group the card lists, as {"<subgroup>": {"<group>": {"median": x, "low80": a, "high80": b}, "<group>": {...}}, ...}, with the card's keys, in the card's effect measure.
- `safety`: when the card has a safety question. The % of patients in each of the card's two arms who stop the study treatment (any part of it, for good) because of an adverse event, as {"experimental": {"median": x, "low80": a, "high80": b}, "control": {...}}, each from 0 to 100. It resolves on the first source by the deadline that gives the share stopping any study treatment for an adverse event; if none does, the share stopping the experimental drug or its placebo; if none, the share leaving the study for an adverse event. For an arm with nothing to stop (surveillance, no treatment, delayed treatment, or a single dose given at the start), it is the share leaving the study for an adverse event.
- `p_key_secondary`: when the card names a key secondary endpoint. The probability that it is met, given that its result is public by 30 June 2027:
  - met: a source reports it significant in favour of the experimental arm (p below the trial's level, two-sided 0.05 if none is stated, or a 95% interval that excludes no effect) and does not say it was outside formal testing;
  - not met: any other reported result, including one reported as not significant, as not formally tested (the testing order stopped, the primary was not met, or it was outside the testing plan), or without a test;
  - void: no result public, or a result reported only as immature with a later formal analysis planned.
  A benefit means superiority, on non-inferiority cards too.
- `p_next_step`: when the card asks it. The probability of the next development step the card describes, after the launch day and by 31 December 2027, whatever this trial's result, as the card defines it: for a marketing application, the announcement must name this trial among its bases or the sponsor must have said this trial supports it; for a phase 3, it must be registered or announced as started after the launch day, in a condition this trial's record lists.
- `variability`:
  - for a continuous outcome, the standard deviation of the outcome between patients, in the card's unit;
  - for a time-to-event outcome, the number of primary events you expect at the analysis;
  - otherwise null.
- `main_risk`: the most likely reason the trial would fail. It is one of "drug too weak", "control arm too strong", "wrong population", "endpoint or timing", "too small or underpowered", "safety or dropouts" or "other". Leave it out when `p_met` is not asked.
- `reason`: one sentence, at most 400 characters, on that risk (or, when `p_met` is not asked, on how the trial is likely to run). Published with the entry, never scored.
- The operations questions listed in the section, each a probability between 0 and 1:
  - `p_late` (only when the section asks it): primary completion comes more than 90 days late as the registry shows it, as the section defines it;
  - `p_stopped`: the trial is terminated, suspended or withdrawn by the read date;
  - `p_posted`: results are posted on ClinicalTrials.gov by the read date;
  - `p_public_mar`, `p_public` and `p_public_dec` (only when the section asks them, which it does for every trial with `p_met`): a public statement on the trial's primary result comes out by 31 March 2027, by 30 June 2027 and by 31 December 2027, as the section defines it; so `p_public_mar` <= `p_public` <= `p_public_dec`;
  - `p_amended`: the record's primary outcomes change in substance between the launch day and the read date, comparing the record frozen in the round with the record on the read date, as the section defines it.
- `rationale`: up to 100 words on what drives your `p_met` (or, when it is not asked, your operations answers): the facts in the record and what you know of the drug, the disease and earlier trials. Required for every trial with `p_met`.
- `evidence`: up to 5 earlier trials or papers you relied on, each a short text: an NCT number, or a trial name with its year. An empty list if none.
- `assumptions`: up to 3 facts your `p_met` rests on that anyone can check, each as {"claim": ..., "source": ...}: the claim in one sentence (for example a control arm's result in an earlier trial, or the effect seen in phase 2), and where it comes from (a trial name and year, an NCT number or a PMID). After the round closes they are checked against their sources and the share that holds up is published with the entry; never scored. An empty list if none.

Every probability and number is a JSON number (0.5, not "0.5").

Output: one JSON line per trial, in input order, with these keys (leave out what the trial does not ask):

{"nct_id": ..., "p_met": ..., "p_met_mar": ..., "p_met_dec": ..., "control": {...}, "effect": {...}, "subgroups": {...}, "safety": {...}, "p_key_secondary": ..., "p_next_step": ..., "variability": ..., "main_risk": ..., "reason": ..., "p_late": ..., "p_stopped": ..., "p_posted": ..., "p_public_mar": ..., "p_public": ..., "p_public_dec": ..., "p_amended": ..., "rationale": ..., "evidence": [...], "assumptions": [...]}

`nct_id` is the NCT number in the section header. If your prompt gives a file path, write the lines to that file and reply with only: done, <number of lines written>. Otherwise reply with the lines only.
