"""Command line: build, baselines, run, score-a, compare, score-b, trials, facts, patient, synth."""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd


def _write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def cmd_build(a):
    from .build import build
    m = build(a.data, a.out, a.test_per_type, a.dev_per_type, a.seed, not a.no_train_features,
              a.traps_per_template, salt_file=a.salt_file, templates_file=a.templates)
    print(json.dumps(m["counts"], indent=1))


def cmd_baselines(a):
    from . import baselines
    priv = os.path.join(a.build, "private")
    pred_dir = os.path.join(a.build, "predictions")
    os.makedirs(pred_dir, exist_ok=True)
    train = pd.read_csv(os.path.join(priv, "labels_train.csv"))
    b0 = baselines.fit_b0(train)
    ftr = pd.read_csv(os.path.join(priv, "features_train.csv.gz"))
    train_f = train.merge(ftr, on="case_id", how="inner")
    X = train_f.drop(columns=[c for c in train.columns if c != "case_id"]).drop(columns=["case_id"])
    b1 = baselines.fit_b1(X, train_f[train.columns], seed=a.seed)
    for split in ("dev", "test"):
        lab = pd.read_csv(os.path.join(priv, f"labels_{split}.csv"))
        _write_jsonl(os.path.join(pred_dir, f"b0_{split}.jsonl"), baselines.predict_b0(b0, lab))
        f = pd.read_csv(os.path.join(priv, f"features_{split}.csv.gz"))
        f = lab[["case_id"]].merge(f, on="case_id", how="left")
        _write_jsonl(os.path.join(pred_dir, f"b1_{split}.jsonl"),
                     baselines.predict_b1(b1, f.drop(columns=["case_id"]), f["case_id"]))
    # scores summarise the labels, so they stay in private/
    from . import score_a
    rep_dir = os.path.join(priv, "reports")
    os.makedirs(rep_dir, exist_ok=True)
    for split in ("dev", "test"):
        lab = pd.read_csv(os.path.join(priv, f"labels_{split}.csv"))
        ref = score_a.load_predictions(os.path.join(pred_dir, f"b0_{split}.jsonl"))
        for name in ("b0", "b1"):
            rep = score_a.score(lab, score_a.load_predictions(os.path.join(pred_dir, f"{name}_{split}.jsonl")), ref)
            with open(os.path.join(rep_dir, f"{name}_{split}.json"), "w") as fh:
                json.dump(rep, fh, indent=1)
    print(f"wrote B0 and B1 predictions to {pred_dir} and their scores to {rep_dir}")


def cmd_run(a):
    from . import runner
    kw = {}
    if a.provider == "openai" and a.base_url:
        kw["base_url"] = a.base_url
    prov = runner.make_provider(a.provider, a.model, **kw)
    pdir = os.path.join(a.build, "packets", a.track.upper(), a.split)
    if a.track.upper() == "D" and not os.path.isdir(pdir):      # a facts build has one question set
        pdir = os.path.join(a.build, "packets", "D", "questions")
    if not os.path.isdir(pdir):
        sys.exit(f"no packets in {pdir}")
    stats = runner.run(pdir, a.out, a.track.upper(), prov, workers=a.workers, limit=a.limit)
    print(json.dumps({k: v for k, v in stats.items() if k != "failures"}, indent=1))


def cmd_score_a(a):
    from . import score_a
    lab = pd.read_csv(os.path.join(a.build, "private", f"labels_{a.split}.csv"))
    preds = score_a.load_predictions(a.pred)
    ref = score_a.load_predictions(a.ref) if a.ref else None
    rep = score_a.score(lab, preds, ref, n_boot=a.n_boot)
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(rep, fh, indent=1)
    print(score_a.summary_table({os.path.basename(a.pred): rep}).round(4).to_string(index=False))


