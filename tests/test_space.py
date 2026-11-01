"""The submission page's storage logic (space/submit.py) with a local store."""
import datetime as dt
import importlib
import json
import os
import subprocess
import sys

import pytest

from test_round_cards import CARDS, _fc
from test_round import META, _build, _jsonl
from tdcb.trials import round as tround

HERE = os.path.dirname(os.path.abspath(__file__))
SPACE = os.path.join(os.path.dirname(HERE), "space")


@pytest.fixture
def S(tmp_path, monkeypatch):
    from test_round_cards import IDS
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in IDS]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    (tmp_path / "fi.md").write_text("# Task: forecast\n")
    tround.export(str(b), str(r), "t-r1", closes="2026-12-10", opens="2026-11-01",
                  cards=_jsonl(tmp_path / "c.jsonl", CARDS), deadline="2027-06-30", instructions=str(tmp_path / "fi.md"))
    monkeypatch.setenv("ROUND_DIR", str(r))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("SPACE_ID", raising=False)
    monkeypatch.setenv("LOCAL_STORE", str(tmp_path / "store"))
    sys.path.insert(0, SPACE)
    mod = importlib.reload(importlib.import_module("submit"))
    mod._tmp, mod._round = tmp_path, r
    return mod


FORM = dict(META, agree=True, models="m1, m2", code_url="")
NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.timezone.utc)


def _file(S, name="f.jsonl", rationale=False):
    rows = _fc([0.5, 0.5, 0.5, 0.5])
    if rationale:                          # the Models board's instructions ask a rationale for every trial
        rows = [dict(o, rationale="An earlier trial of the class worked.") for o in rows]
    return _jsonl(S._tmp / name, rows)


def test_reupload_namespaced_and_capped(S):
    store = S.make_store()
    a = S.submit(_file(S), FORM, "alice", store, NOW)
    assert a["ok"] and a["entry"]["id"] == "alice--" + S.slug(META["entry_name"]) and a["entry"]["version"] == 1
    assert a["entry"]["retrieval"] == "web search" and a["entry"]["ensemble"] is False     # the Open board's method
    no_method = S.submit(_file(S), dict(FORM, retrieval=""), "alice", store, NOW)
    assert not no_method["ok"] and any("retrieval is needed" in e for e in no_method["errors"])
    b = S.submit(_file(S), FORM, "alice", store, NOW + dt.timedelta(minutes=1))
    assert b["ok"] and b["entry"]["version"] == 2
    c = S.submit(_file(S), FORM, "bob", store, NOW + dt.timedelta(minutes=2))   # same entry name, other account
    assert c["ok"] and c["entry"]["id"].startswith("bob--")
    for i in range(2):
        assert S.submit(_file(S), dict(FORM, entry_name=f"other {i}"), "alice", store, NOW)["ok"]
    over = S.submit(_file(S), dict(FORM, entry_name="fourth"), "alice", store, NOW)
    assert not over["ok"] and "up to 3" in over["message"]
    latest = S.latest_entries(store)
    assert len(latest) == 4 and latest[a["entry"]["id"]]["version"] == 2
    t = S.registry_rows(store)
    assert "Account" in t.columns and len(t) == 4


def test_closed_dates_size_and_misconfigured(S, monkeypatch):
    store = S.make_store()
    assert "opens" in S.submit(_file(S), FORM, "a", store, dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc))["message"]
    assert "closed" in S.submit(_file(S), FORM, "a", store, dt.datetime(2026, 12, 11, 0, 1, tzinfo=dt.timezone.utc))["message"]
    assert S.submit(_file(S), FORM, "a", store, dt.datetime(2026, 12, 10, 23, 59, tzinfo=dt.timezone.utc))["ok"]
    big = S._tmp / "big.jsonl"
    big.write_bytes(b" " * (S.MAX_BYTES + 1))
    assert "larger" in S.submit(str(big), FORM, "a", store, NOW)["message"]
    assert not S.submit(_file(S), FORM, "a", None, NOW)["ok"]
    monkeypatch.setenv("SPACE_ID", "user/space")
    with pytest.raises(S.Misconfigured):
        S.make_store()


