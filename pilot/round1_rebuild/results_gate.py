"""The results-check gate: when a trial's check rows let it stay in the round. Used by launch.py and
check_results_rows.py, so both apply the same bar.

A trial stays only when its latest check row is CLEAN:
- reported "no" and stop_announced "no" (anything else, "unclear" included, is not clean);
- at least `min_queries` distinct, non-empty searches;
- at least `min_opened` pages opened that are not ClinicalTrials.gov or a site that republishes its records (the
  instructions forbid them, and they cannot show a result the record does not);
- for a trial whose sites are all in China, Korea, Japan, Taiwan or Hong Kong, at least one search with three or more
  Chinese, Japanese or Korean characters (the sponsor's own announcements are often only there);
- searches counted once after lower-casing and dropping punctuation; a search-engine results page or a trial
  aggregator does not count as an opened page;
- checked on or after `checked_from` (the day the records were pulled), as a YYYY-MM-DD date, and not after today;
- notes that do not flag the row for review (UNSURE, HIGHEST RISK, REVIEW), unless the organiser signed it off.
A FINDING in any row (reported "yes" or "stopped_without_result", or a stop announced) sticks: a later "no" does not
undo it. Everything else is SHALLOW (checked, but not to the bar) or MISSING (no row).
"""
import datetime as _dt
import json
import re
import unicodedata
from urllib.parse import urlparse

MIRRORS = ("clinicaltrials.gov", "ichgcp.net", "trial.medpath.com", "medpath.com", "tundraspace.com", "plaintrial.com",
           "findatrial", "ctv.veeva.com", "syfrah", "datalookout", "withpower.com", "clinicaltrialsregister.eu",
           "trialx.com", "centerwatch.com", "antidote.me", "clinconnect.io", "clinicaltrials.ucdavis.edu",
           "trials.cancer.gov", "dailymed", "veeva.com", "biopharmcatalyst.com/trial", "patsnap", "trialsearch.who.int",
           "who.int/trialsearch", "pharmacompass", "clinicaltrialsarena.com/projects", "drugbank", "chictr.org.cn",
           "jrct.niph.go.jp", "cris.nih.go.kr", "euclinicaltrials.eu", "isrctn.com", "anzctr.org.au", "ctri.nic.in",
           "drugs.ncats.io", "go.drugbank", "pharnexcloud.com", "so.com", "globaldata.com", "clinicaltrials.eu",
           "yaozh.com", "drugs.com", "clinicaltrialsgps", "adisinsight", "hra.nhs.uk", "finviz.com", "citeline.com",
           "pharmaceutical-technology.com", "itiger.com", "sec.gov", "biopharmcatalyst.com", "trialtrove",
           "clinicaltrials.ucdavis.edu", "medpath.com", "clinregs", "trialbulletin", "mtec-sc.org", "kalkinemedia.com",
           "web.archive.org", "archive.org", "archive.ph", "archive.today", "finance.yahoo.com", "marketscreener.com",
           "stocktitan.net", "sohu.com", "163.com", "businesswire.com/news/home/search", "globenewswire.com/search",
           # trial registries and listings, including sponsors' own trial sites (they show what the registry shows)
           "ctis.eu", "astrazenecaclinicaltrials.com", "gsk-studyregister.com", "forpatients.roche.com",
           "abbvieclinicaltrials.com", "trials.otsuka-us.com", "jrct.mhlw.go.jp", "onderzoekmetmensen.nl",
           "globaltrialfinder.janssen.com", "xogene.com", "trialstracker.net", "trials.braintumor.org", "whichtrial.com",
           "anzchog.org", "flcube.com", "larvol.com", "biopharmawatch.com", "ai-analytics.org", "db.antibodysociety.org",
           "jnjmedicalconnect.com", "wikipedia.org",
           # stock-quote, investor-forum and summary sites that repost others' news
           "tipranks.com", "marketbeat.com", "filingreader.com", "quartr.com", "webull.com", "moomoo.com", "barchart.com",
           "zacks.com", "pulse.bot", "allmind.ai", "rallies.ai", "briefglance.com", "pages.dev", "appliedxl.com",
           "usmartglobal.com", "quantisnow.com", "biotechhunter.com", "10jqka.com.cn", "abcbourse.com", "fortuneo.fr",
           "placera.se", "stockstar.com", "cfi.cn", "gelonghui.com",
           "umin.ac.jp", "drks.de", "irct.ir", "irct.behdasht.gov.ir", "jrct.niph.go.jp", "rctportal.niph.go.jp",
           "prnewswire.com/search", "prnewswire.com/news-releases/search", "eastmoney.com", "dfcfw.com", "xueqiu.com", "futunn.com/stock",
           "investing.com/equities", "seekingalpha.com/symbol")
