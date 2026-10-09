# Eagles GM Lab · Live

Live-data edition of Eagles GM Lab (separate from `eagles-gm-lab`). Static single-page app on GitHub Pages.

- `scripts/fetch_data.py` pulls ESPN (roster, standings, schedule), nflverse (injuries, depth charts, Over The Cap contracts) and Sleeper (depth backup, max once/day) into `data/*.json`. A failed source keeps its previous file.
- `.github/workflows/update-data.yml` runs daily ~7 AM ET, every 3h on Sun/Mon/Thu, or manually; commits only when data changes. Pages redeploys on push.
- `index.html` loads `data/*.json` at startup and merges over the embedded Oct 7, 2026 snapshot (falls back to the snapshot on any failure). Live fields are tagged `prov: 'L'`.
- **Manual:** `data/cap_manual.json` holds cap hits, dead money, extensions, cut candidates, draft picks, league cap, team cap space/needs. No free live source exists — edit by hand.

Data credits: ESPN (unofficial API), nflverse, Over The Cap (via nflverse), Sleeper. Personal, non-commercial demo.
