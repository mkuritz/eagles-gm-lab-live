# Eagles GM Lab · Live

Live-data edition of Eagles GM Lab (separate from `eagles-gm-lab`). Static single-page app on GitHub Pages.

- `scripts/fetch_data.py` pulls ESPN (roster, standings, schedule), nflverse (injuries, depth charts, Over The Cap contracts) and Sleeper (depth backup, max once/day) into `data/*.json`. A failed source keeps its previous file.
- `.github/workflows/update-data.yml` runs daily ~7 AM ET, every 3h on Sun/Mon/Thu, or manually; commits only when data changes. Pages redeploys on push.
- `index.html` loads `data/*.json` at startup and merges over the embedded Oct 7, 2026 snapshot (falls back to the snapshot on any failure). Live fields are tagged `prov: 'L'`.
- **Manual:** `data/cap_manual.json` holds cap hits, dead money, extensions, cut candidates, draft picks, league cap, team cap space/needs. No free live source exists — edit by hand.

Data credits: ESPN (unofficial API), nflverse, Over The Cap (via nflverse), Sleeper. Personal, non-commercial demo.

## Performance Score (replaces subjective ratings)
`scripts/performance.py` builds `data/performance.json` from free nflverse data (season player stats,
PFR snap counts, PFR advanced defense). Per position it computes rate stats (e.g. CB: yards/target,
completion % and passer rating allowed, PD+INT per snap, missed-tackle %), converts each to a percentile
vs league peers with a minimum sample, and blends **50% Current** (this season) + **50% Talent**
(3-season rates shrunk toward the position median by sample size). Availability is reported separately
as injury risk. OL get no score (no free blocking data). All scores are estimates from public stats.
The "Super Bowl Puzzle" view tiers players (Cornerstone / Core / Contributor / Depth) from percentile + age + contract.
Part of [Sports Labs](https://mkuritz.github.io/sports-labs/).