SEARCH = ("google.", "bing.com", "duckduckgo.com", "baidu.com", "search.yahoo", "yandex.", "naver.com/search",
          "sogou.com")
FAILED = ("refused", "failed", "blocked", "robots", "403", "404", "http 500", "status 500", "nothing retrieved", "not retrieved", "error",
          "timed out", "timeout", "empty", "could not load", "couldn't load", "could not be loaded", "access denied",
          "paywall", "unavailable", "captcha", "did not load", "didn't load", "no usable content", "no content", "redirect script",
          "returned only a redirect")
EAST_ASIA = {"China", "Korea, Republic of", "South Korea", "Japan", "Taiwan", "Hong Kong"}
FLAGS = re.compile(r"\b(UNSURE|HIGHEST RISK|NEEDS? REVIEW|REVIEW)\b"
                   r"|(?i:\bunsure\b|needs? (a )?(review|re-?check)|re-?check (this|it|before|soon|or)|or leave (it )?out"
                   r"|leave it out|reviewer should|reviewer's eye|reviewer may|re-?check|(cannot|could not|can't) (be )?(rule[ds]? out|excluded?)"
                   r"|cannot be (ruled out|excluded)|weak check|low confidence)")   # the agent's own call for a person to look
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def _date_ok(s):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s)):
        return False
    try:
        _dt.date.fromisoformat(str(s))
        return True
    except ValueError:
        return False


def _norm(q):
    """A search, lower-cased with punctuation and spacing removed, so trivial variants count once."""
    q = unicodedata.normalize("NFKC", q).lower()
    words = re.sub(r"[\W_]+", " ", q, flags=re.UNICODE).split()
    return " ".join(sorted(set(words)))       # word order and repeated words do not make a new search


def _match(host, url, m):
    """A mirror entry matches by domain ("ichgcp.net" matches ichgcp.net and its subdomains), by a name inside the
    host when it has no dot ("patsnap" matches synapse.patsnap.com), or by domain and path ("who.int/trialsearch")."""
    if "/" in m:
        dom, path = m.split("/", 1)
        return (host == dom or host.endswith("." + dom) or dom in host) and "/" + path in url
    if "." in m:
        return host == m or host.endswith("." + m)
    return m in host


def is_finding(r):
    return r.get("reported") in ("yes", "stopped_without_result") or r.get("stop_announced") == "yes"


def opened_pages(r):
    out = set()
    for x in r.get("pages_checked") or []:
        if not isinstance(x, str) or not x.startswith("opened:"):
            continue
        rest = x[len("opened:"):].strip()
        url = rest.split()[0] if rest.split() else ""
        note = rest[len(url):].lower()               # what the agent wrote after the URL
        if any(w in note for w in FAILED):          # a fetch that returned nothing is not an opened page
            continue
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        mirror = any(_match(host, url.lower(), m) for m in MIRRORS)
        if not host or mirror or any(s in host for s in SEARCH) or "/search?" in url.lower():
            continue
        out.add(url)
    return out


SAFETY_WORDS = re.compile(r"(?i)well[- ]tolerated|favou?rable safety|safety profile|no (new |major |unexpected )?safety (signals?|concerns?|issues?)"
                          r"|safe and (well )?tolerated|positive safety review|no safety concerns|generally safe")
# (Chinese, Japanese and Korean wording: SAFETY_CJK below)
SAFETY_PRIMARY = re.compile(r"(?i)adverse|safety|tolerab|TEAE|side effect|toxicit|dose[- ]limiting|\bDLT|immunogenic"
                            r"|antibod|pharmacokinetic|\bPK\b|Cmax|AUC")


