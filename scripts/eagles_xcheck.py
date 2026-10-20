"""Eagles GM Hub cross-check: Next Gen Stats, PFR advanced, ffopportunity expected points, snap counts, and
depth-chart agreement between nflverse (ESPN-sourced) and Sleeper for the roster."""
import json, os, sys, collections, time
sys.path.insert(0, os.path.dirname(__file__))
from xlib import Src, rows, f, norm, write
import nflx
TEAM = os.environ.get("TEAM", "PHI")
D = os.path.join(os.path.dirname(__file__), "..", "data")
S = Src(); yr = int(time.strftime("%Y")) - (1 if int(time.strftime("%m")) < 8 else 0)
NV = nflx.NV
rec = S.get("nflverse Next Gen Stats: receiving", NV + "nextgen_stats/ngs_receiving.csv.gz", "Separation, air-yard share, YAC over expected", lambda: {k: v for k, v in nflx.ngs("receiving", yr).items() if k[1] == TEAM}, link="https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats") or {}
rush = S.get("nflverse Next Gen Stats: rushing", NV + "nextgen_stats/ngs_rushing.csv.gz", "Rush yards over expected, stacked boxes", lambda: {k: v for k, v in nflx.ngs("rushing", yr).items() if k[1] == TEAM}, link="https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats") or {}
pas = S.get("nflverse Next Gen Stats: passing", NV + "nextgen_stats/ngs_passing.csv.gz", "CPOE, time to throw, aggressiveness", lambda: {k: v for k, v in nflx.ngs("passing", yr).items() if k[1] == TEAM}, link="https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats") or {}
pfr = S.get("nflverse PFR advanced (rec/rush)", NV + "pfr_advstats/", "Broken tackles, drops", lambda: {k: v for k, v in nflx.pfr_rec(yr).items() if k[1] == TEAM}, link="https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats") or {}
snaps = S.get("nflverse snap counts", NV + "snap_counts/snap_counts_%d.csv" % yr, "Offense/defense snap share trend (last 3 games vs season)", lambda: [r for r in rows(NV + "snap_counts/snap_counts_%d.csv" % yr) if nflx.T(r["team"]) == TEAM], link="https://github.com/nflverse/nflverse-data/releases/tag/snap_counts") or []
ep = S.get("Expected points model (open stats feed)", "https://github.com/ffverse/ffopportunity", "Usage-based expected production vs actual", lambda: [r for r in rows("https://github.com/ffverse/ffopportunity/releases/download/latest-data/ep_weekly_%d.csv" % yr) if nflx.T(r["posteam"]) == TEAM], link="https://github.com/ffverse/ffopportunity") or []
S.list = [dict(name="Already used: ESPN roster/schedule/standings, nflverse injuries/depth/contracts/stats, Sleeper depth", status="ok", what="Core inputs (unchanged)", new=False)] + S.list
# depth agreement (existing sources, now cross-checked)
dep = json.load(open(os.path.join(D, "depth.json")))["data"]; sd = json.load(open(os.path.join(D, "sleeper_depth.json")))["data"]
espn1 = {norm(r["player_name"]): int(f(r["pos_rank"], 9)) for r in dep if r.get("player_name") and r.get("pos_grp") != "Special Teams"}
dt = []; nag = ncmp = 0
for r in sd:
    if r.get("depthOrder") is None: continue
    n = norm(r["name"]); e = espn1.get(n)
    if e is None: continue
    ncmp += 1; v = "agree" if (e == 1) == (r["depthOrder"] == 1) else "disagree"; nag += v == "agree"
    dt.append([r["name"], r["depthPos"], r["depthOrder"], e, r.get("injury") or "—", v])
dt.sort(key=lambda r: (r[5] != "disagree", r[0]))
sn = collections.defaultdict(list)
for r in snaps:
    if r.get("game_type", "REG") != "REG": continue
    sh = max(f(r.get("offense_pct"), 0), f(r.get("defense_pct"), 0))
    sn[(r["player"], r["position"])].append((int(r["week"]), sh))
