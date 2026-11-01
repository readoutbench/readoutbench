import json
import os

import pytest

from tdcb.trials import round as tround


def _build(tmp, keyrows):
    b = tmp / "build"
    (b / "private").mkdir(parents=True)
    (b / "packets" / "C" / "open").mkdir(parents=True)
    (b / "private" / "key_C.json").write_text(json.dumps(keyrows))
    for k in keyrows:
        if k["set"] == "open":
            (b / "packets" / "C" / "open" / f"{k['nct_id']}.md").write_text(f"# Trial {k['nct_id']}\n")
            (b / "packets" / "C" / "open" / f"{k['nct_id']}.json").write_text(json.dumps(
                {"case_id": k["nct_id"], "endpoint_kind": k["endpoint_kind"],
                 "record": {"title": "T", "primary_completion_date": "2026-12-01"}}))
    return b


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(path)


META = {"team": "A", "entry_name": "a", "contact": "a@b.c", "models": ["m"], "harness": "one call",
        "setting": "open", "web_access": True, "cost_usd_per_trial": 0.5,
        "retrieval": "web search", "human_in_the_loop": False, "fine_tuned": False, "ensemble": False}


def test_round_export_validate_register_and_score(tmp_path):
    ids = ["NCT00000001", "NCT00000002", "NCT00000003"]
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "time_to_event" if i != ids[2] else "other"} for i in ids]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    m = tround.export(str(b), str(r), "t-r1", closes="2026-12-31")
    assert m["n_trials"] == 3 and m["n_time_to_event"] == 2 and len(m["packets_sha256"]) == 3
    assert json.loads((r / "registry.json").read_text()) == []

    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    good = _jsonl(tmp_path / "good.jsonl", [{"nct_id": ids[0], "p_met": 0.8, "hr_median": 0.7, "hr_low80": 0.5,
                                             "hr_high80": 0.9}, {"nct_id": ids[1], "p_met": 0.3},
                                            {"nct_id": ids[2], "p_met": 0.6}])
    v = tround.validate(str(r), good, str(meta))
    assert v["ok"] and v["n_forecasts"] == 3 and v["warnings"]          # one time-to-event trial without an HR
    bad = _jsonl(tmp_path / "bad.jsonl", [{"nct_id": ids[0], "p_met": 1.2},
                                          {"nct_id": ids[1], "p_met": 0.5, "hr_median": 0.7, "hr_low80": 0.9,
                                           "hr_high80": 0.8}, {"nct_id": "NCT99999999", "p_met": 0.5}])
    v = tround.validate(str(r), bad)
    assert not v["ok"] and len(v["errors"]) == 4                          # p, HR order, unknown trial, one missing
    costly = tmp_path / "costly.json"                                    # no cap on the cost, only a number >= 0
    costly.write_text(json.dumps({**META, "cost_usd_per_trial": 250}))
    assert tround.validate(str(r), good, str(costly))["ok"]
    costly.write_text(json.dumps({**META, "cost_usd_per_trial": -1}))
    assert not tround.validate(str(r), good, str(costly))["ok"]
    no_method = tmp_path / "no_method.json"                             # the Open board says how the entry was made
    no_method.write_text(json.dumps({k: v for k, v in META.items() if k != "retrieval"}))
    assert any("retrieval is needed" in e for e in tround.validate(str(r), good, str(no_method))["errors"])
    no_method.write_text(json.dumps({**META, "retrieval": "google"}))
    assert any("retrieval must be one of" in e for e in tround.validate(str(r), good, str(no_method))["errors"])

    base = _jsonl(tmp_path / "base.jsonl", [{"nct_id": i, "p_met": 0.7} for i in ids])
    tround.register(str(r), "ref-b0", base, str(meta), "2026-10-22", kind="reference")
    tround.register(str(r), "team-a", good, str(meta), "2026-11-15")
    with pytest.raises(ValueError):
        tround.register(str(r), "team-b", good, str(meta), "2027-01-02")  # after the close
    with pytest.raises(ValueError):
        tround.register(str(r), "team-a", good, str(meta), "2026-11-16")  # same id twice

    # results come in: one before the close (dropped), one after (scored), one still pending
    key[0].update(set="post_cutoff", met=1, first_public_date="2027-03-01", hr=0.6)
    key[1].update(set="post_cutoff", met=0, first_public_date="2026-12-10")
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    lb = tround.leaderboard(str(b), str(r), n_boot=50, min_scored=1)
    st = lb["status"]
    assert st["n_scored"] == 1 and st["n_dropped_reported_before_close"] == 1 and st["n_pending"] == 1
    assert lb["dropped"] == [ids[1]] and st["ranked"]
    by = {e["id"]: e for e in lb["entries"] + lb["references"]}
    assert by["team-a"]["n_scored"] == 1 and abs(by["team-a"]["brier"] - 0.04) < 1e-9
    assert abs(by["ref-b0"]["brier"] - 0.09) < 1e-9 and by["team-a"]["bss_vs_base_rate"] > 0
    assert lb["entries"][0]["id"] == "team-a"