def safety_primary(record):
    """True when a registered primary outcome is a safety, tolerability, PK or immune-response measure."""
    return any(SAFETY_PRIMARY.search(str(o.get("measure") or "")) for o in (record or {}).get("primary_outcomes") or [])


# Chinese (simplified and traditional), Japanese and Korean: no phrase list. Four review rounds showed that judgement
# wording in these languages is open-ended (each new probe set found new misses at the same rate), and a miss lets a
# trial through. So any safety, tolerability or adverse-event word counts as a safety mention: on a trial with a
# safety primary it needs the organiser's sign-off (signed_off.jsonl), whatever it says. On the round as built this
# raised no trial (no check row of a safety-primary trial carried such a word), so it costs no sign-offs today.
# Matched after spaces are taken out (이상 반응, and PDF text such as "安 全 性"). In a string that holds any CJK, the
# Latin adverse-event abbreviations count too when written inside CJK wording (SAE发生率低, TEAE均为1级, TRAEs 발생률),
# which the English list does not match.
SAFETY_CJK = re.compile(r"安全|耐受|耐容|忍容|不良(反应|反應|事件|事象)|有害(事象|反応|反應)|副作用|副反应|副反應|反应原性|反應原性"
                        r"|毒性|안전|내약|이상(반응|사례)|유해(사례|반응)|부작용|독성")
_CJK_ANY = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
_AE_ABBR = re.compile(r"(?<![A-Za-z])(T?E?AEs?|SAEs?|TRAEs?|irAEs?|AESIs?|ADRs?|DLTs?)(?![A-Za-z])")
_SPACES = re.compile(r"[\s\u3000]+")


def has_safety_words(text):
    """True when English text holds a safety statement ("well tolerated", "no new safety signals"...) or Chinese,
    Japanese or Korean text mentions safety, tolerability or adverse events at all (安全, 耐受, 忍容, 不良反应, 副反应,
    有害事象, 副作用, 안전, 내약, 이상 반응, 유해사례..., or AE, SAE, TEAE, TRAE in a string with CJK in it)."""
    text = str(text or "")
    if SAFETY_WORDS.search(text):
        return True
    if not _CJK_ANY.search(text):
        return False
    if SAFETY_CJK.search(_SPACES.sub("", text)):
        return True
    # an abbreviation counts when it sits inside CJK wording (CJK within four characters), not when an English
    # sentence that names the primary ("TEAEs") only happens to carry a Chinese company name elsewhere
    return any(_CJK_ANY.search(text[max(0, m.start() - 4):m.end() + 4]) for m in _AE_ABBR.finditer(text))


def load_signed_off(path, trials=None):
    """The organiser's sign-offs (signed_off.jsonl): {nct_id: date}. Each line needs an nct_id (of the round, when
    `trials` is given), a non-empty reason and a date (YYYY-MM-DD); a trial listed twice keeps its latest date. A sign-off
    covers the check rows dated on or before it: a newer row with a safety mention or a review flag needs a new one."""
    out, known = {}, set(trials) if trials is not None else None
    for i, line in enumerate(open(path, encoding="utf-8-sig"), 1):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"signed_off line {i}: not valid JSON ({e.msg})") from None
        nid = str(o.get("nct_id") or "").strip().upper() if isinstance(o, dict) else ""
        if not nid or (known is not None and nid not in known):
            raise ValueError(f"signed_off line {i}: {nid or 'no nct_id'} is not a trial of this round")
        if not (isinstance(o.get("reason"), str) and o["reason"].strip()):
            raise ValueError(f"signed_off line {i}: {nid} needs a reason")
        if not _date_ok(o.get("date")):
            raise ValueError(f"signed_off line {i}: {nid} needs a date as YYYY-MM-DD")
        out[nid] = max(out.get(nid, ""), o["date"])
    return out


def _signed(nid, row_date, signed_off):
    """True when the trial's sign-off covers a row of that date. A plain set of IDs (no dates) covers every row."""
    if isinstance(signed_off, dict):
        d = signed_off.get(nid)
        return d is not None and bool(row_date) and str(row_date) <= d
    return nid in signed_off


