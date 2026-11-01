"""ReadoutBench submission logic, kept apart from the web page so it can be tested.

A submission = a forecast file (JSONL) + the entry's metadata. It is checked with the round's own validator
(tdcb.trials.round.validate), then stored as new files only (nothing is ever rewritten, so two uploads at the same
moment cannot overwrite each other):
- privately (SUBMISSIONS_REPO, a private dataset): <round>/uploads/<account>/<entry>/<time>/forecasts.jsonl and
  meta.json, with the contact address;
- publicly (REGISTRY_REPO, a public dataset): registry/<account>/<entry>/<time>.json, one row per upload with the
  Hugging Face account, team, entry name, received time (UTC, set by the server), the SHA-256 of the file and the
  entry's description. The dataset's commit history time-stamps every upload.
An entry is identified by the uploading account's exact name and its entry name, so nobody can take another account's
entry. If simultaneous uploads take an account past MAX_ENTRIES, pull_entries.py keeps the first three entries and
lists the rest as left out, publicly, right after the close.
It may be uploaded again until the close; the last valid upload counts (the first is scored too, next to it, never
ranked). Each account may hold up to MAX_ENTRIES
entries. Without HF_TOKEN everything goes to a local folder (testing only): on a Hugging Face Space (SPACE_ID set)
a missing token closes the page instead.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import tempfile

from tdcb.trials import round as tround

ROUND_DIR = os.environ.get("ROUND_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "round"))
MAX_ENTRIES = int(os.environ.get("MAX_ENTRIES", "3"))
MAX_BYTES = 12 * 1024 * 1024        # a Models board entry with every field at its cap in a non-Latin script is ~7 MB
META_TEXT = ("team", "entry_name", "contact", "harness", "setting", "code_url", "model_version", "provider",
             "run_dates", "run_settings", "retrieval")
COUNT_KEYS = ("n_forecasts", "n_number_answers", "n_subgroup_answers", "n_safety_answers", "n_key_secondary_answers",
              "n_next_step_answers", "n_operations_answers", "n_p_public_answers", "n_p_public_mar_answers",
              "n_p_public_dec_answers", "n_p_amended_answers", "n_rationales", "n_assumptions")
METHOD_FLAGS = ("human_in_the_loop", "fine_tuned", "ensemble")      # the Open board: how the entry was made


USER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")


class Misconfigured(RuntimeError):
    pass


def manifest() -> dict:
    with open(os.path.join(ROUND_DIR, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:60] or "entry"


class LocalStore:
    """Files under a local folder (for testing without a Hugging Face token)."""

    def __init__(self, root: str):
        self.root = root

    def put(self, which: str, path: str, data: bytes):
        p = os.path.join(self.root, which, path)
        if os.path.exists(p):
            raise FileExistsError(p)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)

    def list(self, which: str, prefix: str) -> list[str]:
        base = os.path.join(self.root, which)
        out = []
        for d, _, files in os.walk(os.path.join(base, prefix)):
            out += [os.path.relpath(os.path.join(d, f), base).replace(os.sep, "/") for f in files]
        return sorted(out)

    def read(self, which: str, path: str) -> bytes:
        with open(os.path.join(self.root, which, path), "rb") as fh:
            return fh.read()

    def put_many(self, which: str, files: dict):
        for path, data in files.items():
            self.put(which, path, data)


class HubStore:
    """Two datasets on the Hugging Face Hub: a private one for the files, a public one for the registry."""

    def __init__(self, token: str, private_repo: str, public_repo: str):
        from huggingface_hub import HfApi
        self.api, self.token = HfApi(token=token), token
        self.repo = {"private": private_repo, "public": public_repo}
        self._cache = {}        # registry rows never change once written (each path is a new timestamp): read once

    def put_many(self, which: str, files: dict):
        """Several files in one commit, so an upload is stored whole or not at all."""
        from huggingface_hub import CommitOperationAdd
        self.api.create_commit(repo_id=self.repo[which], repo_type="dataset",
                               operations=[CommitOperationAdd(path_in_repo=p, path_or_fileobj=io.BytesIO(d))
                                           for p, d in files.items()],
                               commit_message=f"add {len(files)} file(s) under {os.path.dirname(next(iter(files)))}")

    def put(self, which: str, path: str, data: bytes):
        self.api.upload_file(path_or_fileobj=io.BytesIO(data), path_in_repo=path, repo_id=self.repo[which],
                             repo_type="dataset", commit_message=f"add {path}")

    def list(self, which: str, prefix: str) -> list[str]:
        files = self.api.list_repo_files(self.repo[which], repo_type="dataset")
        return sorted(f for f in files if f.startswith(prefix))

    def read(self, which: str, path: str) -> bytes:
        if (which, path) in self._cache:
            return self._cache[(which, path)]
        from huggingface_hub import hf_hub_download
        with open(hf_hub_download(self.repo[which], path, repo_type="dataset", token=self.token,
                                  force_download=True), "rb") as fh:
            data = fh.read()
        if which == "public" and path.startswith("registry/"):
            self._cache[(which, path)] = data
        return data


def make_store():
    token = os.environ.get("HF_TOKEN")
    if token:
        return HubStore(token, os.environ["SUBMISSIONS_REPO"], os.environ["REGISTRY_REPO"])
    if os.environ.get("SPACE_ID"):
        raise Misconfigured("HF_TOKEN is not set on this Space; submissions are closed until it is.")
    return LocalStore(os.environ.get("LOCAL_STORE", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                 "_local_store")))


def build_meta(form: dict) -> dict:
    models = form.get("models") or []
    if isinstance(models, str):
        models = [m.strip() for m in models.split(",") if m.strip()]
    meta = {k: (str(form.get(k) or "").strip()) for k in META_TEXT}
    meta["models"] = models
    meta["web_access"] = bool(form.get("web_access"))
    try:
        meta["cost_usd_per_trial"] = float(form.get("cost_usd_per_trial"))
    except (TypeError, ValueError):
        meta["cost_usd_per_trial"] = None
    for k in ("code_url", "model_version", "provider", "run_dates", "run_settings", "retrieval"):
        if not meta[k]:
            meta.pop(k)
    if meta.get("setting") == "open":           # how the entry was made, required on the Open board
        for k in METHOD_FLAGS:
            meta[k] = bool(form.get(k))
    else:
        meta.pop("retrieval", None)
    # the Models board uses the round's instructions unchanged; the entrant confirms it, the page fills in their SHA-256
    if meta.get("setting") == "closed" and form.get("same_prompt"):
        meta["prompt_sha256"] = manifest().get("instructions_sha256") or ""
    return meta


def registry_uploads(store, round_id: str | None = None) -> list[dict]:
    """Every public registry row (one per accepted upload), oldest first."""
    rows = [json.loads(store.read("public", p)) for p in store.list("public", "registry/") if p.endswith(".json")]
    if round_id:
        rows = [r for r in rows if r.get("round") == round_id]
    return sorted(rows, key=lambda r: (r["received_utc"], r["id"]))


def latest_entries(store, round_id: str | None = None) -> dict:
    """{entry id: its latest upload row}, with `version` = how many uploads the entry has."""
    out = {}
    for r in registry_uploads(store, round_id):
        r = dict(r, version=(out.get(r["id"], {}).get("version", 0) + 1))
        out[r["id"]] = r
    return out


def submit(forecasts_path: str, form: dict, hf_user: str | None, store, now: _dt.datetime | None = None) -> dict:
    """Check and store one submission. Returns {"ok", "message", "errors", "warnings", "entry"}."""
    now = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(_dt.timezone.utc)   # dates are judged in UTC
    man = manifest()
    fail = lambda msg, errors=(): {"ok": False, "message": msg, "errors": list(errors), "warnings": [], "entry": None}  # noqa: E731
    if store is None:
        return fail("Submissions are closed: this page is not configured. Please tell the organiser.")
    if not hf_user:
        return fail("Sign in with Hugging Face first.")
    today = now.date().isoformat()
    if man.get("opens") and today < man["opens"]:
        return fail(f"The round opens on {man['opens']}.")
    if today > man["closes"]:
        return fail(f"The round closed on {man['closes']} (at the end of that day, UTC).")
    if not forecasts_path or not os.path.exists(forecasts_path):
        return fail("Attach your forecasts.jsonl.")
    if os.path.getsize(forecasts_path) > MAX_BYTES:
        return fail(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB; a full entry with every field filled is a few MB.")
    if not form.get("agree"):
        return fail("Please confirm the fair-play rules.")
    meta = build_meta(form)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(meta, fh)
        meta_path = fh.name
    try:
        v = tround.validate(ROUND_DIR, forecasts_path, meta_path)
    finally:
        os.unlink(meta_path)
    if not v["ok"]:
        return {"ok": False, "message": f"The file did not pass the checks ({len(v['errors'])} problems). Nothing was "
                "stored.", "errors": v["errors"][:25], "warnings": v["warnings"][:10], "entry": None}
    if not USER_RE.fullmatch(hf_user):
        return fail("This account name cannot be used for an entry; please tell the organiser.")
    user = hf_user                           # the exact account name, so two accounts never share an entry id
    entry = slug(meta["entry_name"])
    entry_id = f"{user}--{entry}"
    mine = {r["id"] for r in registry_uploads(store, man["round"]) if r["hf_user"] == hf_user}
    if entry_id not in mine and len(mine) >= MAX_ENTRIES:
        return fail(f"Each account may hold up to {MAX_ENTRIES} entries. To replace one, upload it again under the "
                    "same entry name.")
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    received = now.isoformat(timespec="microseconds")
    base = f"{man['round']}/uploads/{user}/{entry}/{stamp}"
    private_meta = dict(meta, hf_user=hf_user, received_utc=received, sha256=v["sha256"], round=man["round"])
    row = {"id": entry_id, "round": man["round"], "hf_user": hf_user, "team": meta["team"],
           "entry_name": meta["entry_name"], "received_utc": received, "sha256": v["sha256"],
           "setting": meta["setting"], "board": tround.board(meta), "web_access": meta["web_access"],
           "models": meta["models"], "model_version": meta.get("model_version"),
           "cost_usd_per_trial": meta["cost_usd_per_trial"], "private_path": base,
           **{k: meta[k] for k in ("retrieval",) + METHOD_FLAGS if k in meta},
           **{k: v[k] for k in COUNT_KEYS if k in v}}
    try:          # the private files in one commit, then the public row; an upload counts only once its row exists
        store.put_many("private", {f"{base}/forecasts.jsonl": open(forecasts_path, "rb").read(),
                                   f"{base}/meta.json": json.dumps(private_meta, indent=1).encode("utf-8")})
        store.put_many("public", {f"registry/{user}/{entry}/{stamp}.json": json.dumps(row, indent=1).encode("utf-8")})
    except Exception as e:  # noqa: BLE001 - any storage failure: say plainly that nothing was recorded
        return fail(f"Your upload was not recorded (a storage error: {type(e).__name__}). Nothing counts until you see "
                    "'Received'; please try again in a minute, and tell the organiser if it keeps failing.")
    version = latest_entries(store, man["round"]).get(entry_id, {}).get("version", 1)
    msg = (f"Received: {meta['team']} / {meta['entry_name']} (account {hf_user}), version {version}, at {received} "
           f"UTC. SHA-256 of your file: {v['sha256']}. Your forecasts stay private until the round closes.")
    return {"ok": True, "message": msg, "errors": [], "warnings": v["warnings"][:10], "entry": dict(row, version=version)}


COLUMNS = {"team": "Team", "entry_name": "Entry", "hf_user": "Account", "received_utc": "Last upload (UTC)",  # shown on the leaderboard too
           "version": "Uploads", "board": "Board", "web_access": "Web", "cost_usd_per_trial": "$/trial",
           "sha256": "SHA-256"}


def registry_rows(store):
    """The public list of entries, as a table (latest upload of each, newest first)."""
    import pandas as pd
    if store is None:
        return pd.DataFrame([], columns=list(COLUMNS.values()))
    rows = sorted(latest_entries(store, manifest()["round"]).values(), key=lambda r: r["received_utc"], reverse=True)
    return pd.DataFrame([[r.get(k) for k in COLUMNS] for r in rows], columns=list(COLUMNS.values()))
