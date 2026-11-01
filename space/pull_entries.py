"""Organiser, once, after the round has closed: register the latest valid upload of every entry from the submission
datasets into the round directory, ready for the leaderboard, and the first upload of every entry uploaded more than
once (kind "first_upload", id "<entry>.first"), scored next to the last and never ranked.

usage: HF_TOKEN=... SUBMISSIONS_REPO=... REGISTRY_REPO=... python3 -I pull_entries.py <round dir> [--local <folder>]
       [--test]
Reads the public registry rows (one per accepted upload), keeps each entry's latest upload, and checks that the
private file has the SHA-256 the public row shows. An account's entries beyond MAX_ENTRIES (by first upload) are
listed and left out. Each entry is registered with the date of its last upload, which the Space's server set.
Refuses to run before the close (uploads may still come); --test runs it anyway, for a dry run on a copy of the
round. Running it again registers nothing new; an entry already registered with a different file stops it.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from tdcb.trials import round as tround  # noqa: E402
import submit as S  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("round_dir")
ap.add_argument("--local")
ap.add_argument("--test", action="store_true")
a = ap.parse_args()
man = json.load(open(os.path.join(a.round_dir, "manifest.json")))
today = dt.datetime.now(dt.timezone.utc).date().isoformat()
if today <= man["closes"] and not a.test:
    raise SystemExit(f"the round closes on {man['closes']}; pull the entries after the close (or --test on a copy)")
store = S.LocalStore(a.local) if a.local else S.HubStore(os.environ["HF_TOKEN"], os.environ["SUBMISSIONS_REPO"],
                                                         os.environ["REGISTRY_REPO"])
uploads = S.registry_uploads(store, man["round"])
first, first_row = {}, {}
for r in uploads:
    first.setdefault(r["id"], r["received_utc"])
    first_row.setdefault(r["id"], r)
owner = {r["id"]: r["hf_user"] for r in uploads}
by_user = {}
for eid, t in sorted(first.items(), key=lambda kv: kv[1]):
    by_user.setdefault(owner[eid], []).append(eid)
over = {e for ids in by_user.values() for e in ids[S.MAX_ENTRIES:]}
latest = S.latest_entries(store, man["round"])
reg = {e["id"]: e for e in json.load(open(os.path.join(a.round_dir, "registry.json")))}
left_out = []


def _register(eid, r, **kw):
    data = store.read("private", r["private_path"] + "/forecasts.jsonl")
    if hashlib.sha256(data).hexdigest() != r["sha256"]:
        raise SystemExit(f"{eid}: the private file does not match the SHA-256 in the public registry")
    meta = json.loads(store.read("private", r["private_path"] + "/meta.json"))
    with tempfile.TemporaryDirectory() as tmp:
        fp, mp = os.path.join(tmp, "forecasts.jsonl"), os.path.join(tmp, "meta.json")
        open(fp, "wb").write(data)
        json.dump({k: v for k, v in meta.items() if k not in ("received_utc", "sha256", "round")}, open(mp, "w"))
        return tround.register(a.round_dir, eid, fp, mp, r["received_utc"][:10], expect_sha256=r["sha256"], **kw)


for eid, r in sorted(latest.items()):
    if eid in over:
        print("left out (more than", S.MAX_ENTRIES, "entries on the account):", eid)
        left_out.append({"id": eid, "hf_user": r["hf_user"], "reason": f"more than {S.MAX_ENTRIES} entries on the account"})
        continue
    if eid in reg:
        if reg[eid]["sha256"] != r["sha256"]:
            raise SystemExit(f"{eid} is registered with another file ({reg[eid]['sha256'][:12]})")
        print("already registered:", eid)
        continue
    e = _register(eid, r)
    print("registered:", eid, e["sha256"][:12], "uploads:", r["version"])
    f = first_row[eid]
    if r["version"] > 1 and f["sha256"] != r["sha256"]:          # the first upload, scored next to the last
        _register(eid + ".first", f, kind="first_upload", of=eid)
        print("registered its first upload:", eid + ".first", f["sha256"][:12])
json.dump(left_out, open(os.path.join(a.round_dir, "left_out_entries.json"), "w"), indent=1)   # publish with the entries
