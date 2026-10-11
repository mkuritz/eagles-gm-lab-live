#!/usr/bin/env python3
"""Stat-based Performance Score for every NFL player (output: data/performance.json).

Sources (all free, nflverse-data GitHub releases): season player stats (stats_player_reg_YYYY),
weekly snap counts (PFR via nflverse), PFR advanced defense (coverage / pass rush / tackling).

Score (0-100) = 50% CURRENT (this season's rate stats, percentile vs position peers)
              + 50% TALENT (same rate stats over a 3-season window, shrunk toward the
                position median by sample size: w = snaps / (snaps + K)).
If the current sample is thin, CURRENT is itself shrunk toward TALENT, so an injured player
with elite per-snap history is not buried by low totals. Availability (share of team games
played in the window) is reported separately as an injury-risk flag; it is NOT in the score.
No grades, no film ratings: only public box-score / charting stats. OL have no free
per-player blocking stats, so OL get no score (availability/snap share only)."""
import csv, io, json, os, re, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SEASON = int(os.environ.get("SEASON", "2026"))
WINDOW = [SEASON - 2, SEASON - 1, SEASON]
B = "https://github.com/nflverse/nflverse-data/releases/download"
CACHE = os.environ.get("NFLV_CACHE")

POSMAP = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE",
          "T": "OL", "G": "OL", "C": "OL", "OT": "OL", "OG": "OL", "OL": "OL", "LT": "OL", "RT": "OL", "LG": "OL", "RG": "OL",
          "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL",
          "LB": "LB", "OLB": "LB", "ILB": "LB", "MLB": "LB",
          "CB": "CB", "S": "S", "FS": "S", "SS": "S", "SAF": "S", "K": "K", "P": "P"}

# metric: (label, higher_is_better, fn(row)->value or None). Rows hold summed season stats.
def d(a, b):
    return a / b if b else None

METRICS = {
 "QB": [("EPA per dropback+rush", 1, lambda r: d(r["passing_epa"] + r["rushing_epa"], r["attempts"] + r["sacks_suffered"] + r["carries"])),
        ("Adj. net yds/att", 1, lambda r: d(r["passing_yards"] + 20 * r["passing_tds"] - 45 * r["passing_interceptions"] - r["sack_yards_lost"], r["attempts"] + r["sacks_suffered"])),
        ("CPOE", 1, lambda r: d(r["cpoe_w"], r["attempts"])),
        ("INT rate", 0, lambda r: d(r["passing_interceptions"], r["attempts"]))],
 "RB": [("Rush EPA/carry", 1, lambda r: d(r["rushing_epa"], r["carries"])),
        ("Yds/carry", 1, lambda r: d(r["rushing_yards"], r["carries"])),
        ("Scrimmage yds/snap", 1, lambda r: d(r["rushing_yards"] + r["receiving_yards"], r["off_snaps"])),
        ("TDs/snap", 1, lambda r: d(r["rushing_tds"] + r["receiving_tds"], r["off_snaps"]))],
 "WR": [("Rec yds/snap", 1, lambda r: d(r["receiving_yards"], r["off_snaps"])),
        ("Rec EPA/target", 1, lambda r: d(r["receiving_epa"], r["targets"])),
        ("Targets/snap", 1, lambda r: d(r["targets"], r["off_snaps"])),
        ("Catch rate", 1, lambda r: d(r["receptions"], r["targets"]))],
 "TE": [("Rec yds/snap", 1, lambda r: d(r["receiving_yards"], r["off_snaps"])),
        ("Rec EPA/target", 1, lambda r: d(r["receiving_epa"], r["targets"])),
        ("Targets/snap", 1, lambda r: d(r["targets"], r["off_snaps"]))],
 "DL": [("Pressures/snap", 1, lambda r: d(r["pfr_pressures"], r["def_snaps"])),
        ("Sacks/snap", 1, lambda r: d(r["def_sacks"], r["def_snaps"])),
        ("TFL/snap", 1, lambda r: d(r["def_tackles_for_loss"], r["def_snaps"])),
        ("QB hits/snap", 1, lambda r: d(r["def_qb_hits"], r["def_snaps"]))],
 "LB": [("Tackles/snap", 1, lambda r: d(r["def_tackles_solo"] + r["def_tackle_assists"], r["def_snaps"])),
        ("TFL+sacks/snap", 1, lambda r: d(r["def_tackles_for_loss"] + r["def_sacks"], r["def_snaps"])),
        ("Missed tackle %", 0, lambda r: d(r["pfr_missed"], r["pfr_missed"] + r["pfr_tackles"])),
        ("Yds allowed/target", 0, lambda r: d(r["pfr_yds_allowed"], r["pfr_targets"]) if r["pfr_targets"] >= 8 else None)],
 "CB": [("Yds allowed/target", 0, lambda r: d(r["pfr_yds_allowed"], r["pfr_targets"]) if r["pfr_targets"] >= 8 else None),
        ("Comp % allowed", 0, lambda r: d(r["pfr_cmp"], r["pfr_targets"]) if r["pfr_targets"] >= 8 else None),
        ("Passer rtg allowed", 0, lambda r: d(r["pfr_rtg_w"], r["pfr_targets"]) if r["pfr_targets"] >= 8 else None),
        ("PD+INT per snap", 1, lambda r: d(r["def_pass_defended"] + r["def_interceptions"], r["def_snaps"])),
        ("Missed tackle %", 0, lambda r: d(r["pfr_missed"], r["pfr_missed"] + r["pfr_tackles"]))],
 "S":  [("Yds allowed/target", 0, lambda r: d(r["pfr_yds_allowed"], r["pfr_targets"]) if r["pfr_targets"] >= 6 else None),
        ("Passer rtg allowed", 0, lambda r: d(r["pfr_rtg_w"], r["pfr_targets"]) if r["pfr_targets"] >= 6 else None),
        ("PD+INT per snap", 1, lambda r: d(r["def_pass_defended"] + r["def_interceptions"], r["def_snaps"])),
        ("Tackles/snap", 1, lambda r: d(r["def_tackles_solo"] + r["def_tackle_assists"], r["def_snaps"])),
        ("Missed tackle %", 0, lambda r: d(r["pfr_missed"], r["pfr_missed"] + r["pfr_tackles"]))],
 "K":  [("FG %", 1, lambda r: d(r["fg_made"], r["fg_att"])),
        ("50+ makes/att", 1, lambda r: d(r["fg_made_50_59"] + r["fg_made_60_"], r["fg_att"])),
        ("PAT %", 1, lambda r: d(r["pat_made"], r["pat_att"]))],
 "P":  [("Net yds/punt", 1, lambda r: d(r["pt_net_yards"], r["pt_att"])),
        ("Inside-20 rate", 1, lambda r: d(r["pt_inside_20"], r["pt_att"]))],
}
# sample unit per position and shrink constant K (in that unit); min sample to be ranked
SAMPLE = {"QB": ("dropbacks", 150, 250), "RB": ("off_snaps", 250, 250), "WR": ("off_snaps", 300, 400), "TE": ("off_snaps", 300, 400),
          "DL": ("def_snaps", 300, 400), "LB": ("def_snaps", 300, 400), "CB": ("def_snaps", 300, 400), "S": ("def_snaps", 300, 400),
          "K": ("fg_att", 15, 30), "P": ("pt_att", 30, 60)}