def test_sealed_submission_and_matching_forecasts(tmp_path):
    ids = ["NCT00000001", "NCT00000002"]
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in ids]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    tround.export(str(b), str(r), "t-r1", closes="2026-12-31")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({**META, "contact": "@octocat"}))       # a GitHub handle is a valid contact
    fc = _jsonl(tmp_path / "f.jsonl", [{"nct_id": i, "p_met": 0.5} for i in ids])
    sha = tround.validate(str(r), fc, str(meta))["sha256"]

    good = tmp_path / "forecasts.sha256"
    good.write_text(f"{sha}  forecasts.jsonl\n")                       # as sha256sum prints it
    v = tround.check_sealed(str(meta), str(good))
    assert v["ok"] and v["sha256"] == sha
    bad = tmp_path / "bad.sha256"
    bad.write_text("not-a-hash\n")
    assert not tround.check_sealed(str(meta), str(bad))["ok"]

    with pytest.raises(ValueError):                                     # the e-mailed file must match the seal
        tround.register(str(r), "team-a", fc, str(meta), "2026-11-01", expect_sha256="0" * 64)
    e = tround.register(str(r), "team-a", fc, str(meta), "2026-11-01", expect_sha256=sha.upper())
    assert e["sha256"] == sha
    assert "contact" not in json.loads((r / "registry.json").read_text())[0]
    assert "contact" not in json.loads((r / "entries" / "team-a" / "meta.json").read_text())


def test_void_list_takes_a_trial_out_of_scoring_and_a_result_before_launch_drops_it(tmp_path):
    ids = ["NCT00000001", "NCT00000002", "NCT00000003"]
    key = [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in ids]
    b = _build(tmp_path, key)
    r = tmp_path / "round"
    tround.export(str(b), str(r), "t-r1", closes="2026-12-31")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    fc = _jsonl(tmp_path / "f.jsonl", [{"nct_id": i, "p_met": 0.8} for i in ids])
    tround.register(str(r), "ref-b0", fc, str(meta), "2026-10-22", kind="reference")
    tround.register(str(r), "team-a", fc, str(meta), "2026-11-15")
    # all three report after the close; one had its primary result public before the round opened (dropped by its
    # date), one is voided by the organiser (a safety statement on a safety primary found after launch)
    key[0].update(set="post_cutoff", met=1, first_public_date="2027-03-01")
    key[1].update(set="post_cutoff", met=1, first_public_date="2026-10-15")      # before the round opened
    key[2].update(set="post_cutoff", met=0, first_public_date="2027-02-01")
    (b / "private" / "key_C.json").write_text(json.dumps(key))
    lb = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1)
    assert lb["dropped"] == [ids[1]] and lb["status"]["n_scored"] == 2 and lb["void"] == []
    (r / "void.jsonl").write_text(json.dumps({"nct_id": ids[2], "reason": "safety statement before launch",
                                              "date": "2026-12-01"}) + "\n")
    lb = tround.leaderboard(str(b), str(r), n_boot=20, min_scored=1)
    assert lb["void"] == [ids[2]] and lb["status"]["n_scored"] == 1 and lb["status"]["n_pending"] == 0
    by = {e["id"]: e for e in lb["entries"]}
    assert by["team-a"]["n_scored"] == 1 and abs(by["team-a"]["brier"] - 0.04) < 1e-9


def test_validate_warns_on_unknown_keys(tmp_path):
    ids = ["NCT00000001"]
    b = _build(tmp_path, [{"nct_id": ids[0], "set": "open", "endpoint_kind": "other"}])
    r = tmp_path / "round"
    tround.export(str(b), str(r), "t-r1", closes="2026-12-31")
    f = _jsonl(tmp_path / "f.jsonl", [{"nct_id": ids[0], "p_met": 0.5, "zzz": 1, "p_mett": 0.4}])
    v = tround.validate(str(r), f)
    assert v["ok"] and any("unknown key(s) p_mett, zzz" in w for w in v["warnings"])
    f = _jsonl(tmp_path / "g.jsonl", [{"nct_id": ids[0], "p_met": 0.5}])
    assert not any("unknown key" in w for w in tround.validate(str(r), f)["warnings"])


def test_void_list_refuses_bad_lines(tmp_path):
    ids = ["NCT00000001", "NCT00000002"]
    b = _build(tmp_path, [{"nct_id": i, "set": "open", "endpoint_kind": "other"} for i in ids])
    r = tmp_path / "round"
    tround.export(str(b), str(r), "t-r1", closes="2026-12-31")
    ok = {"nct_id": ids[0], "reason": "safety statement before launch", "date": "2026-12-01"}
    (r / "void.jsonl").write_text(json.dumps(dict(ok, nct_id=ids[0].lower())) + "\n")
    assert list(tround.load_void(str(r), ids)) == [ids[0]]                       # lower case is read as upper
    (r / "void.jsonl").write_bytes(b"\xef\xbb\xbf" + (json.dumps(ok) + "\r\n").encode())
    assert list(tround.load_void(str(r), ids)) == [ids[0]]                       # a BOM and CRLF are fine
    for bad, msg in ((dict(ok, nct_id="NCT99999999"), "not a trial of this round"), ({**ok, "reason": " "}, "needs a reason"),
                     ({k: v for k, v in ok.items() if k != "date"}, "needs a date"), (dict(ok, date="2026-13-40"), "is not a date"),
                     ({k: v for k, v in ok.items() if k != "nct_id"}, "no nct_id")):
        (r / "void.jsonl").write_text(json.dumps(bad) + "\n")
        with pytest.raises(ValueError, match=msg):
            tround.load_void(str(r), ids)
    (r / "void.jsonl").write_text(json.dumps(ok) + "\n" + json.dumps(ok) + "\n")
    with pytest.raises(ValueError, match="listed twice"):
        tround.load_void(str(r), ids)
    (r / "void.jsonl").write_text(json.dumps(ok) + "\n{not json\n")
    with pytest.raises(ValueError, match="line 2: not valid JSON"):
        tround.load_void(str(r), ids)