def test_pull_entries_registers_latest_once(S):
    store = S.make_store()
    S.submit(_file(S, "v1.jsonl"), FORM, "alice", store, NOW)
    rows = _fc([0.9, 0.1, 0.9, 0.1])
    v2 = _jsonl(S._tmp / "v2.jsonl", rows)
    S.submit(v2, FORM, "alice", store, NOW + dt.timedelta(days=1))
    cmd = [sys.executable, os.path.join(SPACE, "pull_entries.py"), str(S._round), "--local", str(S._tmp / "store")]
    env = dict(os.environ, PYTHONPATH=os.path.dirname(HERE))
    assert subprocess.run(cmd, env=env, capture_output=True).returncode != 0          # before the close: refused
    out = subprocess.run(cmd + ["--test"], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    reg = {e["id"]: e for e in json.load(open(S._round / "registry.json"))}
    eid = "alice--" + S.slug(META["entry_name"])
    assert set(reg) == {eid, eid + ".first"} and reg[eid]["received"] == "2026-11-21"
    assert reg[eid]["sha256"] == tround.validate(str(S._round), v2)["sha256"] and reg[eid]["kind"] == "entry"
    assert reg[eid + ".first"]["kind"] == "first_upload" and reg[eid + ".first"]["of"] == eid
    assert reg[eid + ".first"]["received"] == "2026-11-20"
    again = subprocess.run(cmd + ["--test"], env=env, capture_output=True, text=True)
    assert again.returncode == 0 and "already registered" in again.stdout


def test_models_board_form(S):
    store = S.make_store()
    form = dict(FORM, setting="closed", web_access=False, models="model-x", model_version="model-x-2026-09-01",
                provider="Example AI", entry_name="bare model")
    no = S.submit(_file(S, rationale=True), dict(form, same_prompt=False), "carol", store, NOW)
    assert not no["ok"] and any("prompt_sha256" in e for e in no["errors"])
    bare = S.submit(_file(S), dict(form, same_prompt=True), "carol", store, NOW)
    assert not bare["ok"] and any("rationale" in e for e in bare["errors"])
    yes = S.submit(_file(S, rationale=True), dict(form, same_prompt=True), "carol", store, NOW)
    assert yes["ok"] and yes["entry"]["board"] == "models" and "retrieval" not in yes["entry"]
    two = S.submit(_file(S, rationale=True), dict(form, same_prompt=True, models="a, b", entry_name="two"), "carol",
                   store, NOW)
    assert not two["ok"]
    assert S.registry_rows(store)["Board"].tolist() == ["models"]


def test_build_space_checks_before_writing(S, tmp_path):
    import hashlib
    import shutil
    repo = os.path.dirname(HERE)            # the repository, or 4_code in the review package (data in 3_round1)
    data0 = os.path.join(repo, "pilot", "round1_rebuild", "data")
    data0 = data0 if os.path.isdir(data0) else os.path.join(os.path.dirname(repo), "3_round1")
    data = tmp_path / "bdata"                                                     # a copy we may change
    data.mkdir()
    for f in ("baselines_training.jsonl", "baselines_round_features.jsonl", "baselines_info.json",
              "baselines_label_audit.jsonl", "baselines_relabel_check_a.jsonl", "baselines_relabel_check_b.jsonl"):
        shutil.copy(os.path.join(data0, f), data / f)
    srcs = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in data.iterdir()}
    script = os.path.join(repo, "pilot", "round1_rebuild", "make_baselines.py")
    srcs["make_baselines.py"] = hashlib.sha256(open(script, "rb").read()).hexdigest()
    base = tmp_path / "base.json"
    short = tmp_path / "short.json"                       # B0's metadata pins only three of the seven files
    short.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=[],
                                     sources_sha256={k: v for k, v in srcs.items() if k.endswith((".jsonl", ".json"))
                                                     and "relabel" not in k and "audit" not in k})))
    base.write_text(json.dumps(dict(META, setting="closed", web_access=False, models=[], sources_sha256=srcs)))
    tround.register(str(S._round), "ref-b0", _file(S, "ref-b0.jsonl"), str(short), "2026-10-31", kind="reference")
    tround.register(str(S._round), "ref-b1", _file(S, "ref-b1.jsonl"), str(base), "2026-10-31", kind="reference")
    (S._round / "sisters.json").write_text('{"groups": {}, "trial_group": {}}')    # files this small round lacks
    (S._round / "operations.jsonl").write_text("")
    rules = tmp_path / "rules.md"
    rules.write_text("# Rules\n")
    out = tmp_path / "hf"
    cmd = [sys.executable, os.path.join(SPACE, "build_space.py"), str(S._round), "--rules", str(rules),
           "--baselines-data", str(data)]
    r = subprocess.run(cmd[:3] + [str(out)] + cmd[3:], capture_output=True, text=True)
    assert r.returncode != 0 and "not the published baseline files" in r.stderr and not out.exists()
    shutil.rmtree(S._round / "entries" / "ref-b0")                                # register B0 again, in full
    reg = json.load(open(S._round / "registry.json"))
    (S._round / "registry.json").write_text(json.dumps([e for e in reg if e["id"] != "ref-b0"]))
    tround.register(str(S._round), "ref-b0", _file(S, "ref-b0.jsonl"), str(base), "2026-10-31", kind="reference")
    posted = hashlib.sha256((S._round / "registry.json").read_bytes()).hexdigest()
    r = subprocess.run(cmd[:3] + [str(out)] + cmd[3:] + ["--expect-registry-sha", "0" * 64], capture_output=True,
                       text=True)
    assert r.returncode != 0 and "is not the posted one" in r.stderr and not out.exists()
    r = subprocess.run(cmd[:3] + [str(out)] + cmd[3:] + ["--expect-registry-sha", posted], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    ds = out / "dataset"
    man = json.load(open(S._round / "manifest.json"))
    assert json.load(open(ds / "template" / "meta.models_board.example.json"))["prompt_sha256"] == man["instructions_sha256"]
    assert (ds / "references" / "make_baselines.py").exists() and (ds / "forecast_instructions.md").exists()
    sp = out / "space"                                    # the upload fingerprint runs from the built Space as documented
    r = subprocess.run([sys.executable, "-I", str(sp / "upload_fingerprint.py"), "t-r1", "--local", str(tmp_path / "nolog")],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0 and "uploads 0" in r.stdout, r.stderr
    tt = data / "baselines_training.jsonl"
    tt.write_text(tt.read_text().replace('"met": 1', '"met": 0', 1))                # the training table changed
    r = subprocess.run(cmd[:3] + [str(tmp_path / "hfa")] + cmd[3:], capture_output=True, text=True)
    assert r.returncode != 0 and "fitted from" in r.stderr and not (tmp_path / "hfa").exists()
    shutil.copy(os.path.join(data0, "baselines_training.jsonl"), tt)
    (S._round / "entries" / "extra").mkdir()                                      # an entry not in the registry
    r = subprocess.run(cmd[:3] + [str(tmp_path / "hfb")] + cmd[3:], capture_output=True, text=True)
    assert r.returncode != 0 and "not in the registry" in r.stderr
    (S._round / "entries" / "extra").rmdir()
    pk = sorted((S._round / "packets").glob("*.md"))
    pk[1].write_text(pk[1].read_text() + "junk\n")                               # one packet changed
    out3 = tmp_path / "hf3"
    r = subprocess.run(cmd[:3] + [str(out3)] + cmd[3:], capture_output=True, text=True)
    assert r.returncode != 0 and "does not match the manifest" in r.stderr and not out3.exists()
    pk[1].write_text(pk[1].read_text()[:-5])                                      # back as it was
    ref = S._round / "entries" / "ref-b1" / "forecasts.jsonl"
    ref.write_text(ref.read_text().replace("0.5", "0.999", 1))                    # a reference entry changed
    out4 = tmp_path / "hf4"
    r = subprocess.run(cmd[:3] + [str(out4)] + cmd[3:], capture_output=True, text=True)
    assert r.returncode != 0 and "does not match the registry" in r.stderr and not out4.exists()
    os.rename(pk[0], S._round / "packets" / "NCT09999999.md")                    # one packet swapped for another
    out2 = tmp_path / "hf2"
    r = subprocess.run(cmd[:3] + [str(out2)] + cmd[3:], capture_output=True, text=True)
    assert r.returncode != 0 and "packets" in r.stderr and not out2.exists()


def test_upload_fingerprint_is_stable_and_changes_with_any_upload():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "space"))
    import upload_fingerprint as U
    rows = [{"received_utc": "2026-11-02T10:00:00Z", "id": "team-a", "sha256": "a" * 64},
            {"received_utc": "2026-11-03T10:00:00Z", "id": "team-b", "sha256": "b" * 64}]
    sha, n = U.fingerprint(rows)
    assert n == 2 and sha == U.fingerprint([dict(r) for r in rows])[0]
    assert U.fingerprint(rows[:1])[0] != sha
    assert U.fingerprint([rows[0], dict(rows[1], sha256="c" * 64)])[0] != sha


def test_storage_failure_records_nothing_and_says_so_and_dates_are_judged_in_utc(S, tmp_path):
    class Broken(S.LocalStore):
        def put_many(self, which, files):
            if which == "public":
                raise OSError("hub down")
            super().put_many(which, files)
    store = Broken(str(tmp_path / "broken"))
    out = S.submit(_file(S), FORM, "alice", store, NOW)
    assert not out["ok"] and "not recorded" in out["message"] and S.registry_uploads(store) == []
    ok = S.LocalStore(str(tmp_path / "ok"))
    cet = dt.timezone(dt.timedelta(hours=1))                     # 11 Dec 00:30 CET is 10 Dec 23:30 UTC: still open
    late = S.submit(_file(S), FORM, "alice", ok, dt.datetime(2026, 12, 11, 0, 30, tzinfo=cet))
    assert late["ok"] and late["entry"]["received_utc"].endswith("+00:00")
