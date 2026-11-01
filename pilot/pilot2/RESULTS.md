# Pilot 2 results (25 October 2026, internal)

Pilot 2 asked Opus 5.5, Sonnet 5.5 and Haiku 5.5 for the decomposed forecast a pharmaceutical team makes: the control arm's result, the drug's effect (median and 80% interval), the variability, the probability the trial meets its primary objective (`p_met`), and the main risk. Closed book, from the registry record and the question card. It is internal only: the trials' results are already public.

## Set

- 111 randomized trials from all areas whose primary result first became public between July and October 2026, after the models' training data. 81 met, 30 did not (73%).
- Labels: 78 from the web results check, 17 from Pilot 1, 16 from PubMed alone.
- Published numbers: extracted for 69 trials (58 exact, 11 close). 3 were dropped by hand (arbitrary units; trial identity not confirmed; a risk ratio where the card asked for a difference), leaving 64 effects and 52 control arms. The other 42 trials announced met or not met without numbers, often in exchange filings.
- B1: the registry model (`b1.py`), trained on 135 history trials.

## Findings

1. **All three models give lower chances than this set bore out.** Their mean `p_met` is 0.58–0.60 against 73% met. Trials they gave under 30% met 35–41% of the time; trials they gave 30–50% met 57–65% of the time. On raw Brier they are worse than B1: 0.184 (Opus), 0.178 (Sonnet) and 0.181 (Haiku), against 0.164.

   Much of this gap comes from the set, not the models (see the base-rate test below). By construction, the set holds no trial that was stopped early. Stopped trials always count as history, and none of the 14 stopped history trials met.
2. **They rank trials well, and they know something the registry model does not.** AUROC: Opus 0.80, Sonnet 0.81, Haiku 0.78; B1 0.79. Their forecasts correlate only 0.42–0.48 with B1 (logit scale).
   - Adds-information test against B1: p < 0.001 for Opus and Sonnet, p = 0.002 for Haiku.
   - After the bias is corrected (5-fold cross-validated recalibration), Brier is 0.157 (Opus), 0.153 (Sonnet) and 0.164 (Haiku), against 0.159 for B1.
   - B1 combined with a model, cross-validated: 0.147 with Opus, 0.146 with Sonnet. That is about 8% better than B1 alone.
3. **The models cannot be told apart on `p_met`.** The paired Brier difference is +0.006 for Opus minus Sonnet [−0.010, +0.021]. Opus and Sonnet correlate 0.94, Haiku 0.83–0.84 with them.
   - SD of the paired per-trial difference: 0.085 for Opus vs Sonnet, 0.12–0.14 against Haiku.
   - At 700 questions, the smallest detectable difference would be about 0.009 (Opus vs Sonnet) and 0.014 (against Haiku).
4. **The models' own numbers predict worse than their stated `p_met`.** Pushing their control, effect and variability forecasts through each trial's design gives a `p_met` that is too extreme: 32% of these implied values are below 0.1 or above 0.9, against 11–19% of the stated ones. It is also less accurate:

   | Model | Brier, implied | Brier, stated | AUROC, implied | AUROC, stated |
   |---|---|---|---|---|
   | Opus | 0.214 | 0.184 | 0.75 | 0.80 |
   | Sonnet | 0.193 | 0.178 | 0.78 | 0.81 |
   | Haiku | 0.203 | 0.181 | 0.75 | 0.78 |

   The cause is that the effect intervals are too narrow. 80% intervals held the published effect in 70% (Opus, Sonnet) and 64% (Haiku) of trials; hazard ratios 56–69%, responder rates 40–60%.
5. **The broken link is the control arm.** The control arms did better than forecast in 71–75% of trials. Time-to-event trials miss most: control patients went longer without an event than forecast, by a median of 0.9 to 1.3 of the model's own spread.
   - In the 12 failed trials with a published control number, the control did better than forecast in 11, for every model.
   - Yet in the 30 failed trials the models named "control arm too strong" as the main risk only 1–3 times. They named "drug too weak" 13–19 times.
6. **The numbers separate the models a little more than `p_met` does.**
   - Control-arm log score: Sonnet beats Haiku by +0.78 [+0.12, +1.64]; Opus beats Haiku by +0.48 [−0.03, +1.02].
   - Opus and Sonnet are indistinguishable on every score.
   - Haiku's control intervals cover only 42% (time-to-event) and 33% (responders).
