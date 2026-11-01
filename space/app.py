"""ReadoutBench: the submission page and leaderboard (a Hugging Face Space)."""
from __future__ import annotations

import json
import os
import re

import gradio as gr

import submit as S

MAN = S.manifest()
try:
    STORE, STORE_ERROR = S.make_store(), None
except S.Misconfigured as e:              # fail closed: never accept uploads that would be lost
    STORE, STORE_ERROR = None, str(e)
RULES_URL = os.environ.get("RULES_URL", "https://huggingface.co/datasets/" + os.environ.get("REGISTRY_REPO", ""))
FILES_URL = os.environ.get("FILES_URL", RULES_URL)

INTRO = f"""# ReadoutBench · Round 1
Forecast **{MAN['n_trials']} company-run clinical trials** before their results are public. Scored as the results come
out. Submissions close **at the end of {MAN['closes']}, UTC** (23:59:59 UTC; in Central Europe that is 00:59:59 CET the next day); results count until **{MAN.get('deadline')}**.

[Rules]({RULES_URL}) · [Trial files and question cards]({FILES_URL})
"""
if STORE_ERROR:
    INTRO += f"\n> **Submissions are closed for now:** {STORE_ERROR}\n"


def do_submit(file, team, entry_name, contact, models, harness, setting, web_access, cost, code_url, model_version,
              provider, same_prompt, run_settings, retrieval, human, tuned, ensemble, agree,
              profile: gr.OAuthProfile | None):
    user = profile.username if profile else (None if os.environ.get("HF_TOKEN") else "local-tester")
    form = {"team": team, "entry_name": entry_name, "contact": contact, "models": models, "harness": harness,
            "setting": setting, "web_access": web_access, "cost_usd_per_trial": cost, "code_url": code_url,
            "model_version": model_version, "provider": provider, "same_prompt": same_prompt,
            "run_settings": run_settings, "retrieval": retrieval, "human_in_the_loop": human, "fine_tuned": tuned,
            "ensemble": ensemble, "agree": agree}
    r = S.submit(file if isinstance(file, str) else getattr(file, "name", None), form, user, STORE)
    out = ("### Accepted. " if r["ok"] else "### Not accepted. ") + r["message"]
    if r["errors"]:
        out += "\n\n**Problems:**\n" + "\n".join(f"- {e}" for e in r["errors"])
    if r["warnings"]:
        out += "\n\n**Notes:**\n" + "\n".join(f"- {w}" for w in r["warnings"])
    return out, S.registry_rows(STORE)


def esc(x) -> str:
    """Entrants' text as plain text in a Markdown table: no links, images, emphasis, HTML or broken columns, and no
    bare web address turned into a link (a zero-width space is put after "//" and before each "." of a domain)."""
    t = " ".join(str(x if x is not None else "–").split())
    t = "".join("\\" + c if c in "\\|[]()!*_<>`#~" else c for c in t)
    # no web or e-mail address may become a link: a zero-width space after every "//", "." and "@"
    return re.sub(r"(//|\.|@)(?=\S)", lambda m: m.group(1) + "\u200b", t)


TIER_WORDS = {1: "Clearly better than the registry model", 2: "No clear difference from the registry model",
              3: "Clearly worse than the registry model"}
NUMBER_TIER_WORDS = {1: "clearly better", 2: "no clear difference", 3: "clearly worse"}


