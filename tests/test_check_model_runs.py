"""check_model_runs.py: closed book; a run may edit its own output, but nothing else; the round's own prompt file; the
declared model."""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "pilot", "round1_rebuild", "check_model_runs.py")


def _args(tmp_path, model="m-1"):
    return ["--instructions", str(tmp_path / "round" / "forecast_instructions.md"), "--manifest",
            str(tmp_path / "round" / "manifest.json"), "--model-version", model]


def _setup(tmp_path, uses, reply_model="m-1", model="m-1"):
    b, o, t = tmp_path / "batches", tmp_path / "out", tmp_path / "tr"
    (tmp_path / "round").mkdir(parents=True)
    (tmp_path / "round" / "forecast_instructions.md").write_text("Forecast.\n")
    (tmp_path / "round" / "manifest.json").write_text(json.dumps(
        {"instructions_sha256": hashlib.sha256(b"Forecast.\n").hexdigest(), "trials": ["N1"]}))
    for d in (b, o, t):
        d.mkdir()
    (b / "lists.json").write_text(json.dumps({"B_000": ["N1"]}))
    (b / "B_000.md").write_text("# Trial N1\n")
    (o / "B_000.jsonl").write_text(json.dumps({"nct_id": "N1", "p_met": 0.5}) + "\n")
    text = (o / "B_000.jsonl").read_text()
    content = [{"type": "tool_use", "id": str(i), "name": n,
                "input": dict({"file_path": str(p)}, **({"content": text} if n == "Write" else
                                                     {"old_string": "0.5", "new_string": "0.5"} if n == "Edit" else {}))}
               for i, (n, p) in enumerate(uses)]
    (t / "A1.output").write_text(json.dumps({"message": {"role": "assistant", "model": reply_model,
                                                          "content": content}}) + "\n")
    (tmp_path / "agents.tsv").write_text("opus\tB_000\tA1\n")
    r = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "agents.tsv"), str(t), str(o), str(b),
                        str(tmp_path / "merged.jsonl")] + _args(tmp_path, model), capture_output=True, text=True)
    return r


def test_reading_and_editing_own_output_is_allowed(tmp_path):
    out = tmp_path / "out" / "B_000.jsonl"
    r = _setup(tmp_path, [("Read", tmp_path / "round" / "forecast_instructions.md"), ("Read", tmp_path / "batches" / "B_000.md"),
                          ("Write", out), ("Read", out), ("Edit", out)])
    assert r.returncode == 0, r.stdout


def test_other_tools_and_files_are_refused(tmp_path):
    out = tmp_path / "out" / "B_000.jsonl"
    r = _setup(tmp_path, [("Write", out), ("Edit", tmp_path / "out" / "B_001.jsonl")])
    assert r.returncode == 1 and "edited" in r.stdout
    for bad in (("WebSearch", out), ("Bash", out), ("Write", tmp_path / "elsewhere" / "B_000.jsonl"),
                ("Read", tmp_path / "out" / "B_001.md")):
        d = tmp_path / bad[0] / str(abs(hash(str(bad[1]))))
        d.mkdir(parents=True)
        r = _setup(d, [("Write", d / "out" / "B_000.jsonl"), bad])
        assert r.returncode == 1, (bad, r.stdout)


def test_lines_in_any_order_are_merged_in_the_batch_order(tmp_path):
    out = tmp_path / "out" / "B_000.jsonl"
    r = _setup(tmp_path, [("Write", out)])
    (tmp_path / "batches" / "lists.json").write_text(json.dumps({"B_000": ["N1", "N2"]}))
    m = json.loads((tmp_path / "round" / "manifest.json").read_text())
    (tmp_path / "round" / "manifest.json").write_text(json.dumps(dict(m, trials=["N1", "N2"])))
    for rows, ok in (([("N2", 0.4), ("N1", 0.5)], True), ([("N1", 0.5)], False), ([("N1", 0.5), ("N1", 0.6)], False)):
        out.write_text("".join(json.dumps({"nct_id": n, "p_met": p}) + "\n" for n, p in rows))
        _sync(tmp_path)
        r = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "agents.tsv"), str(tmp_path / "tr"),
                            str(tmp_path / "out"), str(tmp_path / "batches"), str(tmp_path / "merged.jsonl")]
                           + _args(tmp_path),
                           capture_output=True, text=True)
        assert (r.returncode == 0) == ok, (rows, r.stdout)
        if ok:
            merged = [json.loads(x)["nct_id"] for x in open(tmp_path / "merged.jsonl") if x.strip()]
            assert merged == ["N1", "N2"]


