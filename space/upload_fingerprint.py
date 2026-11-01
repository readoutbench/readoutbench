"""Organiser, every week while the round is open and once at the close: a fingerprint of the list of uploads, to post
outside the submission page (in the same public place as the round's fingerprints).

usage (from the Space folder, which holds this script, submit.py and the tdcb package beside each other; from the repo's space/ folder the parent folder, which holds tdcb, is put on the path too):
  HF_TOKEN=... SUBMISSIONS_REPO=... REGISTRY_REPO=... python3 -I upload_fingerprint.py <round id> [--local <folder>]
Reads the public registry rows (one per accepted upload, oldest first) and prints one line per upload, "received_utc
id sha256", then the SHA-256 of those lines and their count. Anyone can recompute it from the public registry rows; a
later change to an upload's file, or an upload slipped in after a posted fingerprint, then shows. Standard library
plus the Space's own submit.py.
"""
import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if not os.path.isdir(os.path.join(HERE, "tdcb")):       # run from the repo's space/ folder: tdcb is one level up
    sys.path.insert(1, os.path.dirname(HERE))
import submit as S  # noqa: E402


def lines_of(rows):
    return [f"{r['received_utc']} {r['id']} {r['sha256']}" for r in rows]


def fingerprint(rows):
    body = "".join(x + "\n" for x in lines_of(rows))
    return hashlib.sha256(body.encode("utf-8")).hexdigest(), len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("round_id")
    ap.add_argument("--local")
    a = ap.parse_args()
    store = S.LocalStore(a.local) if a.local else S.HubStore(os.environ["HF_TOKEN"], os.environ["SUBMISSIONS_REPO"],
                                                             os.environ["REGISTRY_REPO"])
    rows = S.registry_uploads(store, a.round_id)
    for x in lines_of(rows):
        print(x)
    sha, n = fingerprint(rows)
    print(f"uploads {n}  SHA-256 {sha}")
