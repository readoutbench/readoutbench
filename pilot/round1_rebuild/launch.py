"""Round 1 (rebuilt): the whole launch build in one command, from the selected list to the fingerprints and the Space.

usage: python3 -I launch.py <config.json> [--dry-run]

The config names the inputs (paths relative to the config file's folder, or absolute):
  questions, funnel, review     the selection's output (build_list.py): questions.json, funnel.json, review.json
  cards, records                the cards and the registry records of every candidate still in the list
  drops                         JSONL, one line per trial taken out at launch: {"nct_id", "step"} (the funnel step)
  checks                        the results-check label files, oldest first (a later row for a trial wins)
  min_queries, min_opened       the bar of results_gate.py for a trial to stay in: its latest check row reports "no"
                                and no stop, with at least this many distinct searches and pages opened beyond the
                                registry and its mirrors, a search in Chinese, Japanese or Korean when every site is
                                in East Asia, and a date on or after checked_from; at least 2 and 1 except with
                                --dry-run. A finding in any row sticks.
  checked_from                  the day the records were pulled: a check row dated earlier does not count
  signed_off                    JSONL of the organiser's decisions on rows the checking agent flagged for review
                                ({"nct_id", "decision", "reason"}); a flagged row without one does not pass
                                (required except with --dry-run)
  rules                         the rules file the Space shows (default: docs/round1-rules-draft.md in the repo)
  unchecked_step                the funnel step for trials whose check falls short (they go to the supplement);
                                if absent, such trials stop the build instead
  snapshot, received            the day the records were pulled; the day the reference entries are registered
  refs                          [[entry id, forecasts.jsonl, meta.json(, checked.jsonl)], ...]: the organiser's
                                reference entries, each cut to the round's trials and registered; a Models board
                                entry (setting closed) also names check_model_runs.py's merged output, and its
                                answers must equal it trial for trial
  out                           a new folder (refused if it exists; a failed build leaves it partly written, so
                                rerun into another): list/, cards.jsonl, records.jsonl, sisters.json,
                                round/ (the staged round with its registry), refs_cut/, anchor.txt, space/

Steps, each stopping the build on failure: cut the list → results-check gate → sister groups → stage the round →
check every packet → register the reference entries (each validated against the round) → fingerprints (anchor.py) →
build the Space and dataset, which must find the registry SHA-256 just printed. --dry-run builds everything into the
out folder all the same; it only prints at the end that nothing was posted or uploaded, which this script never does.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
from tdcb.trials import round as tr  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("config")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
cfg = json.load(open(a.config))
base = os.path.dirname(os.path.abspath(a.config))


def p(x):
    return x if os.path.isabs(x) else os.path.join(base, x)


def jsonl(path):
    return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]


def run(*args):
    r = subprocess.run([sys.executable, "-I", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"FAILED: {os.path.basename(args[0])}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r.stdout


REQUIRED_REFS = ("ref-b0", "ref-b1", "ref-opus-5-5", "ref-sonnet-5-5", "ref-haiku-5-5")
if not a.dry_run and not set(REQUIRED_REFS) <= {r[0] for r in cfg["refs"]}:
    raise SystemExit(f"a real build needs every reference entry: {', '.join(REQUIRED_REFS)}")
if not a.dry_run and not cfg.get("checked_from"):
    raise SystemExit("a real build needs checked_from (the day the records were pulled)")
if not a.dry_run and (cfg["min_queries"] < 2 or cfg["min_opened"] < 1):
    raise SystemExit("min_queries must be at least 2 and min_opened at least 1 (lower only with --dry-run)")
if cfg.get("unchecked_step") == "in the round" or any(d["step"] == "in the round" for d in jsonl(p(cfg["drops"]))):
    raise SystemExit("'in the round' is not a step a trial can be dropped at")
out = p(cfg["out"])
if os.path.exists(out):
    raise SystemExit(f"{out} exists: give a new folder")
os.makedirs(out + "/list")

# 1. cut the list
questions = json.load(open(p(cfg["questions"])))
funnel = json.load(open(p(cfg["funnel"])))
drops = jsonl(p(cfg["drops"]))
steps = {}
for d in drops:
    steps.setdefault(d["step"], []).append(d["nct_id"])
ids = [q["nct_id"] for q in questions]
unknown = sorted({d["nct_id"] for d in drops} - set(ids))
if unknown:
    raise SystemExit(f"drops not in the list: {unknown}")

# 2. results-check gate (results_gate.py): every trial left needs a clean, deep enough latest check row; a finding
#    in any row sticks, and a trial with a finding must be in drops (decided and listed) before the build goes on
from results_gate import classify, load_signed_off  # noqa: E402
recs = {json.loads(x)["nct_id"]: json.loads(x) for x in open(p(cfg["records"]), encoding="utf-8") if x.strip()}
dropped = {d["nct_id"] for d in drops}
cls = classify([jsonl(p(f)) for f in cfg["checks"]], recs, [n for n in ids if n not in dropped],
               min_queries=cfg["min_queries"], min_opened=cfg["min_opened"],
               checked_from=cfg.get("checked_from"),
               signed_off=load_signed_off(p(cfg["signed_off"]), ids) if cfg.get("signed_off") else {})
flagged = {n: w for n, (k, w) in cls.items() if k == "finding"}
if flagged:
    raise SystemExit("trials whose check found something, not in drops (decide them first): "
                     + "; ".join(f"{n} ({w})" for n, w in sorted(flagged.items())))
failing = {n: w for n, (k, w) in cls.items() if k in ("shallow", "missing")}
# trials the organiser keeps although no check reached the bar (listed with a reason; marked in questions.json and
# scored apart as well as in the total); a finding still stops the build above
below = {d["nct_id"]: d for d in (jsonl(p(cfg["below_bar"])) if cfg.get("below_bar") else [])}
if set(below) & dropped:
    raise SystemExit(f"below_bar trials also in drops: {sorted(set(below) & dropped)}")
kept_below = sorted(n for n in below if n in set(ids) - dropped)   # all of them marked, clean row or not
# for them the build waives the depth bar, the checking agent's doubt flag and the date bar; a finding in any row
# (above) or a safety statement noted on a safety primary still stops it
unsafe = {n: w for n, w in failing.items() if "safety statement" in w}     # any trial, below the bar or not:
if unsafe:                                                                  # never dropped silently as "unchecked"
    raise SystemExit("trials whose row notes a safety statement on a safety primary (decide them first): "
                     + "; ".join(f"{n} ({w})" for n, w in sorted(unsafe.items())))
failing = {n: w for n, w in failing.items() if n not in below}
if failing:
    if not cfg.get("unchecked_step"):
        raise SystemExit(f"{len(failing)} trials without a deep enough check, e.g. "
                         + "; ".join(f"{n} ({w})" for n, w in sorted(failing.items())[:10]))
    steps.setdefault(cfg["unchecked_step"], []).extend(sorted(failing))
    dropped |= set(failing)
keep = [q for q in questions if q["nct_id"] not in dropped]
for q in keep:
    if q["nct_id"] in kept_below:
        q["check"] = "below the bar"
if kept_below:
    print(f"kept below the bar (marked): {len(kept_below)}")
json.dump(keep, open(out + "/list/questions.json", "w"), indent=1)
inround = [n for n in funnel["in the round"] if n not in dropped]
f2 = {k: v for k, v in funnel.items() if k != "in the round"}
for k, v in steps.items():              # a step that already exists in the funnel gets the new trials added
    f2[k] = list(f2.get(k, [])) + [n for n in v if n not in f2.get(k, [])]
f2["in the round"] = inround
if sorted(inround) != sorted(q["nct_id"] for q in keep):
    raise SystemExit("the funnel's 'in the round' does not match the questions")
json.dump(f2, open(out + "/list/funnel.json", "w"), indent=0)
json.dump(json.load(open(p(cfg["review"]))), open(out + "/list/review.json", "w"), indent=1)
kept = {q["nct_id"] for q in keep}
for name in ("cards", "records"):
    rows = [x for x in open(p(cfg[name]), encoding="utf-8") if x.strip() and json.loads(x)["nct_id"] in kept]
    if len(rows) != len(kept):
        raise SystemExit(f"{name}: {len(rows)} rows for {len(kept)} trials")
    open(f"{out}/{name}.jsonl", "w", encoding="utf-8").write("".join(rows))
print(f"list: {len(ids)} → {len(kept)} trials ({len(dropped)} out: "
      + ", ".join(f"{k}: {len(v)}" for k, v in steps.items()) + ")")

# 3-5. sister groups, staging, packet check
run(HERE + "/make_sisters.py", out + "/cards.jsonl", out + "/records.jsonl", "--out", out + "/sisters.json")
if kept_below:                  # the scorer shows every score without them too (round.leaderboard, "without_below_bar")
    _sis = json.load(open(out + "/sisters.json"))
    _sis["trial_below_bar"] = {n: n in set(kept_below) for n in sorted(kept)}
    json.dump(_sis, open(out + "/sisters.json", "w"), indent=1, sort_keys=True)
s = run(HERE + "/stage_round.py", out + "/list/questions.json", out + "/cards.jsonl", out + "/work",
        "--records", out + "/records.jsonl", "--snapshot", cfg["snapshot"], "--sisters", out + "/sisters.json",
        *(["--closes", cfg["closes"]] if cfg.get("closes") else []))
rdir = out + "/work/round"
man = json.load(open(rdir + "/manifest.json"))
if man["n_trials"] != len(kept) or sorted(man["trials"]) != sorted(kept):
    raise SystemExit(f"the staged round has {man['n_trials']} trials, not the {len(kept)} kept")
c = run(HERE + "/check_packets.py", rdir)
if not re.search(r"\b0 differ", c):
    raise SystemExit("packet check: " + c[-500:])
print(f"staged: {man['n_trials']} trials, {man['n_p_met_questions']} with p_met; {c.strip().splitlines()[-1]}")

# 6. reference entries
if json.load(open(rdir + "/registry.json")) != []:
    raise SystemExit("the staged registry is not empty")
os.makedirs(out + "/refs_cut")
for ref in cfg["refs"]:
    eid, fp, mp = ref[:3]
    rows = [x for x in open(p(fp), encoding="utf-8") if x.strip() and json.loads(x)["nct_id"] in kept]
    meta = json.load(open(p(mp)))
    if meta.get("setting") == "closed" and meta.get("models"):        # not the baselines (no model)
        # a Models board run: its answers must be exactly those check_model_runs.py merged from the checked logs
        if len(ref) < 4:
            raise SystemExit(f"{eid}: a Models board reference needs the checker's merged file as its 4th item")
        checked = {json.loads(x)["nct_id"]: json.loads(x) for x in open(p(ref[3]), encoding="utf-8") if x.strip()}
        mine = {json.loads(x)["nct_id"]: json.loads(x) for x in rows}
        if any(checked.get(n) != o for n, o in mine.items()) or set(checked) & kept != set(mine):
            raise SystemExit(f"{eid}: the forecasts differ from the checked runs in {ref[3]}")
    cut = f"{out}/refs_cut/{eid}.jsonl"
    open(cut, "w", encoding="utf-8").write("".join(rows))
    e = tr.register(rdir, eid, cut, p(mp), cfg["received"], kind="reference")   # validates against the round
    print(f"registered {eid}: {len(rows)} lines, {e['board']}, {e['sha256'][:16]}...")

# 7-8. fingerprints, Space
anchor = run(HERE + "/anchor.py", rdir)
open(out + "/anchor.txt", "w").write(anchor)
m = re.search(r"registry\.json SHA-256 ([0-9a-f]{64})", anchor)
if not m:
    raise SystemExit("anchor.py printed no registry SHA-256:\n" + anchor)
sha = m.group(1)
b = run(os.path.join(REPO, "space", "build_space.py"), rdir, out + "/space", "--expect-registry-sha", sha,
        *(["--rules", p(cfg["rules"])] if cfg.get("rules") else []))
print(b.strip().splitlines()[-1])
print("\n" + anchor)
print("DRY RUN: nothing posted or uploaded." if a.dry_run else
      f"Built in {out}. Next, by hand: post the block above outside the page, then upload {out}/space.")