def test_another_prompt_file_or_another_model_is_refused(tmp_path):
    out = tmp_path / "out" / "B_000.jsonl"
    r = _setup(tmp_path / "a", [("Read", tmp_path / "a" / "x" / "forecast_instructions.md"), ("Write", tmp_path / "a" / "out" / "B_000.jsonl")])
    assert r.returncode == 1 and "read" in r.stdout
    r = _setup(tmp_path / "b", [("Write", tmp_path / "b" / "out" / "B_000.jsonl")], reply_model="m-0")
    assert r.returncode == 1 and "not m-1" in r.stdout
    r = _setup(tmp_path / "c", [("Write", tmp_path / "c" / "out" / "B_000.jsonl")])
    assert r.returncode == 0, r.stdout
    (tmp_path / "c" / "round" / "forecast_instructions.md").write_text("Changed.\n")
    r = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "c" / "agents.tsv"), str(tmp_path / "c" / "tr"),
                        str(tmp_path / "c" / "out"), str(tmp_path / "c" / "batches"), str(tmp_path / "c" / "m.jsonl")]
                       + _args(tmp_path / "c"), capture_output=True, text=True)
    assert r.returncode == 1 and "not the round's instructions" in r.stdout


def _sync(d):
    """Make the transcript's Writes of B_000.jsonl carry the output file as it now stands."""
    p = d / "tr" / "A1.output"
    lines = []
    for x in p.read_text().splitlines():
        m = json.loads(x)
        for c in (m.get("message") or {}).get("content") or []:
            if c.get("name") == "Write" and c["input"].get("file_path", "").endswith("B_000.jsonl"):
                c["input"]["content"] = (d / "out" / "B_000.jsonl").read_text()
        lines.append(json.dumps(m))
    p.write_text("\n".join(lines) + "\n")


def _rerun(d):
    return subprocess.run([sys.executable, SCRIPT, str(d / "agents.tsv"), str(d / "tr"), str(d / "out"),
                           str(d / "batches"), str(d / "m.jsonl")] + _args(d), capture_output=True, text=True)


def test_a_reply_naming_no_model_is_refused(tmp_path):
    r = _setup(tmp_path, [("Write", tmp_path / "out" / "B_000.jsonl")], reply_model=None)
    assert r.returncode == 1 and "unnamed model" in r.stdout


def test_every_trial_of_the_round_needs_a_run_and_dropped_trials_are_left_out(tmp_path):
    d = tmp_path / "a"
    _setup(d, [("Write", d / "out" / "B_000.jsonl")])
    m = json.loads((d / "round" / "manifest.json").read_text())
    (d / "round" / "manifest.json").write_text(json.dumps(dict(m, trials=["N1", "N9"])))
    r = _rerun(d)
    assert r.returncode == 1 and "no checked run" in r.stdout
    (d / "round" / "manifest.json").write_text(json.dumps(dict(m, trials=[])))
    r = _rerun(d)
    assert r.returncode == 0 and (d / "m.jsonl").read_text().strip() == ""


def test_a_cut_off_transcript_line_or_a_roleless_reply_from_another_model_is_refused(tmp_path):
    d = tmp_path / "a"
    _setup(d, [("Write", d / "out" / "B_000.jsonl")])
    with open(d / "tr" / "A1.output", "a") as fh:
        fh.write('{"message": {"role": "assistant", "model": "m-0", "content": [{"type": "tool_use"')
    r = _rerun(d)
    assert r.returncode == 1 and "not JSON" in r.stdout
    d = tmp_path / "b"
    _setup(d, [("Write", d / "out" / "B_000.jsonl")])
    with open(d / "tr" / "A1.output", "a") as fh:
        fh.write(json.dumps({"message": {"model": "m-0", "content": []}}) + "\n")
    r = _rerun(d)
    assert r.returncode == 1 and "m-0" in r.stdout


def test_two_runs_answering_the_same_trial_are_refused(tmp_path):
    d = tmp_path / "a"
    _setup(d, [("Write", d / "out" / "B_000.jsonl")])
    (d / "batches" / "lists.json").write_text(json.dumps({"B_000": ["N1"], "B_001": ["N1"]}))
    (d / "batches" / "B_001.md").write_text("# Trial N1\n")
    (d / "out" / "B_001.jsonl").write_text(json.dumps({"nct_id": "N1", "p_met": 0.4}) + "\n")
    (d / "tr" / "A2.output").write_text(json.dumps({"message": {"role": "assistant", "model": "m-1", "content": [
        {"type": "tool_use", "id": "0", "name": "Write", "input": {"file_path": str(d / "out" / "B_001.jsonl"),
                                                     "content": (d / "out" / "B_001.jsonl").read_text()}}]}}) + "\n")
    (d / "agents.tsv").write_text("opus\tB_000\tA1\nopus\tB_001\tA2\n")
    r = _rerun(d)
    assert r.returncode == 1 and "more than one run" in r.stdout


def test_an_output_changed_after_the_run_is_refused(tmp_path):
    d = tmp_path / "a"
    r = _setup(d, [("Write", d / "out" / "B_000.jsonl")])
    assert r.returncode == 0, r.stdout
    (d / "out" / "B_000.jsonl").write_text(json.dumps({"nct_id": "N1", "p_met": 0.99}) + "\n")
    r = _rerun(d)
    assert r.returncode == 1 and "differs from what the transcript wrote" in r.stdout
