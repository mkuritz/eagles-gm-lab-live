"""Shared helpers for the free-source cross-check (data/xcheck.json). Every source is optional."""
import csv, gzip, io, json, os, re, time, datetime as dt
from urllib.request import Request, urlopen
UA = {"User-Agent": "Mozilla/5.0 (SportsLabs data refresh; +https://sportslabshq.com/)"}

# Public JSON/README copy. Internal fetch URLs and code identifiers may still name a feed.
_NEU = (
    (re.compile(r"Pro[- ]Football[- ]Reference", re.I), "stats reference"),
    (re.compile(r"\bPFR\b"), "stats reference"),
    (re.compile(r"Next Gen Stats", re.I), "tracking data"),
    (re.compile(r"\bNGS\b"), "tracking data"),
    (re.compile(r"\bnflverse\b", re.I), "public stats"),
    (re.compile(r"\bffverse\b", re.I), "public stats"),
    (re.compile(r"\bnflreadr\b", re.I), "public stats"),
    (re.compile(r"\bffopportunity\b", re.I), "expected points model"),
    (re.compile(r"Over The Cap", re.I), "public contract data"),
    (re.compile(r"\bSleeper\b"), "second depth source"),
    (re.compile(r"\bESPN\b"), "league feed"),
    (re.compile(r"\bYahoo(?: Sports)?\b", re.I), "analyst consensus"),
)
_VENDOR_URL = re.compile(
    r"nflverse|ffverse|nflreadr|ffopportunity|overthecap|sleeper\.app|site\.api\.espn|"
    r"pro-football-reference|profootballreference",
    re.I,
)

def neutralize(text):
    """Replace vendor/source product names in public-facing copy. Leaves non-strings alone."""
    if not isinstance(text, str):
        return text
    for pat, rep in _NEU:
        text = pat.sub(rep, text)
    return text

def public_url(link):
    if not link or _VENDOR_URL.search(str(link)):
        return None
    return link

def neutralize_public(obj, url_key="url"):
    """Walk a public payload: neutralize strings, drop vendor URLs. Does not rename keys."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == url_key:
                out[k] = public_url(v)
            else:
                out[k] = neutralize_public(v, url_key=url_key)
        return out
    if isinstance(obj, list):
        return [neutralize_public(x, url_key=url_key) for x in obj]
    if isinstance(obj, str):
        return neutralize(obj)
    return obj

class Src:
    def __init__(s): s.list = []
    def get(s, name, url, what, fn, link=None, new=True):
        t = time.time()
        try:
            v = fn(); n = len(v) if hasattr(v, "__len__") else None
            s.list.append(dict(name=neutralize(name), url=public_url(link), status="ok" if n else "empty", rows=n, what=neutralize(what), new=new)); return v
        except Exception as e:
            s.list.append(dict(name=neutralize(name), url=public_url(link), status="failed", err=str(e)[:90], what=neutralize(what), new=new)); return None
        finally: time.sleep(0.5)
def fetch(url, timeout=60, hdr=None):
    with urlopen(Request(url, headers=hdr or UA), timeout=timeout) as r: b = r.read()
    if url.endswith(".gz") or b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
    return b
def js(url, **k): return json.loads(fetch(url, **k))
def rows(url, **k): return list(csv.DictReader(io.StringIO(fetch(url, **k).decode("utf-8-sig"))))
def f(x, d=None):
    try: return float(x)
    except Exception: return d
def norm(n):
    import re, unicodedata
    n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[.'’,-]", " ", n); n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", n)
    return " ".join(n.split())
def verdict(rel, tol=0.15, hard=0.30):
    a = abs(rel); return "agree" if a <= tol else ("watch" if a <= hard else "disagree")
def write(path, title, src, tables, summary):
    old = {}
    if os.path.exists(path):
        try: old = json.load(open(path))
        except Exception: pass
    # degrade gracefully: if a table came back empty because its source failed, keep the previous one
    names = {t["title"] for t in tables if t["rows"]}
    for t in old.get("tables", []):
        if t["title"] not in names and not any(x["title"] == t["title"] and x["rows"] for x in tables):
            t["note"] = (t.get("note") or "").split(" (kept from previous")[0] + " (kept from previous refresh: source unavailable this run)"
            tables = [x for x in tables if x["title"] != t["title"]] + [t]
    payload = dict(title=title, generated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   sources=src.list, tables=tables, summary=summary)
    json.dump(neutralize_public(payload), open(path, "w"), separators=(",", ":"))
