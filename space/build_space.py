"""Assemble the two folders to upload to Hugging Face from the repo and a staged round.

usage: python3 -I build_space.py <staged round dir> <out dir> [--rules <the rules file>] [--baselines-dir <dir>]
                                  [--baselines-data <dir>] [--expect-registry-sha <SHA-256 posted by anchor.py>]
(the rules file is docs/round1-rules-draft.md in the repository, 1_design/01_round1_rules_draft.md in the review
package; --baselines-dir holds make_baselines.py, pilot/round1_rebuild in both; --baselines-data holds the
baselines_* files, <baselines-dir>/data in the repository, 3_round1 in the review package)
Writes <out dir>/space (the Space: app, submission logic, the tdcb package, the round's manifest, cards and
operations rows) and <out dir>/dataset (the public dataset: the round files entrants download, the sister-trial
groups, the round's forecast instructions, the list of reference entries with their SHA-256s, the two baselines'
forecasts, training table and script, the rules as its README, the template, and the registry folder the
submission page writes to). Stops before writing anything if a file the dataset needs is missing, if a file does
not match its fingerprint (the manifest's, the registry's, or the SHA-256s of the files B0 and B1 were fitted from,
which must be exactly the baselines' published files), or, with --expect-registry-sha, if the registry is not the one
whose fingerprint was posted outside the page: a coordinated edit of an entry and the registry is caught only there.
"""
import argparse
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ap = argparse.ArgumentParser()
ap.add_argument("round_dir")
ap.add_argument("out")
ap.add_argument("--rules", default=os.path.join(REPO, "docs", "round1-rules-draft.md"))
ap.add_argument("--baselines-dir", default=os.path.join(REPO, "pilot", "round1_rebuild"))
ap.add_argument("--baselines-data")
ap.add_argument("--expect-registry-sha", help="the registry's SHA-256 as posted outside the page (anchor.py)")
a = ap.parse_args()
a.baselines_data = a.baselines_data or os.path.join(a.baselines_dir, "data")
if not os.path.exists(a.rules):                    # before anything is written
    raise SystemExit(f"rules file not found: {a.rules} (pass --rules, e.g. the review package's "
                     "1_design/01_round1_rules_draft.md)")
BASELINE_FILES = [os.path.join(a.baselines_dir, "make_baselines.py")] + [
    os.path.join(a.baselines_data, f) for f in ("baselines_training.jsonl", "baselines_round_features.jsonl",
                                                 "baselines_info.json", "baselines_label_audit.jsonl",
                                                 "baselines_relabel_check_a.jsonl", "baselines_relabel_check_b.jsonl")]
PUBLIC_REFS = ("ref-b0", "ref-b1")
need = BASELINE_FILES + [os.path.join(a.round_dir, f) for f in ("manifest.json", "cards.jsonl", "operations.jsonl",
                                                                 "questions.jsonl", "sisters.json", "registry.json",
                                                                 "forecast_instructions.md")]
need += [os.path.join(a.round_dir, "entries", r, f) for r in PUBLIC_REFS for f in ("forecasts.jsonl", "meta.json")]
TEMPLATE = os.path.join(REPO, "pilot", "round1_rebuild", "template")
need += [os.path.join(HERE, f) for f in ("app.py", "submit.py", "upload_fingerprint.py", "requirements.txt", "SPACE_README.md")]
need += [os.path.join(REPO, "tdcb", f) for f in ("__init__.py", "metrics.py")] + [os.path.join(REPO, "tdcb", "trials")]
need += [os.path.join(TEMPLATE, f) for f in ("forecasts.example.jsonl", "meta.example.json",
                                              "meta.models_board.example.json")]
missing = [p for p in need if not os.path.exists(p)]
import json  # noqa: E402
man = json.load(open(os.path.join(a.round_dir, "manifest.json"))) if os.path.exists(
    os.path.join(a.round_dir, "manifest.json")) else {}
packets = os.path.join(a.round_dir, "packets")
n_packets = len([f for f in os.listdir(packets) if f.endswith(".md")]) if os.path.isdir(packets) else 0
import hashlib  # noqa: E402


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# every file the manifest fingerprints must still match it: what is published is what was fingerprinted
for f, k in (("questions.jsonl", "questions_sha256"), ("cards.jsonl", "cards_sha256"),
             ("operations.jsonl", "operations_sha256"), ("sisters.json", "sisters_sha256"),
             ("forecast_instructions.md", "instructions_sha256")):
    fp = os.path.join(a.round_dir, f)
    if man.get(k) and os.path.exists(fp) and _sha(fp) != man[k]:
        missing.append(f"{fp}: SHA-256 does not match the manifest ({k})")
for nid, h in (man.get("packets_sha256") or {}).items():
    fp = os.path.join(packets, nid + ".md")
    if os.path.exists(fp) and _sha(fp) != h:
        missing.append(f"{fp}: SHA-256 does not match the manifest")
if man:                                  # exactly the manifest's packets: one per trial, none missing, none extra
    have = {f[:-3] for f in os.listdir(packets) if f.endswith(".md")} if os.path.isdir(packets) else set()
    listed, trials = set(man.get("packets_sha256") or {}), set(man.get("trials") or [])
    if listed != trials:
        missing.append("manifest.json: packets_sha256 does not list exactly the round's trials")
    for nid in sorted(have ^ listed)[:10]:
        missing.append(f"{packets}/{nid}.md: " + ("not in the manifest" if nid in have else "missing"))
