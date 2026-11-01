# ReadoutBench

Forecast clinical trials before their results are public.

**Round 1** has 653 company-run, randomized phase 2 and 3 trials whose primary completion falls between July 2026 and March 2027. It opens on 1 November 2026 and closes at the end of 15 November 2026 (23:59:59 UTC). Entries are scored as results come out: an early look at 31 March 2027, the ranked result at 30 June 2027 and an unranked final pass at 31 December 2027.

- Site: https://readoutbench.com
- Enter: https://huggingface.co/spaces/lucasheinrichsb/readoutbench
- Trial files: https://huggingface.co/datasets/readoutbench/readoutbench-r1
- Rules: [`docs/round1-rules-draft.md`](docs/round1-rules-draft.md)
- Fingerprints: [`fingerprints/`](fingerprints/) and the [releases](https://github.com/readoutbench/readoutbench/releases)

## What is here

| Path | Contents |
|---|---|
| `docs/` | The site, the rules, and how the round was built |
| `fingerprints/` | The SHA-256s posted before opening, and the weekly fingerprint of the list of uploads |
| `round1/staged_round/` | The round as entrants get it (also on the dataset): manifest, questions, cards, packets, sister groups, instructions, reference entries |
| `round1/results_check/` | Every results check: searches, pages opened, findings, and the organiser's decisions |
| `round1/launch_inputs/` | The inputs of the launch build, to reproduce it |
| `round1/online_check/` | The registry status pull and the watch list |
| `tdcb/`, `space/`, `pilot/round1_rebuild/` | The scoring code, the submission page, and the scripts that built the round |
| `tests/` | The tests |

The three frontier-model reference entries are sealed until the close: only their SHA-256s are here.

## Reproduce

Python 3.10+ with numpy, scipy, pandas, scikit-learn and pytest.

```
python3 -m pytest -q tests
rm -rf /tmp/readoutbench_rebuild
cd round1/launch_inputs && python3 -I ../../pilot/round1_rebuild/launch.py config_dry_run.json --dry-run
```

The dry run rebuilds the round from its inputs. Its manifest SHA-256 must equal the one in `fingerprints/2026-r1.txt`. Its registry SHA-256 is `bb8c14e5…`, not the posted `44eda736…`, because it registers only the two published baselines.

## Questions

Open an issue.

## Licence

Code: MIT. Round data: CC BY 4.0. Trial records come from ClinicalTrials.gov.
