"""Track C: forecasting the results of randomized phase 3 cancer trials.

A question is one registered trial. From a frozen registry record (design, arms,
primary endpoint, population, sponsor, dates) a system forecasts:

- ``p_met``: probability that the trial meets its primary endpoint, meaning the
  sponsor or investigators report that the experimental arm achieved the primary
  objective (superiority, or non-inferiority when the trial was designed for it) on at
  least one primary endpoint;
- ``hr_median``, ``hr_low80``, ``hr_high80``: the hazard ratio (experimental versus
  control) of the first time-to-event primary endpoint, with an 80% interval.

Labels come from the first public disclosure of the result (press release, congress
abstract, paper or posted registry results) and carry its date. A forecast is scored
only on trials whose result became public after the forecaster's knowledge cutoff;
trials still unreported form a prospective set that is scored as results arrive.
"""
