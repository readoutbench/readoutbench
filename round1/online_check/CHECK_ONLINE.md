# What is still to be checked online before the round opens

The results check is **finished**: every one of the 653 trials except 85 passed the deeper check (`results_gate.py`); the 85 were put back by the organiser although no check reached the bar, and are marked `below the bar` in `questions.json`, under the stricter bar of 30 October (registry copies, sec.gov filings and news-repost sites no longer count as an opened page), and a separate stop check on 30 October (announced stops, pauses and holds the registry does not show). Two
things are left, both for Saturday 31 October.

## 1. The registry status pull: every trial (658 on 30 October, night; redone per trial for the 653 on 31 October)

**Done**, and redone per trial on 31 October (00:10 CET; 30 October 23:10 UTC) through the organiser's ClinicalTrials.gov tool: `status_pull_2026-10-31.jsonl` has one line per trial in the round (status, primary completion date, enrollment, and the values in `records.jsonl` beside them). No trial is terminated, withdrawn or suspended and no status changed. Five primary completion dates moved (two out past the window: NCT06629779 to 2027-09-30, NCT06944522 to 2028-10, past even the final pass of 31 December 2027); they stay in, since running late is what `p_late` asks, and NCT06944522's p_met will very likely resolve as not public. **NCT06944522** (the late one): its registry primary completion moved to October 2028, past even the final pass of 31 December 2027; it stays in the round on purpose. The file is rebuilt from the raw pull with `registry/status_pull.py` (raw files and their SHA-256s in `registry/raw_2026-10-31/`, pulled 30 October 23:10 UTC). The tool's search results carry no results-posted field, so `has_results` is null in this file; that no trial has results posted is shown by the query recorded in `registry/results_query.json` (0 of 658, with a control trial that has results found). The 30 October summary (`registry_pull_2026-10-30.txt`) counted the 658 trials then in the round. The registry pull cannot see a stop the registry does not show (TROPION-Lung12 was one), which is why the sponsor sweep of 31 October was run. The script route below stays for a rerun.

A trial that stopped or posted results since the 29 October pull comes out. This pull also keeps ClinicalTrials.gov's
ESTIMATED/ACTUAL date type, which the earlier tool dropped.

On any computer that reaches clinicaltrials.gov:

```bash
cd registry
python3 fetch_raw.py round_ids.txt raw
```

Standard Python, nothing to install; it can be rerun after a failure. Send back the `raw/` folder. It becomes drops with one command: `python3 -I status_drops.py raw <the round's manifest.json> status_drops.jsonl` (in `4_code/pilot/round1_rebuild/`) lists every trial that is terminated, withdrawn, suspended or has results posted; its lines are added to the launch drop list and `launch.py` is run again.

## 2. Watch list: required (done on 30 October, night)

**Done** for the 73 trials listed on 30 October: no public result and no stop (`watch_log.tsv`, one line per trial with the pages looked at). The rows added after that look (marked v27 and v28) are not in `watch_log.tsv` because they were added after it; they fall after launch and are to be watched then: a result public before launch found later means the trial is never scored.

