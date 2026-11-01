"""Pilot 2: lists for the result-extraction agents: each trial's question card and what the results check found.

usage: python3 -I make_extract_lists.py <set.json> <cards.jsonl> <out dir> --labels <labels.jsonl> [...] --pilot-key <key_C.json>
       --pubmed <pubmed.jsonl> --judged <judged.jsonl> [--size 10]
"""
import argparse
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("set")
ap.add_argument("cards")
ap.add_argument("out")
ap.add_argument("--labels", nargs="+", default=[])
ap.add_argument("--pilot-key")
ap.add_argument("--pubmed")
ap.add_argument("--judged")
ap.add_argument("--size", type=int, default=10)
a = ap.parse_args()
rows = json.load(open(a.set))
cards = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.cards) if l.strip()}
lab = {}
for p in a.labels:
    for l in open(p):
        if l.strip():
            r = json.loads(l)
            lab[r["nct_id"]] = r
key = {k["nct_id"]: k for k in json.load(open(a.pilot_key))} if a.pilot_key else {}
pub = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.pubmed)} if a.pubmed else {}
jud = {json.loads(l)["nct_id"]: json.loads(l) for l in open(a.judged)} if a.judged else {}


def block(n, src):
    c = cards[n]
    out = [f"## {n}", "Question card: " + "; ".join(f"{k}: {c.get(k)}" for k in
           ("endpoint", "kind", "effect_measure", "better", "control_measure", "unit", "experimental_arm", "control_arm", "design"))]
    if n in lab and src == "web":
        w = lab[n]
        out.append(f"Results check: met = {w['met']}; first public {w['first_public_date']}; result: {w.get('result')}; "
                   f"quote: {w.get('quote')}")
        out.append("Sources: " + " ; ".join((w.get("sources") or [])[:4]))
    elif n in key:
        k = key[n]
        out.append(f"Results check: met = {k.get('met')}; first public {k.get('first_public_date')}; endpoint: {k.get('endpoint')}; "
                   f"hazard ratio {k.get('hr')} ({k.get('hr_ci_low')} to {k.get('hr_ci_high')})")
        out.append("Sources: " + " ; ".join((k.get("sources") or [])[:4]))
    elif src == "pubmed_only" and n in jud:
        out.append(f"Results check (PubMed only): met = {jud[n]['met']}; published {jud[n]['pub_date']}; "
                   f"result: {jud[n].get('result')}")
    j = jud.get(n)
    if j and j.get("primary_result_found"):
        art = [x for x in pub[n]["articles"] if x["pmid"] == j["pmid"]]
        if art:
            out.append(f"PubMed abstract (PMID {j['pmid']}, {j['journal']}, {j['pub_date']}, https://doi.org/{j['doi']}): "
                       + " ".join(str(art[0].get("abstract") or "").split())[:2500])
    return "\n".join(out) + "\n"


os.makedirs(a.out, exist_ok=True)
lists = {}
for i in range(0, len(rows), a.size):
    name = f"X_{i // a.size:02d}"
    chunk = rows[i:i + a.size]
    lists[name] = [r["nct_id"] for r in chunk]
    open(os.path.join(a.out, name + ".md"), "w").write("\n".join(block(r["nct_id"], r["label_source"]) for r in chunk))
json.dump(lists, open(os.path.join(a.out, "lists.json"), "w"), indent=0)
print(len(rows), "trials in", len(lists), "lists")
