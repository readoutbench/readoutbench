You are taking part in a research benchmark on oncology decision support. You will read the case of a patient with advanced cancer at the moment the next line of systemic therapy is being chosen, including the biomarker tests done so far.

Recommend the next systemic treatment. If information that would change your recommendation is missing, set `needs_info_first` to true and list the missing information in `info_needed`, using the IDs from this menu; otherwise set `needs_info_first` to false and leave `info_needed` empty.

- EGFR: EGFR mutation
- ALK: ALK fusion
- ROS1: ROS1 fusion
- BRAF: BRAF V600E mutation
- KRAS: KRAS mutation (including G12C)
- NRAS: NRAS mutation
- MET: MET exon 14 skipping
- RET: RET fusion
- NTRK: NTRK1/2/3 fusion
- NRG1: NRG1 fusion
- ERBB2_MUT: HER2 (ERBB2) mutation
- HER2: HER2 protein or amplification (IHC/ISH)
- ER_PR: Hormone receptor status (ER/PR)
- PI3K: PIK3CA, AKT1 or PTEN alteration
- ESR1: ESR1 mutation
- HRR_TUMOR: BRCA1/2 or other homologous-recombination repair genes in the tumour
- GERMLINE: Germline (inherited) cancer-gene testing
- MSI: Microsatellite instability or mismatch-repair status
- TMB: Tumour mutational burden
- PDL1: PD-L1 expression
- FGFR: FGFR2 or FGFR3 alteration
- IDH1: IDH1 mutation
- KIT: KIT or PDGFRA mutation
- CLDN18: Claudin 18.2 expression

Reply with one JSON object only, no other text:

{"case_id": "<case id>", "needs_info_first": false, "info_needed": [], "recommendation": "<the regimen, or what you would do once the missing results are back>"}
