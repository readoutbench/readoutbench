"""Therapeutic area of a registry record, from its conditions, title and interventions.

Keyword rules, first match wins, in the order of AREAS. Kept simple on purpose: the tagging check
compares it with a reader's call on a sample, and the leftovers land in "other" for a look by hand.
"""
import re

AREAS = [
    ("cancer", r"cancer|carcinom|tumou?r|neoplas|lymphoma|leuka?emia|myeloma|sarcoma|melanoma|gliom|glioblastom"
               r"|blastoma\b|mesotheliom|myelodysplas|myelofibros|polycyth[ae]mia|metasta|malignan|oncolog|nsclc|sclc"
               r"|waldenstr|macroglobulin|\bgist\b|neuroendocrine|\baml\b|\bcll\b|\bmds\b|hodgkin|adenocarcinom"),
    ("infections and vaccines", r"infect|\bhiv\b|hepatitis [bcde]|\bhbv\b|\bhcv\b|influenza|covid|sars-cov|\brsv\b"
               r"|respiratory syncytial|pneumonia|sepsis|septic|tubercul|malaria|vaccin|bacter|fung|viral\b|virus|herpes"
               r"|zoster|\bcmv\b|cytomegalovir|dengue|clostridi|pneumococc|meningococc|papillomavir|\bhpv\b|candid"
               r"|onychomycos|\buti\b|chikungunya|mpox|monkeypox|ebola|cholera|typhoid|shigell|pertussis|rotavir"
               r"|norovir|helicobacter|babesi|\bprep\b|pre-exposure prophylaxis|syphilis|gonorrh|chlamydia|leishmani|schistosom|helminth|parasit|antibiotic"),
    ("blood (not cancer)", r"an(a)?emia|sickle|thalass|ha?emophilia|thrombocytopeni|paroxysmal nocturnal|\bpnh\b"
               r"|von willebrand|neutropeni|iron deficien|iron overload|hemoly|haemoly|aplastic|hemoglobin|haemoglobin"
               r"|transfusion|light chain amyloid|al amyloid"),
    ("eyes", r"macular|retin|glaucom|uveitis|dry eye|myopi|kerat|ocular|conjunctiv|cataract|presbyopi|blephar"
               r"|eye\b|vision|optic neur|diabetic macular"),
    ("women's health and pregnancy", r"endometrios|uterine fibroid|leiomyom|menopaus|hot flash|vasomotor|pregnan"
               r"|preterm|pre-?eclamps|infertil|contracept|polycystic ovar|postpartum|labou?r induction|vaginos"
               r"|vulvovagin|heavy menstrual|dysmenorrh|ovarian hyperstim|in vitro fertil|\bivf\b|lactation|cesarean|caesarean|labou?r|vaginitis|obstetric"),
    ("mental health and addiction", r"depress|schizophren|bipolar|anxiety|panic|post-?traumatic|\bptsd\b|\badhd\b"
               r"|attention deficit|autis|insomnia|alcohol use|alcohol depend|opioid.use|opioid depend|personality disorder|smoking|cigarette|demoraliz|smoking cessation"
               r"|tobacco|nicotine|cocaine|methamphetamine|cannabis use|binge|obsessive|agitation|psychos|suicid"
               r"|anorexia nervosa|bulimia|tourette|postpartum depress|substance use|gambling|delirium"),
    ("brain and nerves", r"alzheimer|dementia|parkinson|epilep|seizure|migraine|headache|multiple sclerosis"
               r"|amyotrophic|\bals\b|neuropath|huntington|ataxia|stroke|spinal muscular|myasthenia|narcolepsy|tremor"
               r"|rett\b|dravet|lennox|brain injur|cognitive impair|neuromyelitis|cidp|polyneuropath|duchenne|dystroph"
               r"|cerebral|intracerebral|subarachnoid|neurodegener|spinal cord|restless legs|cluster headache|dyskinesia"
               r"|guillain|neuralgia|concussion|hydrocephal|friedreich|angelman|prader|consciousness|subdural|hematoma"),
    ("pain, anaesthesia and surgery", r"\bpain|analges|an(a)?esthe|nerve block|sedation|postoperative|post-operative"
               r"|surgery|surgical|perioperative|intraoperative|opioid-induced|nausea and vomiting|\bponv\b|incision"
               r"|arthroplasty|bunionectomy|herniorrhaphy|cholecystectomy|tonsillectomy|laparoscop"),
    ("heart and blood vessels", r"heart|cardi|coronary|myocard|atrial|hypertension|hypercholesterol|dyslipid"
               r"|lipoprotein|\bldl\b|thrombo|embolism|aort|peripheral arter|vascular|angina|arrhythm|ventricular"
               r"|hyperlipid|atheroscl|venous|varicose|claudication|raynaud|vasculopath|fontan|telangiectasia"),
    ("kidney and urinary", r"kidney|renal|nephr|dialysis|iga\b|fsgs|glomerul|overactive bladder|urinary|bladder"
               r"|prostatic hyperplasia|\bbph\b|cystitis|hyperkal|hyperphosphat|incontinence|nocturia|urolith|polycystic kidney|enuresis|erectile|ejaculation"),
    ("immune and joints", r"rheumatoid|arthritis|spondyl|lupus|sj[oö]gren|vasculitis|myositis|systemic sclerosis"
               r"|scleroderma|gout|polymyalgia|giant cell arter|igg4|sarcoidos|beh[cç]et|still'?s disease|autoimmun"
               r"|antiphospholipid|dermatomyositis|graft.versus.host|\bgvhd\b|transplant|immune-mediated|allerg|angioedema|anaphyla|vexas|mastocytos"),
    ("skin", r"dermatitis|eczema|psoria|acne|hidradenitis|vitiligo|alopecia|urticaria|prurigo|pemphig|rosacea"
               r"|keloid|wound|foot ulcer|leg ulcer|pressure ulcer|epidermolysis|pruritus|itch|skin|cutaneous|hyperhidros"
               r"|actinic|scar|burn\b|burns\b|photoaging|cellulite|melasma|ichthyos|glabellar|wrinkle|pustulos|pseudoxanthoma"),
    ("liver and gut", r"liver|hepat|cirrho|steatohepat|\bnash\b|\bmash\b|fatty liver|biliar|cholang|crohn|colitis"
               r"|bowel|celiac|coeliac|esophag|oesophag|gastr|pancreatit|constipation|\bibs\b|diverticul|dyspeps"
               r"|reflux|\bgerd\b|short bowel|anal fissure|hemorrhoid|haemorrhoid|cholestas|portal hypertension|ascites"
               r"|colonoscopy|bowel prep|fecal|faecal|duoden|ileus"),
    ("lungs and airways", r"asthma|copd|chronic obstructive|pulmonary|lung|bronch|cystic fibrosis|rhinitis|sinusitis"
               r"|nasal polyp|cough|sleep apnea|sleep apnoea|respiratory distress|\bards\b|emphysema|interstitial|airway"
               r"|alpha-1 antitrypsin|tracheal|wheez"),
    ("diabetes, obesity and metabolism", r"diabet|obes|overweight|weight|glyc|insulin|hypertriglycerid|hypoglyc"
               r"|metabolic|lipodystroph|phenylketon|fabry|gaucher|pompe|mucopolysacch|hypophosphat|homocystin|urea cycle"
               r"|hyperammon|thyroid|growth hormone|acromegal|cushing|adrenal|hypogonad|hypoparathyr|hyperparathyr"
               r"|vitamin d|osteomalacia|achondroplas|short stature|endocrin|wilson|malnutrition|wasting|nutrition"),
    ("bones and muscles", r"osteopor|osteoarthr|fracture|sarcopeni|bone|muscle|tendin|tendon|back pain|fibromyalg"
               r"|rotator|ligament|cartilage|musculoskeletal|osteogenesis|spine|osteonecros|dupuytren|chondroplas"),
    ("ear, nose, throat and mouth", r"caries|gingiv|periodont|dental|tooth|teeth|oral lichen|xerostom|hearing|tinnitus|otitis"
               r"|pharyng|laryng|vertigo|m[eé]ni[eè]re|tonsil|mucositis|halitosis|denti"),
]
_RX = [(a, re.compile(p, re.I)) for a, p in AREAS]


def area(rec):
    """First matching area for a record with conditions, title and interventions; 'other' if none."""
    text = " | ".join([" ; ".join(rec.get("conditions") or []), str(rec.get("title") or ""),
                       " ; ".join(rec.get("interventions") or [])])
    cond = " ; ".join(rec.get("conditions") or [])
    for a, rx in _RX:              # conditions decide first
        if rx.search(cond):
            return a
    for a, rx in _RX:              # then the title and interventions
        if rx.search(text):
            return a
    return "other"
