#!/usr/bin/env python3
"""Fetch live Eagles/NFL data into data/*.json. Each source is independent:
if one fails, its previous file is kept untouched. Cap data is NOT fetched
(no free source); it lives in data/cap_manual.json and is edited by hand."""
import csv, io, json, os, sys, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
SEASON = int(os.environ.get("SEASON") or (lambda d: d.year if d.month >= 3 else d.year - 1)(__import__("datetime").date.today()))  # derived from date
UA = {"User-Agent": "eagles-gm-lab-live/1.0 (personal demo; github.com/mkuritz)"}
ESPN = "https://site.api.espn.com/apis"
NFLV = "https://github.com/nflverse/nflverse-data/releases/download"


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def jget(url):
    return json.loads(get(url))


def now_et():
    return datetime.now(timezone.utc).astimezone(ET).isoformat(timespec="seconds")


def path(name):
    return os.path.join(DATA, name)


def write(name, payload):
    """Write only if content (excluding timestamp) changed, so commits happen only on change."""
    p = path(name)
    old = None
    if os.path.exists(p):
        try:
            old = json.load(open(p))
        except Exception:
            old = None
    if old is not None and old.get("data") == payload:
        return False
    json.dump({"updated": now_et(), "data": payload}, open(p, "w"), indent=1, sort_keys=True)
    return True


# ---------------- sources ----------------
def espn_roster():
    j = jget(f"{ESPN}/site/v2/sports/football/nfl/teams/phi/roster")
    out = []
    for g in j["athletes"]:
        for a in g["items"]:
            inj = (a.get("injuries") or [{}])[0]
            out.append({
                "espnId": a["id"], "name": a.get("fullName"), "pos": (a.get("position") or {}).get("abbreviation"),
                "group": g["position"], "age": a.get("age"), "exp": (a.get("experience") or {}).get("years"),
                "jersey": a.get("jersey"), "status": (a.get("status") or {}).get("name"),
                "injury": inj.get("status"), "injuryDate": inj.get("date"),
                "headshot": (a.get("headshot") or {}).get("href"),
            })
    if len(out) < 40:
        raise ValueError(f"roster too small ({len(out)})")
    return out


def espn_standings():
    j = jget(f"{ESPN}/v2/sports/football/nfl/standings")
    out = []
    for conf in j["children"]:
        for e in conf["standings"]["entries"]:
            st = {s["name"]: s.get("displayValue") for s in e["stats"]}
            num = lambda k: int(float(st.get(k) or 0))
            out.append({"abbr": e["team"]["abbreviation"], "name": e["team"]["displayName"],
                        "w": num("wins"), "l": num("losses"), "t": num("ties"),
                        "pf": num("pointsFor"), "pa": num("pointsAgainst"), "streak": st.get("streak"),
                        "seed": st.get("playoffSeed"), "conf": conf.get("abbreviation") or conf.get("name")})
    if len(out) != 32:
        raise ValueError(f"expected 32 teams, got {len(out)}")
    return out


def espn_schedule():
    j = jget(f"{ESPN}/site/v2/sports/football/nfl/teams/phi/schedule")
    out = []
    for e in j["events"]:
        c = e["competitions"][0]
        teams = []
        for x in c["competitors"]:
            sc = x.get("score")
            sc = sc.get("displayValue") if isinstance(sc, dict) else sc
            teams.append({"abbr": x["team"]["abbreviation"], "homeAway": x.get("homeAway"), "score": sc, "winner": x.get("winner")})
        out.append({"week": (e.get("week") or {}).get("number"), "date": e.get("date"), "name": e.get("shortName"),
                    "status": c["status"]["type"].get("description"), "completed": c["status"]["type"].get("completed"), "teams": teams})
    return out


def nflverse_csv(url, team_col="team", team="PHI"):
    txt = get(url, timeout=120).decode("utf-8")
    return [r for r in csv.DictReader(io.StringIO(txt)) if r.get(team_col) == team]


def nflverse_injuries():
    rows = nflverse_csv(f"{NFLV}/injuries/injuries_{SEASON}.csv")
    if not rows:
        raise ValueError("no PHI injury rows")
    wk = max(int(r["week"]) for r in rows if r["week"])
    return {"week": wk, "players": [{
        "name": r["full_name"], "pos": r["position"], "gsisId": r["gsis_id"],
        "injury": r["report_primary_injury"] or r["practice_primary_injury"],
        "gameStatus": r["report_status"], "practice": r["practice_status"]} for r in rows if r["week"] and int(r["week"]) == wk]}