def leaderboard_md():
    try:
        lb = json.loads(STORE.read("public", "leaderboard.json")) if STORE else None
    except Exception:                      # not published yet
        lb = None
    if not lb:
        return ("The leaderboard appears after the close, once results come in, and is updated at least monthly with "
                "scores and intervals. Entries are placed in tiers once a pass's labels are complete (after its "
                "deadline) and 100 trials are scored. Until then, the entries received are listed under **Entries**.")
    st = lb["status"]
    f = lambda x, d=3: "–" if x is None else f"{x:.{d}f}"  # noqa: E731
    ci = lambda c, d=2: "" if not c else f" ({c[0]:.{d}f} to {c[1]:.{d}f})"  # noqa: E731
    which = ("early look, not the ranking" if st.get("early_look") else
             "supplementary pass, not ranked" if lb.get("supplementary") else
             "ranked pass" if st.get("ranked") else "ranked pass, interim: no tiers until its labels are complete")
    out = [f"{st['n_scored']} trials scored ({which}, results up to {st['deadline']}) · "
           f"{st.get('n_pending', 0)} pending · {f(st.get('share_met_among_scored'), 2)} of scored trials met · "
           f"{st.get('n_vague_only_scored_not_met', 0)} of them only vague at the deadline, counted as not met "
           f"(rule 6; every score without them is under **Other scores**) · updated {lb['computed_at']}. "
           "The full leaderboard, with every number and interval, is `leaderboard.json` in the round's dataset."]
    by = {e["id"]: e for e in lb["entries"] + lb.get("references", [])}
    head = ("| Entry | Team | Model / harness | Brier (lower is better) | Skill vs registry model (95%) | "
            "Adds to it (exploratory) | AUROC | Number score | Number tier (vs ref-opus-5-5) | Method | "
            "Cost per trial (declared, not checked) | First upload: Brier |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|")

    def row(e):
        add = e.get("adds_to_registry_model") or {}
        fu = e.get("first_upload") or {}
        who = esc(e.get("model_version") or ", ".join(e.get("models") or []) or "–")
        if e.get("kind") == "reference":
            who += " (organiser's run, logs kept)"
        changed = " (setup changed)" if fu and not fu.get("same_setup", True) else ""
        method = "; ".join(x for x in (
            esc(e["retrieval"]) if e.get("retrieval") else "",
            "people in the loop" if e.get("human_in_the_loop") else "",
            "fine-tuned" if e.get("fine_tuned") else "",
            "ensemble" if e.get("ensemble") else "") if x) or "–"
        cost = e.get("cost_usd_per_trial")
        return (f"| {esc(e['name'])} | {esc(e['team'])} | {who}{' + web' if e.get('web_access') else ''} | {f(e['brier'])} | "
                f"{f(e.get('bss_vs_registry_model'), 2)}{ci(e.get('bss_vs_registry_model_ci95'))} | "
                f"{'no (negative weight)' if add and add.get('positive_weight') is False else {True: 'yes', False: 'no'}.get(add.get('adds'), '–')} | {f(e.get('auroc'), 2)} | "
                f"{f((e.get('numbers') or {}).get('score'), 2)} | {NUMBER_TIER_WORDS.get(e.get('number_tier'), '–')} | "
                f"{method} | {'–' if cost is None else f'${cost:,.2f}'} | {f(fu.get('brier'))}{changed} |")
    names = lb.get("board_names") or {}
    for bd, title in (("models", "Models"), ("open", "Open")):
        ids = (lb.get("boards") or {}).get(bd) or []
        out.append(f"\n## {title} board\n{names.get(bd, '')}. {len(ids)} entries, each tested on its own against the "
                   "registry model.\n")
        if not ids:
            out.append("No entries yet.")
            continue
        tiers = [by[i].get("tier") for i in ids]
        if any(t is not None for t in tiers):
            for t in (1, 2, 3):
                grp = [by[i] for i in ids if by[i].get("tier") == t]
                if grp:
                    look = " (early look, not the ranking)" if st.get("early_look") else ""
                    out += [f"\n**{TIER_WORDS[t]}**{look} (listed by Brier score)\n", head] + [row(e) for e in grp]
        else:
            out += [head] + [row(by[i]) for i in ids]
    # the scores shown next to the ranking and never part of it
    other_head = ("| Entry | Board | Brier without the vague-only trials (n) | Skill vs registry model without them (95%) | "
                  "Tier without them | `p_public` Brier | Met by the deadline: Brier | Operations Brier |\n"
                  "|---|---|---|---|---|---|---|---|")
    other = []
    for bd in ("models", "open"):
        for i in (lb.get("boards") or {}).get(bd) or []:
            e = by[i]
            wv, pp, md, op = (e.get(k) or {} for k in ("without_vague_only", "p_public", "met_by_deadline",
                                                        "operations"))
            n_wo = f" ({wv['n']})" if wv.get("n") else ""
            other.append(f"| {esc(e['name'])} | {bd} | {f(wv.get('brier'))}{n_wo} | "
                         f"{f(wv.get('bss_vs_registry_model'), 2)}{ci(wv.get('bss_vs_registry_model_ci95'))} | "
                         f"{TIER_WORDS.get(wv.get('tier'), '–').lower()} | {f(pp.get('brier'))} | {f(md.get('brier'))} | "
                         f"{f(op.get('brier'))} |")
    if other:
        other.append("\nThe tier tests a Brier gap of more than 0.005 either way; the skill interval is against no gap at "
                     "all, so an interval that excludes 0 can sit next to \"no clear difference\".")
        out += ["\n## Other scores (shown, never ranked)\n",
                f"`p_public` and met by the deadline: {st.get('p_public_resolved') or 0} trials resolved "
                f"(share public by the deadline {f(st.get('share_public_by_deadline'), 2)}; share met by the deadline "
                f"{f(st.get('share_met_by_deadline'), 2)}). Operations: read on 31 August 2027.\n", other_head] + other
    base = [e for e in lb.get("references", []) if e.get("board") == "baseline"]
    if base:
        out += ["\n## Baselines\n", "| Baseline | Brier | Brier without the vague-only trials | Skill vs base rate | "
                "AUROC |\n|---|---|---|---|---|"]
        out += [f"| {esc(e['name'])} | {f(e['brier'])} | {f((e.get('without_vague_only') or {}).get('brier'))} | "
                f"{f(e.get('bss_vs_base_rate'), 2)} | {f(e.get('auroc'), 2)} |" for e in base]
    return "\n".join(out)