NUM = ["attempts", "completions", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered", "sack_yards_lost", "passing_epa",
       "carries", "rushing_yards", "rushing_tds", "rushing_epa", "receptions", "targets", "receiving_yards", "receiving_tds", "receiving_epa",
       "def_tackles_solo", "def_tackle_assists", "def_tackles_for_loss", "def_sacks", "def_qb_hits", "def_interceptions", "def_pass_defended",
       "fg_made", "fg_att", "fg_made_50_59", "fg_made_60_", "pat_made", "pat_att", "pt_att", "pt_net_yards", "pt_inside_20", "games"]


def fetch(rel, name):
    if CACHE and os.path.exists(os.path.join(CACHE, name)):
        return open(os.path.join(CACHE, name), encoding="utf-8").read()
    req = urllib.request.Request(f"{B}/{rel}/{name}", headers={"User-Agent": "eagles-gm-lab-live/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8")


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def f(x):
    try:
        return float(x) if x not in (None, "", "NA") else 0.0
    except ValueError:
        return 0.0


def norm(n):
    n = re.sub(r"[^a-z ]", "", (n or "").lower().replace("-", " "))
    return re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n).strip().replace("  ", " ")


def blank():
    r = defaultdict(float)
    return r


def load_season(y):
    """Return dict key=(normname) -> season row (summed), plus team games."""
    P = {}
    # snaps
    teamweeks = defaultdict(set)
    for s in rows(fetch("snap_counts", f"snap_counts_{y}.csv")):
        if s["game_type"] != "REG":
            continue
        teamweeks[s["team"]].add(s["week"])
        k = norm(s["player"])
        r = P.setdefault(k, blank())
        r["name"] = s["player"]; r["team"] = s["team"]; r["pos_raw"] = s["position"]; r["pfr_id"] = s["pfr_player_id"]
        o, dd = f(s["offense_snaps"]), f(s["defense_snaps"])
        r["off_snaps"] += o; r["def_snaps"] += dd; r["st_snaps"] += f(s["st_snaps"])
        if o + dd > 0 or f(s["st_snaps"]) > 0:
            r["gp"] += 1
        r["pct_sum"] += max(f(s["offense_pct"]), f(s["defense_pct"]))
    for s in rows(fetch("stats_player", f"stats_player_reg_{y}.csv")):
        k = norm(s["player_display_name"])
        r = P.setdefault(k, blank())
        r.setdefault("name", s["player_display_name"])
        if "team" not in r:
            r["team"] = s["recent_team"]
        r["stats_pos"] = s["position"]; r["headshot"] = s["headshot_url"]; r["gsis"] = s["player_id"]
        for c in NUM:
            r[c] += f(s.get(c))
        r["cpoe_w"] += f(s["passing_cpoe"]) * f(s["attempts"])
    for s in rows(fetch("pfr_advstats", f"advstats_week_def_{y}.csv")):
        if s["game_type"] != "REG":
            continue
        k = norm(s["pfr_player_name"])
        r = P.get(k)
        if r is None:
            continue
        t = f(s["def_targets"])
        r["pfr_targets"] += t; r["pfr_cmp"] += f(s["def_completions_allowed"]); r["pfr_yds_allowed"] += f(s["def_yards_allowed"])
        r["pfr_rtg_w"] += f(s["def_passer_rating_allowed"]) * t; r["pfr_pressures"] += f(s["def_pressures"])
        r["pfr_missed"] += f(s["def_missed_tackles"]); r["pfr_tackles"] += f(s["def_tackles_combined"])
    for r in P.values():
        r["dropbacks"] = r["attempts"] + r["sacks_suffered"] + r["carries"] * 0.0
        raw = r.get("pos_raw") or r.get("stats_pos") or ""
        pos = POSMAP.get(raw)
        if raw == "DB":
            pos = "CB" if r.get("stats_pos") == "CB" else "S"
        r["pos"] = pos
    tg = {t: len(w) for t, w in teamweeks.items()}
    return P, tg


