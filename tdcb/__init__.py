"""Treatment Decision Calibration Benchmark (TDCB), v1.

Track A: calibration of patient-level outcome probabilities at the start of a
new line of systemic therapy, scored against what actually happened.
Track B: paired safety traps (planted contraindication vs clean twin).
Track C: forecasts of phase 3 cancer trial results (tdcb.trials).
Track D: trial facts and saying "I don't know", with made-up trials (tdcb.facts).
Track E: missing biomarker tests; Track F: asking for a decisive missing result
before recommending treatment (tdcb.patient).

Tracks A, B, E and F are built locally from each user's own copy of MSK-CHORD
(cBioPortal study ``msk_chord_2024``, CC BY-NC-ND 4.0). Nothing derived from
the dataset is redistributed with this code. Tracks C and D use public registry
data and published results.
"""

__version__ = "0.3.1"

DAYS_PER_MONTH = 30.4375