with gr.Blocks(title="ReadoutBench") as demo:
    gr.Markdown(INTRO)
    with gr.Tab("Submit"):
        gr.Markdown("Sign in, attach `forecasts.jsonl`, describe the entry. The file is checked at once; if it "
                    "passes, it is stored privately and the entry is listed with your Hugging Face account, the time "
                    "and the SHA-256. You may upload again under the same entry name until the close (the end of the closing day, UTC); the "
                    "last valid upload counts, and the first is scored next to it. "
                    f"Up to {S.MAX_ENTRIES} entries per account. "
                    "Two boards: **Models** (one model, the round's instructions unchanged, the packet only: no web, "
                    "no tools, no other model) and **Open** (anything else).")
        if os.environ.get("SPACE_ID"):            # on Hugging Face; a local preview has no sign-in
            gr.LoginButton()
        f_file = gr.File(label="forecasts.jsonl", file_types=[".jsonl"], type="filepath")
        with gr.Row():
            f_team = gr.Textbox(label="Team")
            f_entry = gr.Textbox(label="Entry name", placeholder="e.g. Model X with search and a three-model vote")
        with gr.Row():
            f_contact = gr.Textbox(label="Contact e-mail (never published)")
            f_models = gr.Textbox(label="Models used (comma-separated)")
        f_harness = gr.Textbox(label="Harness: tools, number of calls, how answers are combined", lines=3)
        with gr.Row():
            f_setting = gr.Radio([("Models board", "closed"), ("Open board", "open")], value="open", label="Board",
                                 info="Models = one model, the round's instructions unchanged, the packet only; "
                                      "Open = anything else")
            f_web = gr.Checkbox(label="Used web access")
            f_cost = gr.Number(label="Average cost per trial in USD (declared, not checked: compute and API costs, not people's time)", value=None)
        with gr.Row():
            f_version = gr.Textbox(label="Exact model version (needed on the Models board)",
                                   placeholder="as the provider names it, with its date")
            f_provider = gr.Textbox(label="Provider or API (needed on the Models board)")
        with gr.Row():
            f_same = gr.Checkbox(label="Models board: I used the round's instructions unchanged")
            f_settings = gr.Textbox(label="Run settings (optional): reasoning effort, temperature, dates run")
        with gr.Row():                            # how an Open board entry was made, shown with it
            f_retrieval = gr.Dropdown(list(S.tround.RETRIEVAL), label="Open board: retrieval", value=None)
            f_human = gr.Checkbox(label="Open board: people edited or chose forecasts")
            f_tuned = gr.Checkbox(label="Open board: a model was trained or fine-tuned for this")
            f_ensemble = gr.Checkbox(label="Open board: answers of several models or runs combined")
        f_code = gr.Textbox(label="Code URL (optional)")
        f_agree = gr.Checkbox(label="No inside information about any trial, and no use of other entries' forecasts.")
        btn = gr.Button("Check and submit", variant="primary")
        result = gr.Markdown()
    with gr.Tab("Entries"):
        gr.Markdown("Entries received so far. Forecasts are published after the close.")
        table = gr.Dataframe(value=S.registry_rows(STORE), interactive=False, wrap=True)
        gr.Button("Refresh").click(lambda: S.registry_rows(STORE), outputs=table)
    with gr.Tab("Leaderboard"):
        lb = gr.Markdown(leaderboard_md())
        gr.Button("Refresh").click(leaderboard_md, outputs=lb)
    btn.click(do_submit, [f_file, f_team, f_entry, f_contact, f_models, f_harness, f_setting, f_web, f_cost, f_code,
                          f_version, f_provider, f_same, f_settings, f_retrieval, f_human, f_tuned, f_ensemble,
                          f_agree], [result, table])

if __name__ == "__main__":
    demo.launch()