def pctile(vals, v, hib):
    xs = sorted(vals)
    if not xs:
        return 50.0
    below = sum(1 for x in xs if x < v); eq = sum(1 for x in xs if x == v)
    p = 100.0 * (below + 0.5 * eq) / len(xs)
    return p if hib else 100.0 - p


def summed(rs):
    out = blank()
    for r in rs:
        for k, v in r.items():
            if isinstance(v, float):
                out[k] += v
    return out


def main():
    seasons = {}
    for y in WINDOW:
        try:
            seasons[y] = load_season(y)
        except Exception as e:
            print(f"season {y} failed: {e}", file=sys.stderr)
    if SEASON not in seasons:
        print("current season missing; keeping old file", file=sys.stderr)
        return 1
    cur, curtg = seasons[SEASON]
    keys = set()
    for P, _ in seasons.values():
        keys |= set(P)
    players = []
    for k in keys:
        per = {y: seasons[y][0][k] for y in seasons if k in seasons[y][0]}
        latest = per[max(per)]
        pos = (per.get(SEASON) or latest).get("pos")
        if pos not in METRICS and pos != "OL":
            continue
        win = summed(per.values())
        c = per.get(SEASON, blank())
        team_g = sum(seasons[y][1].get(per[y].get("team"), 17) for y in per)
        gp = sum(per[y]["gp"] for y in per)
        players.append({"k": k, "name": latest["name"], "team": (per.get(SEASON) or latest).get("team"), "pos": pos,
                        "headshot": latest.get("headshot"), "cur": c, "win": win, "gp": gp, "teamG": team_g,
                        "curGp": c["gp"], "curTeamG": curtg.get(c.get("team") or "", 0),
                        "snapPct": round(c["pct_sum"] / c["gp"] * 100) if c["gp"] else None, "seasons": sorted(per)})
    out = []
    for pos, mets in METRICS.items():
        unit, K, minn = SAMPLE[pos]
        pool = [p for p in players if p["pos"] == pos]
        curpool = [p for p in pool if p["cur"][unit] >= minn * 0.2]
        winpool = [p for p in pool if p["win"][unit] >= minn]
        def comp(p, which, peers):
            ps, detail = [], []
            for lab, hib, fn in mets:
                v = fn(p[which])
                vals = [x for x in (fn(q[which]) for q in peers) if x is not None]
                if v is None or len(vals) < 5:
                    continue
                pc = pctile(vals, v, hib); ps.append(pc)
                detail.append({"m": lab, "v": round(v, 3), "pct": round(pc)})
            return (sum(ps) / len(ps) if ps else None), detail
        for p in pool:
            n_cur, n_win = p["cur"][unit], p["win"][unit]
            if n_win < minn * 0.25:
                continue
            t_raw, t_det = comp(p, "win", winpool)
            c_raw, c_det = comp(p, "cur", curpool) if n_cur >= minn * 0.2 else (None, [])
            if t_raw is None:
                continue
            wt = n_win / (n_win + K)
            talent = 50 + (t_raw - 50) * wt                       # shrink to median by sample
            if c_raw is None:
                current = talent
            else:
                wc = n_cur / (n_cur + K * 0.4)
                current = talent + (c_raw - talent) * wc           # thin current sample leans on talent
            score = 0.5 * current + 0.5 * talent
            avail = p["gp"] / p["teamG"] if p["teamG"] else None
            risk = "High" if avail is not None and avail < 0.7 else "Moderate" if avail is not None and avail < 0.85 else "Low"
            out.append({"name": p["name"], "team": p["team"], "pos": pos, "score": round(score, 1), "current": round(current, 1),
                        "talent": round(talent, 1), "currentRaw": None if c_raw is None else round(c_raw), "talentRaw": round(t_raw),
                        "sampleCur": int(n_cur), "sampleWin": int(n_win), "unit": unit, "shrink": round(wt, 2),
                        "gp": int(p["gp"]), "teamG": int(p["teamG"]), "availability": None if avail is None else round(avail, 2), "injuryRisk": risk,
                        "suppressed": bool(avail is not None and avail < 0.8 and t_raw >= 70),
                        "ranked": n_win >= minn, "snapPct": p["snapPct"], "seasons": p["seasons"], "metricsCur": c_det, "metricsWin": t_det, "headshot": p["headshot"]})
    # ranks
    bypos = defaultdict(list)
    for r in out:
        if r.get("ranked"):
            bypos[r["pos"]].append(r)
        else:
            r["rank"] = None; r["note"] = "Below minimum sample for ranking (score heavily shrunk to position median)"
    for pos, lst in bypos.items():
        lst.sort(key=lambda r: -r["score"])
        for i, r in enumerate(lst):
            r["rank"] = i + 1; r["of"] = len(lst); r["pct"] = round(100 * (1 - i / max(1, len(lst) - 1)))
    # OL: availability only
    for p in players:
        if p["pos"] == "OL" and p["win"]["off_snaps"] > 100:
            avail = p["gp"] / p["teamG"] if p["teamG"] else None
            out.append({"name": p["name"], "team": p["team"], "pos": "OL", "score": None, "note": "No free per-player OL blocking stats; availability & snap share only",
                        "sampleCur": int(p["cur"]["off_snaps"]), "sampleWin": int(p["win"]["off_snaps"]), "unit": "off_snaps", "snapPct": p["snapPct"],
                        "gp": int(p["gp"]), "teamG": int(p["teamG"]), "availability": None if avail is None else round(avail, 2),
                        "injuryRisk": "High" if avail is not None and avail < 0.7 else "Moderate" if avail is not None and avail < 0.85 else "Low", "seasons": p["seasons"]})
    ALIAS = {"tariq woolen": "riq woolen"}
    want = {}
    try:
        for r in json.load(open(os.path.join(ROOT, "data", "roster.json")))["data"]:
            want[ALIAS.get(norm(r["name"]), norm(r["name"]))] = POSMAP.get(r.get("pos") or "", r.get("pos"))
    except Exception:
        pass
    phi = [r for r in out if r["team"] == "PHI" or want.get(norm(r["name"]), "?") == r["pos"]]
    for r in phi:
        r["key"] = norm(r["name"])
    leaders = {pos: [{k: r[k] for k in ("name", "team", "score", "rank")} for r in lst[:10]] for pos, lst in bypos.items()}
    payload = {"season": SEASON, "window": WINDOW, "phi": sorted(phi, key=lambda r: (r["pos"], -(r["score"] or 0))), "leaders": leaders,
               "poolSize": {pos: len(l) for pos, l in bypos.items()},
               "method": "Score = 50% Current (this season) + 50% Talent (3-season per-snap rates, shrunk toward the position median by sample). Percentiles vs position peers with a minimum sample. Availability is shown separately as injury risk and is not in the score. Estimates from public stats only; not scouting grades."}
    p = os.path.join(ROOT, "data", "performance.json")
    try:
        if json.load(open(p))["data"] == json.loads(json.dumps(payload)):
            print("performance.json unchanged"); return 0
    except Exception:
        pass
    json.dump({"updated": datetime.now(timezone.utc).astimezone(ET).isoformat(timespec="seconds"), "data": payload}, open(p, "w"), indent=1)
    print(f"ok performance.json: {len(out)} players, {len(phi)} PHI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
