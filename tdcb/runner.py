"""Reference runner: send packets to a model API and write predictions.jsonl.

Providers
---------
anthropic   Anthropic Messages API (ANTHROPIC_API_KEY)
openai      any OpenAI-compatible chat-completions endpoint (OPENAI_API_KEY,
            --base-url for other vendors)
mock        offline, deterministic pseudo-predictions for pipeline tests

The runner resumes: case IDs already present in the output file are skipped.
A run summary (model, tokens, wall time, failures) is written next to the
output as ``<output>.run.json``.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_HERE = os.path.dirname(__file__)


def load_prompt(track: str) -> str:
    with open(os.path.join(_HERE, "prompts", f"track_{track.lower()}.md")) as fh:
        return fh.read()


def extract_json(text: str) -> dict | None:
    """First JSON object in a model reply (tolerates code fences and prose)."""
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text)
    start = t.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = t.find("{", start + 1)
    return None


class Mock:
    """Deterministic pseudo-model for tests: noisy stratum-free guesses."""

    name = "mock"

    def __call__(self, system: str, user: str, case_id: str, track: str):
        h = int(hashlib.sha1(case_id.encode()).hexdigest(), 16)
        r = [((h >> (8 * k)) & 255) / 255 for k in range(3)]
        if track == "A":
            out = {"case_id": case_id, "p_next_line_or_death_6m": round(0.3 + 0.4 * r[0], 3),
                   "p_death_12m": round(0.15 + 0.4 * r[1], 3), "p_progression_6m": round(0.35 + 0.4 * r[2], 3),
                   "key_drivers": ["mock"], "rationale": "mock"}
        elif track == "C":
            hr = round(0.55 + 0.4 * r[1], 3)
            out = {"case_id": case_id, "p_met": round(0.3 + 0.5 * r[0], 3), "hr_median": hr,
                   "hr_low80": round(hr * 0.8, 3), "hr_high80": round(hr * 1.2, 3), "recalls_result": False,
                   "key_reasons": ["mock"]}
        elif track == "D":
            st = ["met", "not_met", "no_result_known", "unknown_trial"][int(r[0] * 3.999)]
            out = {"case_id": case_id, "status": st, "hr": round(0.5 + 0.4 * r[1], 2) if st in ("met", "not_met") else None,
                   "first_public": "2025-06" if st in ("met", "not_met") else None, "confidence": round(r[2], 2)}
        elif track == "E":
            menu = ["EGFR", "ALK", "KRAS", "HER2", "MSI", "GERMLINE", "PDL1", "HRR_TUMOR", "FGFR"]
            out = {"case_id": case_id, "tests_needed": [t for i, t in enumerate(menu) if (h >> i) & 1],
                   "most_important": None, "note": "mock"}
        elif track == "E2":
            words = ["EGFR mutation", "ALK fusion", "KRAS mutation", "HER2 IHC", "MSI/MMR status", "germline BRCA1/2",
                     "PD-L1 IHC", "tumour BRCA1/2", "FGFR2 fusion"]
            out = {"case_id": case_id, "tests_needed": [t for i, t in enumerate(words) if (h >> i) & 1],
                   "most_important": None, "note": "mock"}
        elif track == "F":
            ask = r[0] > 0.5
            out = {"case_id": case_id, "needs_info_first": ask,
                   "info_needed": ["HER2", "EGFR", "KRAS", "HRR_TUMOR"] if ask else [], "recommendation": "mock"}
        else:
            flagged = "Additional recent findings" in user and r[0] > 0.5
            out = {"case_id": case_id, "decision": "modify" if flagged else "proceed", "regimen": [],
                   "flags": [{"category": "interaction", "drug": "all", "note": "mock"}] if flagged else []}
        return json.dumps(out), {"input_tokens": len(user) // 4, "output_tokens": 60}


class Anthropic:
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float | None = None, timeout: float = 120):
        import httpx
        self.name = f"anthropic:{model}"
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature
        self.client = httpx.Client(timeout=timeout)
        self.key = os.environ["ANTHROPIC_API_KEY"]

    def __call__(self, system, user, case_id, track):
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        r = self.client.post("https://api.anthropic.com/v1/messages", json=body,
                             headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                                      "content-type": "application/json"})
        r.raise_for_status()
        j = r.json()
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        u = j.get("usage", {})
        return text, {"input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}


class OpenAICompatible:
    def __init__(self, model: str, base_url: str = "https://api.openai.com/v1", max_tokens: int = 1024,
                 temperature: float | None = None, timeout: float = 120, key_env: str = "OPENAI_API_KEY"):
        import httpx
        self.name = f"openai:{model}"
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.client = httpx.Client(timeout=timeout)
        self.key = os.environ[key_env]

    def __call__(self, system, user, case_id, track):
        body = {"model": self.model, "max_completion_tokens": self.max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        r = self.client.post(self.url, json=body, headers={"Authorization": f"Bearer {self.key}"})
        r.raise_for_status()
        j = r.json()
        text = j["choices"][0]["message"].get("content") or ""
        u = j.get("usage", {})
        return text, {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}


def make_provider(provider: str, model: str | None = None, **kw):
    if provider == "mock":
        return Mock()
    if provider == "anthropic":
        return Anthropic(model, **kw)
    if provider == "openai":
        return OpenAICompatible(model, **kw)
    raise ValueError(f"unknown provider {provider}")


def run(packet_dir: str, out_path: str, track: str, provider, workers: int = 4, limit: int | None = None,
        retries: int = 3, log=print) -> dict:
    system = load_prompt(track)
    files = sorted(glob.glob(os.path.join(packet_dir, "*.md")))
    if limit:
        files = files[:limit]
    done = set()
    if os.path.exists(out_path):
        with open(out_path) as fh:
            for line in fh:
                o = extract_json(line)
                if o and "case_id" in o:
                    done.add(o["case_id"])
    todo = [f for f in files if os.path.basename(f)[:-3] not in done]
    stats = {"model": provider.name, "track": track, "n_total": len(files), "n_skipped": len(done & {os.path.basename(f)[:-3] for f in files}),
             "n_ok": 0, "n_failed": 0, "input_tokens": 0, "output_tokens": 0, "failures": []}
    t0 = time.time()

    def one(path):
        cid = os.path.basename(path)[:-3]
        with open(path) as fh:
            user = fh.read()
        last_err = None
        for attempt in range(retries):
            try:
                text, usage = provider(system, user, cid, track)
                obj = extract_json(text)
                if obj is None:
                    raise ValueError("no JSON object in reply")
                obj["case_id"] = cid
                return cid, obj, usage, None
            except Exception as ex:  # noqa: BLE001
                last_err = f"{type(ex).__name__}: {ex}"
                time.sleep(2 ** attempt)
        return cid, None, {"input_tokens": 0, "output_tokens": 0}, last_err

    with open(out_path, "a") as out, ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, p) for p in todo]
        for k, fut in enumerate(as_completed(futs), 1):
            cid, obj, usage, err = fut.result()
            stats["input_tokens"] += usage.get("input_tokens", 0)
            stats["output_tokens"] += usage.get("output_tokens", 0)
            if obj is None:
                stats["n_failed"] += 1
                stats["failures"].append({"case_id": cid, "error": err})
            else:
                stats["n_ok"] += 1
                out.write(json.dumps(obj) + "\n")
                out.flush()
            if k % 50 == 0:
                log(f"  {k}/{len(todo)} done")
    stats["wall_seconds"] = round(time.time() - t0, 1)
    with open(out_path + ".run.json", "w") as fh:
        json.dump(stats, fh, indent=1)
    return stats
