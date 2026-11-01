"""Round 1 (rebuilt): the fingerprints to post somewhere the organiser cannot rewrite, before the round opens and
again at the close (a GitHub release or gist, a social-media post, an e-mail to a few outside people).

usage: python3 -I anchor.py <round dir> [--registry-dir <public registry folder>]
Prints one short block of text: the round's manifest SHA-256 (which itself holds the SHA-256 of every packet, the
cards, the operations rows and the sister groups), the SHA-256 of the three labelling instructions (results,
amendments, next step), the SHA-256 of the registry (the list of entries) and of every
registered entry's forecasts and metadata (the reference entries before opening), and, with --registry-dir (a local copy of the public registry/ folder), one SHA-256 over every
upload row received so far. Anyone holding the round files can recompute all of them.
"""
import argparse
import hashlib
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("round_dir")
ap.add_argument("--registry-dir")
a = ap.parse_args()


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


man = json.load(open(os.path.join(a.round_dir, "manifest.json")))
lines = [f"ReadoutBench {man['round']}: opens {man.get('opens')}, closes {man['closes']} 23:59:59 UTC (00:59:59 CET the next day), "
         f"{man['n_trials']} trials",
         f"manifest.json SHA-256 {sha(os.path.join(a.round_dir, 'manifest.json'))}",
         f"registry.json SHA-256 {sha(os.path.join(a.round_dir, 'registry.json'))}"]
here = os.path.dirname(os.path.abspath(__file__))          # the labelling instructions, fixed before the round opens
for doc in ("label_instructions_r1.md", "amend_label_instructions.md", "next_step_label_instructions.md"):
    lines.append(f"{doc} SHA-256 {sha(os.path.join(here, doc))}")
for e in json.load(open(os.path.join(a.round_dir, "registry.json"))):
    lines.append(f"{e['kind']} {e['id']} received {e['received']} SHA-256 {e['sha256']}"
                 + (f" meta {e['meta_sha256']}" if e.get("meta_sha256") else ""))
if a.registry_dir:
    rows = []
    for d, _, files in os.walk(a.registry_dir):
        rows += [os.path.join(d, f) for f in files if f.endswith(".json")]
    h = hashlib.sha256()
    for p in sorted(rows, key=lambda p: os.path.relpath(p, a.registry_dir)):
        h.update(os.path.relpath(p, a.registry_dir).replace(os.sep, "/").encode() + b"\n")
        h.update(open(p, "rb").read())
    lines.append(f"public registry: {len(rows)} uploads, SHA-256 {h.hexdigest()}")
print("\n".join(lines))
