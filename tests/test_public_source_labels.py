"""Public site copy (README, meta.json, xcheck.json) and the writers that refresh them
must not name data vendors. Internal fetch URLs and function identifiers may."""
import json, re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_data
from xlib import neutralize, neutralize_public, public_url

VENDOR = re.compile(
    r"nflverse|\bnflreadr\b|\bffverse\b|\bffopportunity\b|\bPFR\b|Pro[- ]Football[- ]Reference|"
    r"Over The Cap|Next Gen Stats|\bNGS\b|\bSleeper\b|\bESPN\b|\bYahoo\b",
    re.I,
)
# PPR (points per reception) is a scoring term, not a vendor.
PUBLIC = [
    ROOT / "README.md",
    ROOT / "data/meta.json",
    ROOT / "data/xcheck.json",
]


class Neutralize(unittest.TestCase):
    def test_known_phrases(self):
        self.assertEqual(neutralize("nflverse snap counts"), "public stats snap counts")
        self.assertIn("tracking data", neutralize("Next Gen Stats + PFR").lower())
        self.assertNotIn("PFR", neutralize("Next Gen Stats + PFR"))
        self.assertEqual(neutralize("ESPN vs Sleeper"), "league feed vs second depth source")
        self.assertEqual(neutralize("Over The Cap"), "public contract data")
        self.assertEqual(neutralize("PPR points per game"), "PPR points per game")

    def test_vendor_urls_dropped(self):
        self.assertIsNone(public_url("https://github.com/nflverse/nflverse-data/releases/tag/snap_counts"))
        self.assertIsNone(public_url("https://github.com/ffverse/ffopportunity"))
        self.assertEqual(public_url("https://sportslabshq.com/docs"), "https://sportslabshq.com/docs")

    def test_payload_walk_keeps_keys_and_numbers(self):
        raw = {"title": "nflverse snap counts", "n": 41, "url": "https://github.com/nflverse/nflverse-data", "ok": True}
        out = neutralize_public(raw)
        self.assertEqual(set(out), set(raw))
        self.assertEqual(out["n"], 41)
        self.assertTrue(out["ok"])
        self.assertIsNone(out["url"])
        self.assertNotRegex(out["title"], VENDOR)


class Writers(unittest.TestCase):
    def test_fetch_data_source_labels_are_clean(self):
        for fname, label, _fn in fetch_data.SOURCES:
            clean = fetch_data._public_label(label)
            self.assertEqual(clean, label, msg=f"{fname} label should already be public-safe")
            self.assertIsNone(VENDOR.search(clean), msg=label)

    def test_xcheck_script_public_literals(self):
        # Fetch URLs may still name a feed; quoted public copy should not.
        src = (ROOT / "scripts/eagles_xcheck.py").read_text()
        # Strip comments and the fetch URL strings for a rough public-literal check:
        # the S.get first arg and table titles/cols live in quotes and must be clean.
        for needle in (
            'S.get("nflverse',
            'S.get("ESPN',
            "Spot (Sleeper)",
            "ESPN rank",
            "Next Gen Stats",
            "nflverse snap counts",
            "ESPN vs Sleeper",
            "ESPN/nflverse",
        ):
            self.assertNotIn(needle, src, msg=needle)


class SiteFiles(unittest.TestCase):
    def test_public_files_have_no_vendor_names(self):
        for path in PUBLIC:
            text = path.read_text()
            m = VENDOR.search(text)
            self.assertIsNone(m, msg=f"{path.name} still has {m.group(0)!r}" if m else "")

    def test_xcheck_schema_and_row_counts(self):
        d = json.loads((ROOT / "data/xcheck.json").read_text())
        self.assertEqual(set(d), {"title", "generated", "sources", "tables", "summary"})
        self.assertEqual(len(d["sources"]), 7)
        self.assertEqual(len(d["tables"]), 4)
        self.assertEqual(len(d["tables"][0]["cols"]), 6)
        self.assertEqual(len(d["tables"][0]["rows"]), 41)
        self.assertEqual(d["tables"][0]["flag"], 5)
        self.assertEqual(d["summary"][0][1], 41)
        self.assertEqual(d["summary"][1][1], "88%")
        for s in d["sources"]:
            self.assertIn("name", s)
            self.assertIn("status", s)
            if "url" in s:
                self.assertTrue(s["url"] is None or not VENDOR.search(s["url"] or ""))

    def test_meta_schema_and_timestamps_kept(self):
        d = json.loads((ROOT / "data/meta.json").read_text())
        self.assertIn("sources", d)
        self.assertEqual(d["timezone"], "America/New_York")
        for fname, src in d["sources"].items():
            for k in ("label", "ok", "lastSuccess"):
                self.assertIn(k, src, msg=f"{fname} missing {k}")
            self.assertIsNone(VENDOR.search(src["label"] or ""), msg=src["label"])


if __name__ == "__main__":
    unittest.main()
