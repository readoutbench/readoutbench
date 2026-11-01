# Pilot 3 results (26 October 2026, internal)

> **Status, 28 October 2026.** The sections below describe Pilot 3 as run on 26 October, on the 852-trial design with the old scoring (Brier ranking without ties, baselines fitted on all earlier trials, no trimmed number score yet). The round has since changed: 836 trials; `p_met` asked given a result by 30 June 2027; baselines matched to each trial's reporting window; two boards (Models: one model, the round's instructions, the packet only; Open: anything else); every entry tested on its own against the registry model and placed in a tier (clearly better, no clear difference, clearly worse), with an exploratory test of whether it adds to the registry model shown beside it; the plain-mean number score with per-question floors. The end-to-end checks (the entry checker, the packets, the operations rows) still hold. The full-round simulation (how often each model ranks first, the interval widths at 250 results) has **not been rerun** under the new design and should be read as indicative only. The backtest is a check of the scoring code, not a clean test of skill: its packets are stubs (the forecasts were made on Pilot 2's packets), and 84 of its 111 trials are in the round's baselines' published training table with their outcomes (the backtest's own B1, Pilot 2's fit, was not trained on them). The addenda at the end re-score it with the newer leaderboards.


Pilot 3 tests the Round 1 setup as it stands after the 26 October changes:
- 852 trials;
- number answers scored with the percentile loss, so the median counts;
- 13 equivalence trials;
- 166 operations-only trials;
- the operations questions, with their own score.

It has three parts:

- **A. Backtest.** Pilot 2's 111 trials, all reported July to October 2026, after the models' training data, run through the round code (`backtest.py`): export, entry check, registration and leaderboard. Entries: Pilot 2's forecasts and its two baselines. Real outcomes and real published numbers.
- **B. Dry run.** Opus 5.5, Sonnet 5.5 and Haiku 5.5, closed book, on 139 trials of the real round, using the reference-entry instructions (`forecast_instructions.md`). The trials (`make_sample.py`, seed 3):
  - 70 main trials, drawn at random;
  - all 13 equivalence trials;
  - 56 operations-only trials, drawn at random.

  No outcomes exist yet.
- **C. Simulation of the full round** (`simulate.py`):
  - `p_met` and numbers: part A's trials resampled to the expected size, about 250 results and 263 published numbers.
  - Operations: part B's answers resampled to the round's mix, with outcomes drawn from the three models' average forecast.

## Findings

1. **The setup works end to end.** All three dry-run entries pass the entry check with no errors and no warnings:
   - 139 lines each;
   - all 66 number questions answered;
   - every operations question answered;
   - no `p_met` given on operations-only trials, no `p_late` where it is not asked, no numbers where none are asked.

   The backtest ran through export, registration and the leaderboard without changes to the code.
2. **On `p_met`, the registry model is likely to lead the ranking.** Part A at full size (250 results, 4,000 resamples; 5th, 50th and 95th percentiles):

   | Entry | Brier | Skill vs B0 | Ranked first |
   |---|---|---|---|
   | Registry model (B1) | 0.164 (0.149–0.179) | +0.22 (+0.16 to +0.28) | 83% |
   | Sonnet 5.5 | 0.178 (0.158–0.200) | +0.15 (+0.04 to +0.26) | 11% |
   | Haiku 5.5 | 0.181 (0.160–0.202) | +0.14 (+0.04 to +0.24) | 4.5% |
   | Opus 5.5 | 0.184 (0.162–0.207) | +0.13 (+0.01 to +0.24) | 2% |
   | Base rate (B0) | 0.211 (0.200–0.222) | 0 | 0% |

   - The best model beats B1 in 17% of resamples at 250 results, 12% at 350 and 4% at 700.
   - Each model beats B0 in 96–98%.
   - Opus beats Sonnet in 16% and Sonnet beats Haiku in 62%: the order among the three models is close to a coin toss.
   - The 95% interval of a model's Brier difference from B0 is about ±0.03 at 250 results.

   This inherits Pilot 2's set, which holds no trial stopped early (73% met). The live round counts futility stops as failures, so its success rate will be lower, and the models' low forecasts will cost them less. Part B shows the same low level on the live trials:

   | Group | Opus | Sonnet | Haiku | History, stopped included |
   |---|---|---|---|---|
   | Phase 3, mean `p_met` | 0.57 | 0.56 | 0.59 | 68% |
   | Phase 2, mean `p_met` | 0.38 | 0.38 | 0.39 | 47% |
   | Equivalence, mean `p_met` | 0.81 | 0.77 | 0.79 | n/a |

   If the round's trials succeed at the historical rates, the models will again sit about 10 points low. The AUROC and calibration columns will then be needed to show what they add.
3. **The number score separates the models, and counting the median helps.** Part A, 116 published numbers (64 effects and 52 control arms), scaled by Opus's range widths:

   | Entry | New score (median counted) | Old interval score | 80% ranges that held the result |
   |---|---|---|---|
   | Opus 5.5 | 4.76 | 2.53 | 70% (effect), 77% (control) |
   | Sonnet 5.5 | 4.93 | 2.57 | 70%, 75% |
   | Sonnet 5.5, second run | 4.92 | 2.58 | 75%, 69% |
   | Haiku 5.5 | 5.47 | 2.87 | 64%, 62% |

   - Paired gaps, new score: Opus − Haiku −0.71 [−1.23, −0.14]; Sonnet − Haiku −0.54 [−1.01, −0.08]; Opus − Sonnet −0.17 [−0.43, +0.12]; Sonnet − its second run +0.00 [−0.20, +0.21].
   - With the old score, the gaps are about half as large, but so is the whole scale. What matters is the gap relative to its noise, and that is about 20–35% larger with the median counted. Paired t on the per-answer log ratio:
     - Opus vs Haiku: −2.9 new, −2.1 old;
     - Opus vs Sonnet: −2.4 new, −2.0 old;
     - Sonnet vs Haiku: −1.5 new, −1.2 old.
   - At full size (263 answers), Opus beats Haiku in 100% of resamples, Sonnet beats Haiku in 99.98%, and Opus beats Sonnet in 95%.
   - The order does not depend on whose widths set the scale: Opus, Sonnet, Haiku or their geometric mean all give the same order and gaps.
   - The score is heavy-tailed: the median answer scores about 2.5, the mean about 5, and the top 10% above 9. One wild miss moves an entry's average visibly.
4. **The operations questions add the most results, and they separate entries only where the models disagree.** The full round asks 852 `p_stopped`, 852 `p_posted` and 676 `p_late` questions, against about 250 `p_met` results. Part B's answers (mean forecast):

   | Question | Opus | Sonnet | Haiku | Mean absolute gap between models |
   |---|---|---|---|---|
   | `p_late` | 0.46 | 0.40 | 0.39 | 0.09–0.11 |
   | `p_stopped` | 0.06 | 0.06 | 0.07 | 0.01–0.02 |
   | `p_posted` | 0.10 | 0.08 | 0.24 | 0.04 (Opus–Sonnet); 0.14–0.16 (with Haiku) |

   - `p_late` follows the launch-day status: 0.53–0.67 for trials still recruiting, against 0.19–0.21 for trials active and not recruiting.
   - `p_posted` falls with the registered date: for trials finishing July to September 2026, Opus 0.24, Sonnet 0.22, Haiku 0.47; for January to March 2027, 0.05, 0.04 and 0.14. For comparison, 50.3% of applicable industry trials posted results within the 12-month legal deadline in the cohort studied by DeVito, Bacon and Goldacre (Lancet 2020). That suggests Opus and Sonnet may be low for the earliest trials, but many of the round's trials are not covered by the US law.
   - `p_stopped`: the three models nearly agree, so it will hardly separate entries.
   - In the consensus world (outcomes drawn from the models' average), the Brier scores are about 0.20 (`p_late`), 0.057 (`p_stopped`) and 0.10–0.12 (`p_posted`). Haiku's `p_posted` scores worse than Opus's in 98% of runs there and worse than Sonnet's in 96%, but only because the average sits nearer Opus and Sonnet. The real outcome could reverse that.
5. **The models still under-name the control arm.** Of the 83 trials with `p_met`, "control arm too strong" is the main risk for 11 (Opus), 10 (Sonnet) and 8 (Haiku). "Drug too weak" is named 27–32 times. Pilot 2 found the control arm to be where the forecasts fail.
6. **Ranges and consistency look as in Pilot 2.**
   - Sonnet's number ranges are 6% wider than Opus's (median ratio) and Haiku's 13% narrower. Haiku's ranges were also the narrowest and least well calibrated in Pilot 2.
   - Gap between stated and implied `p_met`: 0.11 (Opus and Sonnet) and 0.14 (Haiku). It exceeds 0.2 on 15–21% of the number questions.
   - Share of `p_met` below 0.1 or above 0.9: Opus 19%, Sonnet 13%, Haiku 7%.
7. **Cost and time.** About 115k–170k tokens per batch of 14 trials, including the instructions; 1–4 minutes per batch. In line with Pilot 2's per-trial estimate: about $95 for the three reference models on 852 trials, less on the Batch API.

## What this means for the round

- **Expect the registry model at the top of the `p_met` ranking.** It is useful to say so on the page before the results arrive. The models' value shows in AUROC and in the number score more than in raw Brier.
- **Keep the median in the number score.** It separates the models 20–35% more clearly than the range alone, and the order is stable whichever entry sets the scale. The page should show the median per entry next to the mean, because one large miss moves the mean.
- **The operations score will have the most results.** It will separate entries mainly on `p_posted` and `p_late`.
  - `p_stopped` adds little; it could be dropped, or kept as a cheap check.
  - The reference based on the share in the round should be described exactly as computed.
- **Equivalence trials:** the models give 0.77–0.81. That may be low for biosimilar and bioequivalence trials, which are designed and sized to succeed. Few as they are, their results will show it.

## Caveats

- Part A's trial mix is Pilot 2's (completed trials only, 73% met), not Round 1's.
- Part C's operations outcomes are drawn from the models' own average, so they show spread, not who is right.
- 139 dry-run trials; one run per model; one model family.

Files:
- Data and outputs are in the session scratchpad (`p3/`):
  - `stage/`: the staged sample round;
  - `batches/`, `out_<model>/` and `forecasts_<model>.jsonl`: the dry run;
  - `backtest/`: the backtest round and its `leaderboard.json`;
  - `dryrun.json` and `simulate.json`.
- The scripts are `make_sample.py`, `backtest.py`, `dryrun.py` and `simulate.py`.

## Addendum, 26 October: the backtest re-scored after the outside reviews

The same 111 trials (81 met, 73%) scored with the revised leaderboard: the Brier score split into reliability (calibration; lower is better) and resolution (sorting met from not met; higher is better), the level gap (mean forecast minus the share met), and the number score as a 5%-trimmed mean with width floors.

| Entry | Brier | AUROC | Reliability | Resolution | Level gap | Number score (trimmed / mean / median) |
|---|---|---|---|---|---|---|
| Registry model (B1, Pilot 2 fit) | 0.164 | 0.79 | 0.013 | 0.046 | −0.07 | – |
| Sonnet 5.5 (repeat run) | 0.176 | 0.81 | 0.042 | 0.061 | −0.14 | 3.67 / 4.85 / 2.53 |
| Sonnet 5.5 | 0.179 | 0.81 | 0.035 | 0.055 | −0.15 | 3.64 / 4.86 / 2.58 |
| Haiku 5.5 | 0.181 | 0.78 | 0.024 | 0.042 | −0.13 | 4.10 / 5.29 / 2.72 |
| Opus 5.5 | 0.184 | 0.80 | 0.034 | 0.045 | −0.14 | 3.50 / 4.71 / 2.38 |
| Base rate (B0, Pilot 2 fit) | 0.210 | 0.50 | 0.013 | 0 | −0.12 | – |

- The registry model's lead on the Brier score is level, not knowledge: the models sort the trials as well or better (AUROC 0.80–0.81 against 0.79, resolution up to 0.061 against 0.046) but forecast about 14 points too low, against 7 for the registry model. One reviewer computed that moving every model forecast up to the observed share would put Sonnet ahead of the registry model after the same shift (about 0.157 against 0.159).
- So for the live round the baselines are refitted on earlier trials matched to each trial's reporting window, `p_met` is defined as the chance of success given a result by the deadline, and the leaderboard shows resolution, AUROC and the level gap next to the Brier score.
- The number score keeps its order (Opus, Sonnet, Haiku) under the trimmed mean, the plain mean and the median. (After the second review the ranked number score is the plain mean, and the floors are set per question; the trimmed mean is shown only.)

## Addendum, 28 October: the backtest under the tier rule

The same 111 trials, scored as the round will be (after the fifth review): each model on the Models board, tested on its own against the registry model (B1) for a Brier gap larger than 0.005 either way, and the exploratory test of whether each adds to B1 (10 folds, averaged over 5 splits, interval from 500 resamples that each run the same 5 splits, refitting every fold; with Pilot 2 there are no sister groups, so each trial is its own group). The backtest's B1 is Pilot 2's fit, which was not trained on any of these trials; it is not the round's B1, so the backtest says nothing about how the round's refitted baselines behave.

| Entry | Tier | Brier | Skill vs B1 (95%) | Adds to B1: Brier gain (95%) |
|---|---|---|---|---|
| Sonnet 5.5 (repeat run) | no clear difference | 0.176 | −0.07 (−0.33 to 0.16) | +0.015 (−0.005 to 0.036) |
| Sonnet 5.5 | no clear difference | 0.178 | −0.09 (−0.36 to 0.15) | +0.013 (−0.008 to 0.034) |
| Haiku 5.5 | no clear difference | 0.181 | −0.10 (−0.35 to 0.12) | +0.007 (−0.012 to 0.025) |
| Opus 5.5 | no clear difference | 0.184 | −0.12 (−0.40 to 0.11) | +0.013 (−0.007 to 0.032) |
| Registry model (B1) | baseline | 0.164 | – | – |

- No model can be told apart from the registry model at 111 trials: each would have needed a Brier score about 0.043 lower than B1's to be placed clearly better.
- The "adds to" gains are positive for all four, but every interval includes 0, so the backtest does not show that the models carry information B1 lacks. It is a check that the test runs, not evidence either way.