_NOT_SCANNED = {"queries", "nct_id", "checked_on", "check", "checked_utc"}   # our own search words and bookkeeping


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def safety_text(r):
    """True when a safety statement appears anywhere in a row's own words: every string value of the row, nested
    ones included (notes, quote, result, summary, snippets and page notes in pages_checked, source URLs...), except
    the queries we ran and bookkeeping fields."""
    return any(has_safety_words(t) for k, v in r.items() if k not in _NOT_SCANNED for t in _strings(v))


def why_not_clean(r, record=None, min_queries=2, min_opened=1, checked_from=None, signed_off=(), safety_seen=False):
    """None when the row is clean; else a short reason. A row whose notes flag it for review (UNSURE, HIGHEST RISK,
    REVIEW, in capitals) is clean only when its trial is in `signed_off` (the organiser's recorded decisions)."""
    if r is None:
        return "no check row"
    # read before every other reason (an "unchecked" status, a shallow or flagged row), so that none can hide it;
    # a real finding ("yes") is caught by is_finding/classify before this function is consulted
    # `safety_seen`: a statement in an earlier row of the same trial (any file), so a later clean row cannot hide it
    # (with dated sign-offs, safety_seen is the date of the newest earlier row with a mention, or True)
    newest = max([d for d in (safety_seen if isinstance(safety_seen, str) else None,
                               r.get("checked_on") if safety_text(r) else None) if d] or [""])
    if (record is not None and safety_primary(record) and (safety_seen or safety_text(r))
            and not _signed(r.get("nct_id"), newest or (None if safety_seen is True else r.get("checked_on")), signed_off)):
        return "a safety statement noted on a trial with a safety primary, not signed off"
    if r.get("reported") != "no" or r.get("stop_announced") != "no":
        return f"reported {r.get('reported')}, stop {r.get('stop_announced')}"
    q, pg = r.get("queries"), r.get("pages_checked")
    if not isinstance(q, list) or not isinstance(pg, list):
        return "queries or pages_checked is not a list"
    qs = {_norm(x) for x in q if isinstance(x, str) and _norm(x)}
    if len(qs) < min_queries:
        return f"{len(qs)} searches"
    if len(opened_pages(r)) < min_opened:
        return "no page opened beyond the registry and its mirrors"
    if record is not None:
        countries = set(record.get("countries") or [])
        if countries and countries <= EAST_ASIA and not any(len(CJK.findall(x)) >= 3 for x in qs):
            return "no search in the sponsor's language"
    if FLAGS.search(str(r.get("notes") or "")) and not _signed(r.get("nct_id"), r.get("checked_on"), signed_off):
        return "flagged for review by the checking agent, not signed off"
    if checked_from is not None:
        today = _dt.date.today().isoformat()
        if (not _date_ok(r.get("checked_on")) or str(r.get("checked_on")) < checked_from
                or str(r.get("checked_on")) > today):
            return f"checked on {r.get('checked_on')}"
    return None


def classify(rows_by_file, records=None, ids=None, **bar):
    """rows_by_file: lists of rows, oldest first. Returns {nct_id: ("finding" | "clean" | "shallow" | "missing",
    reason)} for `ids` (default: every trial with a row)."""
    latest, found, seen = {}, {}, {}
    for rows in rows_by_file:
        for r in rows:
            n = r.get("nct_id")
            latest[n] = r
            if is_finding(r):
                found.setdefault(n, r)
            if safety_text(r):
                d = r.get("checked_on")                     # the newest dated mention; an undated one: True
                seen[n] = True if (seen.get(n) is True or not _date_ok(d)) else max(seen.get(n, ""), str(d))
    out = {}
    for n in (ids if ids is not None else list(latest)):
        if n in found:
            out[n] = ("finding", f"{found[n].get('reported')}, stop {found[n].get('stop_announced')}")
        elif n not in latest:
            out[n] = ("missing", "no check row")
        else:
            why = why_not_clean(latest[n], (records or {}).get(n), safety_seen=seen.get(n, False), **bar)
            out[n] = ("clean", None) if why is None else (
                "missing" if latest[n].get("reported") == "unchecked" else "shallow", why)
    return out