st = []
for (n, p), w in sn.items():
    w.sort(); s = sum(x[1] for x in w) / len(w); l3 = sum(x[1] for x in w[-3:]) / len(w[-3:])
    if s < .1 and l3 < .1: continue
    st.append([n, p, len(w), round(100 * s), round(100 * l3), round(100 * (l3 - s)), "rising" if l3 - s > .08 else ("falling" if s - l3 > .08 else "steady")])
st.sort(key=lambda r: -abs(r[5]))
adv = []
for (n, t), r in list(rec.items()) + list(rush.items()) + list(pas.items()):
    b = pfr.get((n, t), {})
    if "avg_separation" in r: adv.append([r["player_display_name"], r["player_position"], "Receiving", "Sep %.2f yd · %s%% air yds · YAC+ %.2f" % (f(r["avg_separation"], 0), round(f(r["percent_share_of_intended_air_yards"], 0), 1), f(r["avg_yac_above_expectation"], 0)), b.get("btk", "—"), b.get("drop", "—")])
    elif "rush_yards_over_expected_per_att" in r: adv.append([r["player_display_name"], r["player_position"], "Rushing", "RYOE/att %.2f · 8+ box %s%%" % (f(r["rush_yards_over_expected_per_att"], 0), round(f(r["percent_attempts_gte_eight_defenders"], 0), 1)), b.get("btk", "—"), "—"])
    else: adv.append([r["player_display_name"], "QB", "Passing", "CPOE %+.1f · TTT %.2fs · aggr %s%%" % (f(r["completion_percentage_above_expectation"], 0), f(r["avg_time_to_throw"], 0), round(f(r["aggressiveness"], 0), 1)), "—", "—"])
agg = collections.defaultdict(lambda: [0, 0.0, 0.0, ""])
for r in ep:
    a = agg[r["full_name"]]; a[0] += 1; a[1] += f(r["total_fantasy_points"], 0); a[2] += f(r["total_fantasy_points_exp"], 0); a[3] = r["position"]
et = [[n, a[3], a[0], round(a[1] / a[0], 1), round(a[2] / a[0], 1), round((a[1] - a[2]) / a[0], 1), "outperforming usage" if (a[1] - a[2]) / a[0] > 2.5 else ("underperforming usage" if (a[2] - a[1]) / a[0] > 2.5 else "in line")] for n, a in agg.items() if a[2] / a[0] >= 3]
et.sort(key=lambda r: -r[4])
tables = [dict(title="Depth chart: ESPN/nflverse vs Sleeper", note="Two independent depth charts. 'disagree' = one lists the player as the starter and the other doesn't: usually a recent injury or role change.", cols=["Player", "Spot (Sleeper)", "Sleeper order", "ESPN rank", "Injury", "Verdict"], rows=dt, flag=5),
          dict(title="Snap-share trend (nflverse snap counts)", note="Last 3 games vs season average: who's earning more (or less) trust from the staff.", cols=["Player", "Pos", "Games", "Season snap %", "Last-3 snap %", "Change (pts)", "Trend"], rows=st),
          dict(title="Advanced efficiency (Next Gen Stats + PFR)", note="Season to date.", cols=["Player", "Pos", "Type", "Next Gen Stats", "Broken tackles", "Drops"], rows=adv),
          dict(title="Expected vs actual production", note="PPR points per game vs what each player's opportunities were worth. Gaps tell you whether production is sustainable.", cols=["Player", "Pos", "Games", "Actual/g", "Expected/g", "Diff/g", "Read"], rows=et)]
summ = [["Depth spots compared", ncmp, "ESPN vs Sleeper"], ["Depth agreement", "%d%%" % round(100 * nag / max(ncmp, 1)), ""], ["Rising snap shares", sum(1 for r in st if r[6] == "rising"), "last 3 games"], ["Sources OK", "%d/%d" % (sum(s["status"] == "ok" for s in S.list), len(S.list)), "this refresh"]]
write(os.path.join(D, "xcheck.json"), "Eagles GM Hub · data sources & cross-check", S, tables, summ)
print([(s["name"][:30], s["status"], s.get("rows")) for s in S.list], summ, dt[:3], st[:3], et[:2])