def nflverse_depth():
    rows = nflverse_csv(f"{NFLV}/depth_charts/depth_charts_{SEASON}.csv")
    if not rows:
        raise ValueError("no PHI depth rows")
    # schema varies by year; keep the most recent snapshot by whatever date/week column exists
    key = next((k for k in ("dt", "week") if k in rows[0]), None)
    if key:
        last = max(r[key] for r in rows)
        rows = [r for r in rows if r[key] == last]
    keep = [k for k in ("dt", "week", "pos_grp", "pos_name", "pos_abb", "pos_slot", "pos_rank", "depth_team",
                        "depth_position", "position", "player_name", "full_name", "gsis_id", "espn_id", "formation") if k in rows[0]]
    return [{k: r[k] for k in keep} for r in rows]


def nflverse_contracts():
    import pyarrow.parquet as pq
    tbl = pq.read_table(io.BytesIO(get(f"{NFLV}/contracts/historical_contracts.parquet", timeout=180)),
                        columns=["player", "position", "team", "is_active", "year_signed", "years", "value", "apy", "guaranteed", "apy_cap_pct", "otc_id", "gsis_id"])
    out = [r for r in tbl.to_pylist() if r["team"] == "Eagles" and r["is_active"]]
    if not out:
        raise ValueError("no active Eagles contracts")
    out.sort(key=lambda r: (-(r["apy"] or 0), r["player"]))
    for r in out:
        for k, v in list(r.items()):
            if isinstance(v, float):
                r[k] = round(v, 3)
    return out


def sleeper_depth():
    """Sleeper asks for the full players dump at most once per day."""
    p = path("sleeper_depth.json")
    if os.path.exists(p):
        try:
            prev = json.load(open(p))["updated"]
            if datetime.fromisoformat(prev).date() == datetime.now(ET).date():
                return None  # already fetched today
        except Exception:
            pass
    j = jget("https://api.sleeper.app/v1/players/nfl")
    out = [{"name": v.get("full_name"), "pos": v.get("position"), "depthPos": v.get("depth_chart_position"),
            "depthOrder": v.get("depth_chart_order"), "injury": v.get("injury_status"), "espnId": v.get("espn_id"),
            "status": v.get("status")} for v in j.values() if v.get("team") == "PHI"]
    out.sort(key=lambda r: (r["depthPos"] or "ZZ", r["depthOrder"] or 99, r["name"] or ""))
    return out


SOURCES = [
    ("roster.json", "ESPN team roster", espn_roster),
    ("standings.json", "ESPN standings", espn_standings),
    ("schedule.json", "ESPN team schedule", espn_schedule),
    ("injuries.json", "nflverse injuries (official report)", nflverse_injuries),
    ("depth.json", "nflverse depth charts", nflverse_depth),
    ("contracts.json", "nflverse contracts (Over The Cap)", nflverse_contracts),
    ("sleeper_depth.json", "Sleeper players (depth backup, max 1/day)", sleeper_depth),
]


def main():
    os.makedirs(DATA, exist_ok=True)
    meta_p = path("meta.json")
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {"sources": {}}
    ok_any = False
    for fname, label, fn in SOURCES:
        s = meta["sources"].setdefault(fname, {})
        s["label"] = label
        try:
            payload = fn()
            if payload is None:
                print(f"skip  {fname} (fresh enough)")
                ok_any = True
                continue
            changed = write(fname, payload)
            s.update(ok=True, lastSuccess=now_et(), error=None)
            if changed:
                s["lastChange"] = now_et()
            ok_any = True
            print(f"ok    {fname} ({'changed' if changed else 'unchanged'})")
        except Exception as e:  # keep previous file
            s.update(ok=False, lastAttempt=now_et(), error=f"{type(e).__name__}: {e}"[:300])
            print(f"FAIL  {fname}: {e}", file=sys.stderr)
    meta["lastRun"] = now_et()
    meta["updated"] = max([v.get("lastChange") or "" for v in meta["sources"].values()] or [""]) or meta.get("updated")
    meta["timezone"] = "America/New_York"
    json.dump(meta, open(meta_p, "w"), indent=1, sort_keys=True)
    return 0 if ok_any else 1


if __name__ == "__main__":
    sys.exit(main())