The registry pull does not see press releases, so this look is a required step. These trials had a readout due about
now when they were checked. For each one, search the trial and the drug (and the sponsor's news page) and write one line
to `watch_log.tsv`: trial, date and time checked, the URLs looked at, and "nothing" or the result found with its
link and date. A trial with any public statement on a registered primary outcome before launch is added to the drop
list and `launch.py` is run again. (A result found only after launch is also covered: such a trial is never scored.)

| Trial | What to look for |
|---|---|
| NCT06269705 (Pacira, ZILRETTA shoulder) | topline "later in 2026" |
| NCT06297603 (Lilly retatrutide) | primary completion October 2026 |
| NCT06957080 (Merck BAROLO) | its sister trial BRUNELLO read out in September |
| NCT07037875 (Cinclus) | Q4 topline, all visits done |
| NCT06496607 (solrikitug) | completed 26 October |
| NCT06388564 (axatilimab) | primary completion 1 October; possibly at ASH |
| NCT06341335 | primary completion November 2026; completed September 2026 |
| NCT06421636 (REGN7999) | the EU register shows it ended 19 June 2026 with 19 of 95 enrolled |
| NCT06843590 (Alkermes Vibrance-3) | study completion guided for Q4 2026 |
| NCT05407636, NCT06851559, NCT06742190, NCT07287189, NCT05643534 | flagged by the v14 review as likely to read out soon |
| NCT07298330 (AZURE-4) | topline guided to Q4 2026; its sister AZURE-1 read out positive on 28 September |
| NCT05653349 (VAYHIT1), NCT07810972 | primary completion in September or October 2026, no results yet |
| NCT06846515 (Sobi REDUCE 1, pozdeutinurad) | data guided for 2H 2026; sister REDUCE 2 read out in May |
| NCT06116916 (Kyowa Kirin KHK4951, DME) | primary completion 31 October 2026; the nAMD sister trial read out in September |
| NCT06237335 (ReCode RCT2100) | safety primary; data guided for Q4 |
| NCT06516952 (Incyte, prurigo nodularis) | primary completion 19 October 2026; phase 3 data guided for 2026 |
| NCT07260877 (Ventus) | topline guided for 2H 2026 |
| NCT01983241 (SPARTA) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT05134441 (ENSURE-1) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT05164341 (METRE-PL) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT05702034 (LIBREXIA-STROK) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT05851443 (Incyte Corporation) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06456593 (ENHANCE-CD) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06496620 (ZION) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06901505 (Akebia Therapeutics) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06903338 (Vir Biotechnology, Inc.) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06987643 (RESTORE) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06126224 (Karuna Therapeutics, Inc., a Bristol Mye) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06585787 (Karuna Therapeutics, Inc., a Bristol Mye) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT06958211 (Incyte Corporation) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT07548632 (PREDICT-1) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT03165734 (PACIFICA) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT07176390 (Merck Sharp & Dohme LLC) | readout expected soon (organiser's sign-off or the v20 review) |
| NCT04435990 | EU register: ended April 2026; results summary due |
| NCT04704921 (REGENXBIO sura-vec, wet AMD) | topline guided for Q4 2026 |
| NCT05263934 (GSK OCEAN) | primary completion 29 September 2026 |
| NCT05281471 (Genelux) | topline guided for 2H 2026 |
| NCT05757869 (Librexia AF) | topline guided for 2026 |
| NCT06516965 (Incyte STOP-PN2) | phase 3 data guided for Q4 2026 |
| NCT06309966 (Biohaven RISE 3, opakalim) | fully enrolled, results guided for later in 2026; the FDA hold of September paused only RISE 2 |
| NCT07010471 (Praxis EMERALD, relutrigine) | the sister trial EMBOLD stopped early for efficacy in December 2025 |
| NCT05201638 (Immunic ENSURE-2) | readout expected soon (v20 review) |
| NCT06773962 (TB006, Parkinson's disease) | primary completion 28 November 2026 (v20 review) |
| NCT06708260 (EnnovaBio) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-08-12): a readout may come at any time |
| NCT07032597 (AbbVie) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-09-03): a readout may come at any time |
| NCT07241377 (RDC Clinical Pty Ltd) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-08-05): a readout may come at any time |
| NCT05372718 (Supergene, LLC) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-09-30): a readout may come at any time |
| NCT05995340 (AbbVie) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-07-14): a readout may come at any time |
| NCT06507436 (Jiangsu HengRui Medicine Co., Ltd.) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-08-14): a readout may come at any time |
| NCT06569056 (Jiangsu HengRui Medicine Co., Ltd.) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-09-01): a readout may come at any time |
| NCT06750289 (AstraZeneca) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-09-21): a readout may come at any time |
| NCT06841731 (Jiangsu HengRui Medicine Co., Ltd.) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-09-22): a readout may come at any time |
| NCT06881836 (Ono Pharmaceutical Co., Ltd.) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-07-31): a readout may come at any time |
| NCT07446309 (Jiangsu HengRui Medicine Co., Ltd.) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-07-14): a readout may come at any time |
| NCT02616302 (Takeda) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-07-21): a readout may come at any time |
| NCT05267613 (AstraZeneca) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-08-10): a readout may come at any time |
| NCT06769659 (NeuroPro Therapeutics, Inc.) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-08-17): a readout may come at any time |
| NCT07372924 (Jiangsu HengRui Medicine Co., Ltd.) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-08-14): a readout may come at any time |
| NCT07790120 (Shenzhen Salubris Pharmaceuticals Co., L) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-07-02): a readout may come at any time |
| NCT07791524 (Shanghai Minwei Biotechnology Co., Ltd) | below the bar and completed on ClinicalTrials.gov (primary completion 2026-07-09): a readout may come at any time |
| NCT06008093 | AstraZeneca TRITON: primary completion 23 October 2026; an interim (ORR only) was at ASCO 2026 (v22 review) |
| NCT06389136 | SWITCH-UP: primary completion 1 November 2026 (v22 review) |
| NCT07533786 | Haisco HSK55718: primary completion 22 November 2026 (v22 review) |
| NCT06050122 (Sol-Gel patidegib) | completed 20 August 2026, topline guided for late November 2026 (v25 review) |
| NCT07281937 (Verdiva EVOLVE-2) | completed July 2026, data 'being assessed' (14 October), topline due by end of 2026 (v25 review) |
| NCT04976634 (Merck MK-6482-016) | a snippet says the EU part ended 16 June 2026; the record says active, primary completion 2027-03 (v25 review, unverified) |
| NCT06873035 (BridgeBio ACCEL 2/3) | data guided for 2H 2026, none in the Q3 report |
| NCT06664619 (Teva) | one calendar site lists a phase 3 readout on 19 September 2026 |
| NCT06465186 (MSD efinopegdutide, MASH cirrhosis; v27) | MSD presents a Phase 2b of efinopegdutide at AASLD, 5–9 November; the staged record differs from the reported one (NCT05877547): check whether the presentation covers this trial |
| NCT07021976 (Hengrui/Suncadia HRS-1893, oHCM; v27) | 52-week extension data at AHA on 6 November; check whether it reports this trial's primary |
| NCT06602258 (Eisai E2814) and NCT06268886 (BMS-986446) (v27) | CTAD 2026 runs in early December; recheck the programme |
| NCT07269717 (Hengrui HRS-1893 Phase 2; v28) | watch the AHA 6 November HRS-1893 materials alongside NCT07021976 |
| Every haematology trial in the round (v28) | ASH 2026 regular abstracts go online on 4 November, 15:00 CET: search the abstract site for each haematology trial's drug and NCT number that day |
| NCT06557772 (Sanofi amlitelimab, celiac disease; v28) | Sanofi said in July the Phase 2 reads out in the second half of 2026 |
| NCT06727565 (Gilead VELOCITY-HNSCC substudy, domvanalimab; v28) | Gilead and Arcus ended the gastric and lung domvanalimab trials (Dec 2025, Apr 2026); this head and neck substudy is not named as stopped |

If any of them has a public result, note the trial, the link and the date. The other trials below the bar (`3_round1/launch_inputs/below_bar.jsonl`) are where a missed result is most likely; a quick look at any of them helps.

## If you want to recheck trials yourself

`final_check_deep_instructions.md` is the task given to every checking agent, and `check_results_rows.py` (with
`results_gate.py` beside it) tells whether a set of output rows meets the bar: run it with `--records` (the round's
records) and `--checked-from 2026-10-29`.