# every registered entry's files must still have the SHA-256s the registry gives (the published references.json,
# whose own SHA-256 anchor.py posts outside the page); exactly the registered entries, with B0 and B1 among them
reg_path = os.path.join(a.round_dir, "registry.json")
reg = json.load(open(reg_path)) if os.path.exists(reg_path) else []
for e in reg:
    fp = os.path.join(a.round_dir, e["forecasts"])
    if not os.path.exists(fp) or _sha(fp) != e["sha256"]:
        missing.append(f"{fp}: missing or SHA-256 does not match the registry ({e['id']})")
    mp = os.path.join(a.round_dir, e["meta"])
    if not e.get("meta_sha256") or not os.path.exists(mp) or _sha(mp) != e["meta_sha256"]:
        missing.append(f"{mp}: missing, or no or another meta SHA-256 in the registry ({e['id']})")
ent = os.path.join(a.round_dir, "entries")
extra = sorted(set(os.listdir(ent)) - {e["id"] for e in reg}) if os.path.isdir(ent) else []
missing += [f"{ent}/{d}: not in the registry" for d in extra]
missing += [f"registry.json: {r} is not registered" for r in PUBLIC_REFS if r not in {e["id"] for e in reg}]
if a.expect_registry_sha and os.path.exists(reg_path) and _sha(reg_path) != a.expect_registry_sha.strip().lower():
    missing.append(f"{reg_path}: SHA-256 {_sha(reg_path)} is not the posted one ({a.expect_registry_sha})")
# the files B0 and B1 were fitted from (script, training table, round features, info, label audit and re-checks) must
# be exactly the published baseline files, each with the SHA-256 the baselines' metadata records
by_name = {os.path.basename(p): p for p in BASELINE_FILES}
for r in PUBLIC_REFS:
    mp = os.path.join(a.round_dir, "entries", r, "meta.json")
    srcs = json.load(open(mp)).get("sources_sha256") if os.path.exists(mp) else None
    if not srcs:
        missing.append(f"{mp}: no sources_sha256 (refit the baselines with the current make_baselines.py)")
        continue
    if set(srcs) != set(by_name):
        missing.append(f"{mp}: sources_sha256 lists {sorted(srcs)}, not the published baseline files "
                       f"{sorted(by_name)} (refit with --corrections and --pin, as the README says)")
    for f, h in srcs.items():
        fp = by_name.get(f)
        if fp and os.path.exists(fp) and _sha(fp) != h:
            missing.append(f"{fp}: SHA-256 does not match the one {r} was fitted from")
if man and not man.get("instructions_sha256"):
    missing.append("manifest.json: no instructions_sha256 (stage the round with --instructions)")
if man and n_packets != len(man.get("trials", [])):
    missing.append(f"{packets}: {n_packets} packets for {len(man.get('trials', []))} trials")
if missing:
    raise SystemExit("missing or changed, nothing written:\n  " + "\n  ".join(missing) + "\n(stage the round with "
                     "--instructions, register B0 and B1, or pass --baselines-dir / --baselines-data)")
sp, ds = os.path.join(a.out, "space"), os.path.join(a.out, "dataset")
for d in (sp, ds):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
for f in ("app.py", "submit.py", "upload_fingerprint.py", "requirements.txt"):
    shutil.copy(os.path.join(HERE, f), sp)
shutil.copy(os.path.join(HERE, "SPACE_README.md"), os.path.join(sp, "README.md"))
os.makedirs(os.path.join(sp, "tdcb"))        # only what the checker needs: no other track's code
for f in ("__init__.py", "metrics.py"):
    shutil.copy(os.path.join(REPO, "tdcb", f), os.path.join(sp, "tdcb", f))
shutil.copytree(os.path.join(REPO, "tdcb", "trials"), os.path.join(sp, "tdcb", "trials"),
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
os.makedirs(os.path.join(sp, "round"))
for f in ("manifest.json", "cards.jsonl", "operations.jsonl"):
    shutil.copy(os.path.join(a.round_dir, f), os.path.join(sp, "round", f))
for f in ("manifest.json", "cards.jsonl", "operations.jsonl", "questions.jsonl", "sisters.json", "registry.json",
          "forecast_instructions.md"):
    shutil.copy(os.path.join(a.round_dir, f), os.path.join(ds, f if f != "registry.json" else "references.json"))
# references.json lists the reference entries with their SHA-256s. The two baselines (B0, B1) are published in full
# from the opening day, as public bars to beat (anyone could refit them from the published training table anyway);
# the model reference entries stay private until the close, then go up with the entries.
os.makedirs(os.path.join(ds, "references"), exist_ok=True)
for rid in PUBLIC_REFS:
    shutil.copytree(os.path.join(a.round_dir, "entries", rid), os.path.join(ds, "references", rid))
for p in BASELINE_FILES:                         # anyone can refit B0 and B1 byte for byte from these
    shutil.copy(p, os.path.join(ds, "references", os.path.basename(p)))
shutil.copytree(os.path.join(a.round_dir, "packets"), os.path.join(ds, "packets"))
shutil.copytree(TEMPLATE, os.path.join(ds, "template"))
mb = os.path.join(ds, "template", "meta.models_board.example.json")      # the example carries the round's real SHA
ex = json.load(open(mb))
ex["prompt_sha256"] = man["instructions_sha256"]
json.dump(ex, open(mb, "w"), indent=1)
rules = open(a.rules, encoding="utf-8").read()
head = "---\nlicense: cc-by-4.0\npretty_name: ReadoutBench Round 1\n---\n\n"
open(os.path.join(ds, "README.md"), "w", encoding="utf-8").write(head + rules)
os.makedirs(os.path.join(ds, "registry"))
open(os.path.join(ds, "registry", "README.md"), "w").write(
    "One file per accepted upload: registry/<account>/<entry>/<time>.json, written by the submission page.\n")
print("space:", sum(len(f) for _, _, f in os.walk(sp)), "files; dataset:", sum(len(f) for _, _, f in os.walk(ds)), "files")