7. **Cost per trial** (median tokens: about 10k in and 1.3k out for Opus and Sonnet, 20k in and 4k out for Haiku):

   | Model | Per trial | 700 trials |
   |---|---|---|
   | Opus | ≈ $0.07 | ≈ $47 |
   | Sonnet | ≈ $0.035 | ≈ $23 |
   | Haiku | ≈ $0.004 | ≈ $3 |
   | Fable 5.1 (same tokens) | ≈ $0.17 | ≈ $115 |

   The Batch API halves these.

## Base-rate test (same day)

Sonnet and Opus forecast the same 111 trials again, with one paragraph added to the instructions (`forecast_instructions_br.md`). It gives historical success rates of 72% for phase 3 and 45% for phase 2. A plain Sonnet rerun without the paragraph measures run-to-run noise.

- **The rates barely moved the forecasts.**

  | Group | Without rates | With rates | Told | Actual |
  |---|---|---|---|---|
  | Phase 3 | 0.67–0.69 | 0.68 | 72% | 81% |
  | Phase 2 | 0.36–0.39 | 0.38–0.40 | 45% | 55% |

  - Trials that moved by more than 0.1: 12% for Sonnet and 5% for Opus. The plain rerun moved 8%.
  - Brier: Sonnet 0.178 → 0.169, a paired difference of +0.010 [−0.001, +0.021]; the rerun alone gave 0.176. Opus 0.184 → 0.178, a difference of +0.006 [−0.003, +0.015].
  - The recalibration shift stayed at +0.83 to +0.86.
- **Run-to-run noise is small.** The two plain Sonnet runs correlate 0.98, and the SD of their paired per-trial Brier difference is 0.051. Between Opus and Sonnet it is 0.085, so one run per model is enough.
- **The told rates were slightly off.** A phase lookup missed some records. The corrected rates, stopped trials included, are 68% for phase 3 (63 of 92) and 47% for phase 2 (20 of 43).
- **Why the set looks optimistic.** The history rate depends on whether stopped trials are counted:

  | History, 135 trials | Phase 3 | Phase 2 | Overall |
  |---|---|---|---|
  | Stopped included | 68% | 47% | 61% |
  | Completed only | 73% | 57% | 69% |

  The pilot set holds completed trials only, and 73% of them met. The models' mean of 0.59 sits near the rate that includes stopped trials. Part of the "pessimism" is therefore the models pricing in early stops that this set cannot contain. Some of it is real: the record snapshot showed the trial as completed, and a careful forecaster could have used that.

For Round 1, trials stopped for futility during the round count as not met (rule 5). The level should be judged on the Round 1 results, not on this set. A base-rate paragraph does not change the forecasts, so it stays out of the question.

## Caveats

- 111 trials, of which 30 failed. Numbers were found for 64 effects and 52 control arms. The effect errors split by outcome are biased by the outcome itself, since met trials report better effects. The overall and control-arm figures are less affected.
- Only one model family was tested.
- Trial names and sponsors are shown.
- The records were pulled after the results. Leak phrases are removed, but status fields remain.
- Extraction is by an agent. A quote check found 19 numbers not in their quote: most were formatting or explained in the notes, and 3 trials were dropped.

## What this means for the round

- Score `p_met` on two things: raw Brier (what a user gets) and discrimination (AUROC, or recalibrated Brier). Otherwise the leaderboard mostly measures the pessimism bias.
- Add a control-arm question (median and 80% interval) for every trial with an interpretable scale. It is where the models go wrong, and it separates models better than `p_met`. Keep the effect question for hazard ratios, responder rates and standard clinical scales. Never ask for numbers in arbitrary units.
- Drop `variability` and the implied `p_met`: the decomposition did not beat the stated number. Keep `main_risk` as an unscored diagnostic.
- Number questions resolve only when numbers are published (about 60% here). Scoring them needs a rule for that.

Files:
- Data and outputs are in the session scratchpad (`p2/`).
- `report.json` holds the full scores.
- The scripts are `score.py`, `compare.py`, `links.py`, `numscore.py` and `crps.py`.