def cmd_compare(a):
    from . import score_a
    lab = pd.read_csv(os.path.join(a.build, "private", f"labels_{a.split}.csv"))
    systems = {}
    for spec in a.pred:
        name, _, path = spec.partition("=")
        if not path:
            name, path = os.path.splitext(os.path.basename(spec))[0], spec
        systems[name] = score_a.load_predictions(path)
    if a.cases:
        keep = set(score_a.load_predictions(a.cases)) if a.cases.endswith(".jsonl") else \
            set(open(a.cases).read().split())
        lab = lab[lab["case_id"].isin(keep)].reset_index(drop=True)
    ref = score_a.load_predictions(a.ref) if a.ref else None
    table = score_a.compare(lab, systems, ref, n_boot=a.n_boot, by_type=a.by_type)
    if a.out:
        table.to_csv(a.out, index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(table.round(4).to_string(index=False))


def cmd_score_b(a):
    from . import score_b
    with open(os.path.join(a.build, "private", "track_b_key.json")) as fh:
        key = [k for k in json.load(fh) if a.split == "all" or k["split"] == a.split]
    rep = score_b.score(score_b.load_predictions(a.pred), key)
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(rep, fh, indent=1)
    print(json.dumps(rep["overall"], indent=1))


def cmd_trials(a):
    from .trials import baselines as tb, build as tbuild, records, score as tscore
    if a.trials_cmd == "fetch":
        ids = [x for x in open(a.ids).read().split() if x.upper().startswith("NCT")]
        print(f"fetched {len(records.fetch(ids, a.out))} records into {a.out}")
    elif a.trials_cmd == "build":
        m = tbuild.build(a.registry, a.labels, a.out, cutoff=a.cutoff, snapshot_date=a.snapshot_date,
                         exclude=tbuild.read_exclusions(a.exclude))
        print(json.dumps({k: m[k] for k in ("cutoff", "counts", "met_rate", "with_hr")}, indent=1),
              f"\nexcluded: {len(m['excluded'])}; packets with leak phrases: {len(m['leak_phrases'])}")
    elif a.trials_cmd == "baselines":
        key = json.load(open(os.path.join(a.build, "private", "key_C.json")))
        recs = {}
        for s in ("post_cutoff", "pre_cutoff", "open"):
            d = os.path.join(a.build, "packets", "C", s)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.endswith(".json"):
                    o = json.load(open(os.path.join(d, f)))
                    recs[o["case_id"]] = o["record"]
        b0, b1, info = tb.fit_and_predict(recs, key)
        pdir = os.path.join(a.build, "predictions")
        os.makedirs(pdir, exist_ok=True)
        _write_jsonl(os.path.join(pdir, "c_b0.jsonl"), b0)
        _write_jsonl(os.path.join(pdir, "c_b1.jsonl"), b1)
        print(json.dumps(info, indent=1))
    elif a.trials_cmd == "round":
        from .trials import round as tround
        if a.round_cmd == "export":
            m = tround.export(a.build, a.out, a.round, closes=a.closes, opens=a.opens, cards=a.cards,
                              deadline=a.deadline, operations=a.operations, ops_read=a.ops_read,
                              final_deadline=a.final_deadline, sisters=a.sisters, instructions=a.instructions,
                              early_deadline=a.early_deadline)
            print(json.dumps({k: m[k] for k in ("round", "opens", "closes", "n_trials", "n_time_to_event")}, indent=1))
        elif a.round_cmd == "validate":
            if a.forecasts:
                v = tround.validate(a.round_dir, a.forecasts, a.meta)
            elif a.meta and a.sha256_file:
                man = json.load(open(os.path.join(a.round_dir, "manifest.json"), encoding="utf-8"))
                v = tround.check_sealed(a.meta, a.sha256_file, instructions_sha256=man.get("instructions_sha256"))
            else:
                raise SystemExit("give --forecasts (and --meta), or --meta and --sha256-file for a sealed submission")
            print(json.dumps(v, indent=1))
            if not v["ok"]:
                raise SystemExit(1)
        elif a.round_cmd == "register":
            expect = None
            if a.expect_sha256_file:
                expect = tround.read_sha256_file(a.expect_sha256_file)
                if expect is None:
                    raise SystemExit(f"{a.expect_sha256_file} holds no SHA-256")
            e = tround.register(a.round_dir, a.id, a.forecasts, a.meta, a.received, kind=a.kind, expect_sha256=expect,
                                of=a.of)
            print(json.dumps(e, indent=1))
        elif a.round_cmd == "leaderboard":
            lb = tround.leaderboard(a.build, a.round_dir, n_boot=a.n_boot, min_scored=a.min_scored,
                                    numbers_ref_id=a.numbers_ref, ops_outcomes=a.ops_outcomes,
                                    scoring_pass=getattr(a, "pass"), labels_as_of=a.labels_as_of,
                                    next_step_outcomes=a.next_step_outcomes, amend_outcomes=a.amend_outcomes,
                                    assumption_checks=a.assumption_checks)
            if a.out:
                with open(a.out, "w") as fh:
                    json.dump(lb, fh, indent=1)
            print(json.dumps(lb["status"], indent=1))
        elif a.round_cmd == "ops-resolve":
            recs = {}
            with open(a.records, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        r = json.loads(line)
                        recs[str(r["nct_id"]).upper()] = r
            res = tround.resolve_operations(a.round_dir, recs, a.read_date)
            with open(a.out, "w", encoding="utf-8") as fh:
                for o in res.values():
                    fh.write(json.dumps(o) + "\n")
            print(json.dumps({k: sum(o[k] == 1 for o in res.values()) for k in ("late", "stopped", "posted")} |
                             {"n_trials": len(res), "n_records_missing": sum(n not in recs for n in res)}, indent=1))
    elif a.trials_cmd == "score":
        key = json.load(open(os.path.join(a.build, "private", "key_C.json")))
        ref = tscore.load_predictions(a.ref) if a.ref else None
        rep = tscore.score(tscore.load_predictions(a.pred), key, ref, cutoff=a.cutoff,
                           sets=tuple(a.sets.split(",")), n_boot=a.n_boot)
        if a.out:
            with open(a.out, "w") as fh:
                json.dump(rep, fh, indent=1)
        print(json.dumps(rep, indent=1))


def cmd_facts(a):
    from . import facts
    if a.facts_cmd == "build":
        ph = a.phantoms
        if ph is None:
            ph = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "phantom_trials.json")
        print(json.dumps(facts.build(a.trials, ph, a.out, salt=a.salt), indent=1))
    else:
        key = json.load(open(os.path.join(a.build, "private", "key_D.json")))
        rep = facts.score(facts.load_predictions(a.pred), key, cutoff=a.cutoff, n_boot=a.n_boot)
        if a.out:
            with open(a.out, "w") as fh:
                json.dump(rep, fh, indent=1)
        print(json.dumps(rep, indent=1))


def cmd_patient(a):
    from . import facts, patient
    if a.patient_cmd == "build":
        print(json.dumps(patient.build(a.build, a.split, a.n_per_type_e, a.n_per_type_f, a.seed, a.rules,
                                       with_reports=a.with_reports), indent=1))
        return
    track = a.patient_cmd.split("-")[-1].upper()
    rules = patient.load_rules(a.rules)
    key = json.load(open(os.path.join(a.build, "private", f"key_{track}_{a.split}.json")))
    preds = facts.load_predictions(a.pred)
    if track == "E2":                                  # free-text answers: map them to menu IDs first
        from . import reports
        preds, norm = reports.normalize_predictions(preds)
    rep = (patient.score_e(preds, key, rules["menu"], n_boot=a.n_boot) if track in ("E", "E2")
           else patient.score_f(preds, key, rules["menu"]))
    if track == "E2":
        rep["normalisation"] = norm
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(rep, fh, indent=1)
    print(json.dumps(rep, indent=1))


def cmd_synth(a):
    from .synth import write_synthetic_study
    write_synthetic_study(a.out, n_patients=a.n, seed=a.seed)
    print(f"synthetic study written to {a.out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="tdcb", description="Treatment Decision Calibration Benchmark")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build packets, labels and features from MSK-CHORD files")
    b.add_argument("--data", required=True, help="directory with the msk_chord_2024 study files")
    b.add_argument("--out", required=True)
    b.add_argument("--test-per-type", type=int, default=600)
    b.add_argument("--dev-per-type", type=int, default=100)
    b.add_argument("--seed", type=int, default=20261021)
    b.add_argument("--traps-per-template", type=int, default=10)
    b.add_argument("--no-train-features", action="store_true")
    b.add_argument("--salt-file", help="reuse a salt (e.g. to reproduce a build); default: a new secret salt")
    b.add_argument("--templates", help="Track B template bank (default: the packaged public examples)")
    b.set_defaults(func=cmd_build)

    bl = sub.add_parser("baselines", help="fit B0 and B1 on train, predict dev and test")
    bl.add_argument("--build", required=True)
    bl.add_argument("--seed", type=int, default=0)
    bl.set_defaults(func=cmd_baselines)

    r = sub.add_parser("run", help="send packets to a model and write predictions.jsonl")
    r.add_argument("--build", required=True)
    r.add_argument("--track", choices=list("ABCDEF") + list("abcdef") + ["E2", "e2"], required=True,
                   help="E2: Track E with the results inside reports and free-text answers")
    r.add_argument("--split", default="dev",
                   help="dev or test for tracks A, B, E and F; post_cutoff, pre_cutoff or open for track C; "
                        "questions for track D")
    r.add_argument("--provider", choices=["anthropic", "openai", "mock"], required=True)
    r.add_argument("--model")
    r.add_argument("--base-url")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--limit", type=int)
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_run)

    sa = sub.add_parser("score-a", help="score Track A predictions")
    sa.add_argument("--build", required=True)
    sa.add_argument("--split", choices=["dev", "test"], default="dev")
    sa.add_argument("--pred", required=True)
    sa.add_argument("--ref", help="reference predictions for the skill score (e.g. predictions/b0_dev.jsonl)")
    sa.add_argument("--n-boot", type=int, default=0)
    sa.add_argument("--out")
    sa.set_defaults(func=cmd_score_a)

    c = sub.add_parser("compare", help="score several Track A systems on the same cases")
    c.add_argument("--build", required=True)
    c.add_argument("--split", choices=["dev", "test"], default="dev")
    c.add_argument("--pred", nargs="+", required=True, help="predictions as name=path or path")
    c.add_argument("--ref", help="reference system for the skill score (paired)")
    c.add_argument("--cases", help="restrict to these case IDs (.jsonl predictions or a whitespace list)")
    c.add_argument("--n-boot", type=int, default=0)
    c.add_argument("--by-type", action="store_true")
    c.add_argument("--out", help="write the table as CSV")
    c.set_defaults(func=cmd_compare)

    sb = sub.add_parser("score-b", help="score Track B predictions")
    sb.add_argument("--build", required=True)
    sb.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    sb.add_argument("--pred", required=True)
    sb.add_argument("--out")
    sb.set_defaults(func=cmd_score_b)

    t = sub.add_parser("trials", help="Track C: forecasting phase 3 trial results")
    tsub = t.add_subparsers(dest="trials_cmd", required=True)
    tf = tsub.add_parser("fetch", help="download registry records from ClinicalTrials.gov (needs internet)")
    tf.add_argument("--ids", required=True, help="text file with NCT IDs")
    tf.add_argument("--out", required=True)
    tbp = tsub.add_parser("build", help="question packets and key from registry records and result labels")
    tbp.add_argument("--registry", required=True, help="directory of <NCT id>.json records")
    tbp.add_argument("--labels", nargs="+", required=True, help="label .jsonl files; later files override earlier")
    tbp.add_argument("--out", required=True)
    tbp.add_argument("--cutoff", default="2026-06-30", help="results first public after this date are post-cutoff")
    tbp.add_argument("--snapshot-date", help="date shown in packets (default: each record's fetch date)")
    tbp.add_argument("--exclude", help="text file of trials to leave out, one 'NCT... reason' per line")
    tbl = tsub.add_parser("baselines", help="B0 and B1, fitted on pre-cutoff trials")
    tbl.add_argument("--build", required=True)
    tsc = tsub.add_parser("score", help="score Track C forecasts")
    tsc.add_argument("--build", required=True)
    tsc.add_argument("--pred", required=True)
    tsc.add_argument("--ref", help="reference forecasts for the Brier skill score (e.g. predictions/c_b0.jsonl)")
    tsc.add_argument("--cutoff", help="the forecaster's knowledge cutoff: score only results first public after it")
    tsc.add_argument("--sets", default="post_cutoff", help="comma-separated: post_cutoff, pre_cutoff")
    tsc.add_argument("--n-boot", type=int, default=0)
    tsc.add_argument("--out")
    trd = tsub.add_parser("round", help="live forecasting rounds: publish open trials, check and register entries, leaderboard")
    rsub = trd.add_subparsers(dest="round_cmd", required=True)
    rex = rsub.add_parser("export", help="write a round from the open trials of a build (public data only)")
    rex.add_argument("--build", required=True)
    rex.add_argument("--out", required=True)
    rex.add_argument("--round", required=True, help="round id, e.g. 2026-r1")
    rex.add_argument("--closes", required=True, help="last day to submit (YYYY-MM-DD); scored on results after it")
    rex.add_argument("--opens", help="opening day (YYYY-MM-DD)")
    rex.add_argument("--cards", help="question cards (JSONL, one per trial): adds the number questions")
    rex.add_argument("--deadline", help="last day a result counts (YYYY-MM-DD); later results and silent trials are dropped")
    rex.add_argument("--operations", help="launch-day rows of the operations questions (JSONL, one per trial)")
    rex.add_argument("--ops-read", help="day the operations questions are read from the registry (YYYY-MM-DD)")
    rex.add_argument("--final-deadline", help="last day a result counts in the final scoring pass (YYYY-MM-DD)")
    rex.add_argument("--early-deadline", help="last day a result counts in the early scoring pass (YYYY-MM-DD)")
    rex.add_argument("--sisters", help="sister-trial groups (JSON from make_sisters.py), resampled together")
    rex.add_argument("--instructions", help="the round's forecast instructions (the Models board's prompt)")
    rva = rsub.add_parser("validate", help="check a submission, or a sealed one (metadata and SHA-256 only)")
    rva.add_argument("--round-dir", required=True)
    rva.add_argument("--forecasts", help="forecasts.jsonl")
    rva.add_argument("--meta", help="meta.json")
    rva.add_argument("--sha256-file", help="forecasts.sha256 of a sealed submission (instead of --forecasts)")
    rre = rsub.add_parser("register", help="add a checked entry, with the date it was received")
    rre.add_argument("--round-dir", required=True)
    rre.add_argument("--id", required=True)
    rre.add_argument("--forecasts", required=True)
    rre.add_argument("--meta", required=True)
    rre.add_argument("--received", required=True, help="UTC date the organiser received it (YYYY-MM-DD)")
    rre.add_argument("--kind", choices=["entry", "reference", "first_upload"], default="entry")
    rre.add_argument("--of", help="for --kind first_upload: the id of the entry it is the first upload of")
    rre.add_argument("--expect-sha256-file", help="the forecasts.sha256 the entrant posted beforehand; must match")
    rlb = rsub.add_parser("leaderboard", help="score all entries on trials that reported after the close")
    rlb.add_argument("--build", required=True, help="a Track C build with the latest labels")
    rlb.add_argument("--round-dir", required=True)
    rlb.add_argument("--n-boot", type=int, default=2000)
    rlb.add_argument("--min-scored", type=int, default=100, help="rank entries once this many trials are scored")
    rlb.add_argument("--pass", choices=["early", "first", "final"], default="first",
                     help="early: results up to the early deadline; first (ranked): up to the deadline; final: up to "
                          "the final deadline")
    rlb.add_argument("--numbers-ref", default="ref-opus-5-5", help="reference entry whose range widths scale the number scores")
    rlb.add_argument("--ops-outcomes", help="outcomes of the operations questions (from ops-resolve)")
    rlb.add_argument("--labels-as-of", help="day the labels are as of; the pass's p_public is scored once it is "
                     "after that pass's deadline")
    rlb.add_argument("--next-step-outcomes", help="JSONL {nct_id, next_step: 1/0/null}, after the final deadline")
    rlb.add_argument("--amend-outcomes", help="JSONL {nct_id, amended: 1/0/null}, after the operations read date")
    rlb.add_argument("--assumption-checks", help="JSONL {entry, n_checked, n_supported, ...}, after the close")
    rlb.add_argument("--out")
    ror = rsub.add_parser("ops-resolve", help="outcomes of the operations questions from records fetched on the read date")
    ror.add_argument("--round-dir", required=True)
    ror.add_argument("--records", required=True, help="records fetched on the read date (JSONL)")
    ror.add_argument("--read-date", help="default: the round's operations read date")
    ror.add_argument("--out", required=True)
    t.set_defaults(func=cmd_trials)

    fa = sub.add_parser("facts", help="Track D: trial facts and saying 'I don't know'")
    fsub = fa.add_subparsers(dest="facts_cmd", required=True)
    fb = fsub.add_parser("build", help="questions from a Track C build plus made-up trials")
    fb.add_argument("--trials", required=True, help="a Track C build directory (with private/key_C.json)")
    fb.add_argument("--phantoms", help="JSON list of made-up trials (default: the packaged list)")
    fb.add_argument("--out", required=True)
    fb.add_argument("--salt", default="tdcb-facts")
    fs = fsub.add_parser("score", help="score Track D answers")
    fs.add_argument("--build", required=True)
    fs.add_argument("--pred", required=True)
    fs.add_argument("--cutoff", default="2026-06-30", help="the model's knowledge cutoff (YYYY-MM-DD)")
    fs.add_argument("--n-boot", type=int, default=0)
    fs.add_argument("--out")
    fa.set_defaults(func=cmd_facts)

    pa = sub.add_parser("patient", help="Tracks E and F: missing tests, and asking before answering")
    psub = pa.add_subparsers(dest="patient_cmd", required=True)
    pb = psub.add_parser("build", help="E and F packets from the Track A packets of a build")
    pb.add_argument("--build", required=True)
    pb.add_argument("--split", default="dev", choices=["dev", "test"])
    pb.add_argument("--n-per-type-e", type=int, default=40)
    pb.add_argument("--n-per-type-f", type=int, default=40)
    pb.add_argument("--seed", type=int, default=1)
    pb.add_argument("--rules", help="biomarker rules JSON (default: the packaged draft)")
    pb.add_argument("--with-reports", action="store_true",
                    help="also write Track E2: the same E cases with the results inside reports (free-text answers)")
    for name in ("score-e", "score-e2", "score-f"):
        ps = psub.add_parser(name, help=f"score Track {name.split('-')[-1].upper()} answers")
        ps.add_argument("--build", required=True)
        ps.add_argument("--split", default="dev", choices=["dev", "test"])
        ps.add_argument("--pred", required=True)
        ps.add_argument("--rules")
        ps.add_argument("--n-boot", type=int, default=0)
        ps.add_argument("--out")
    pa.set_defaults(func=cmd_patient)

    sy = sub.add_parser("synth", help="write a synthetic study in MSK-CHORD format (for tests)")
    sy.add_argument("--out", required=True)
    sy.add_argument("--n", type=int, default=600)
    sy.add_argument("--seed", type=int, default=1)
    sy.set_defaults(func=cmd_synth)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    sys.exit(main())
