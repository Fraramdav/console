import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SCRAPER_PATH = (
    Path(__file__).parents[1] / "scrapers" / "node-feature-discovery.py"
)
spec = importlib.util.spec_from_file_location("node_feature_discovery", SCRAPER_PATH)
scraper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraper)

POLICY = """# Versions and deprecation

## Supported versions

The most recent two minor releases (or release branches) of Node Feature
Discovery are supported.

## Kubernetes compatibility

Node Feature Discovery is compatible with Kubernetes v1.24 and later.
"""

RELEASES = [
    "v0.19.0",
    "v0.19.0-rc.1",
    "v0.18.3",
    "v0.18.2",
    "v0.17.4",
    "garbage",
]


class NodeFeatureDiscoveryTests(unittest.TestCase):
    def test_parses_official_support_policy(self):
        self.assertEqual(scraper.parse_support_policy(POLICY), (2, "1.24"))

    def test_missing_support_policy_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "supported-minor policy"):
            scraper.parse_support_policy(
                "Node Feature Discovery is compatible with Kubernetes v1.24 and later."
            )

    def test_missing_kubernetes_minimum_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "minimum Kubernetes"):
            scraper.parse_support_policy(
                "The most recent two minor releases of Node Feature Discovery are supported."
            )

    def test_selects_latest_patch_from_two_supported_minors(self):
        self.assertEqual(
            scraper.select_supported_releases(RELEASES, 2),
            ["0.19.0", "0.18.3"],
        )

    def test_prereleases_and_invalid_tags_are_ignored(self):
        self.assertEqual(
            scraper.stable_versions(["v0.19.0-rc.1", "garbage", "v0.18.3"]),
            ["0.18.3"],
        )

    def test_insufficient_supported_minors_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "supported NFD minor"):
            scraper.select_supported_releases(["v0.19.0", "v0.19.1"], 2)

    def test_expands_kubernetes_minimum_through_plural_current(self):
        self.assertEqual(
            scraper.expand_supported_kube_versions("1.24", "1.27"),
            ["1.27", "1.26", "1.25", "1.24"],
        )

    def test_future_minimum_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "newer than Plural"):
            scraper.expand_supported_kube_versions("1.24", "1.23")

    def test_build_rows_matches_chart_and_application_versions(self):
        rows = scraper.build_rows(RELEASES, "1.27", "1.24", 2)
        self.assertEqual([row["version"] for row in rows], ["0.19.0", "0.18.3"])
        self.assertEqual(rows[0]["chart_version"], "0.19.0")
        self.assertEqual(rows[1]["chart_version"], "0.18.3")
        self.assertEqual(rows[0]["kube"], ["1.27", "1.26", "1.25", "1.24"])

    def test_scrape_wires_official_sources(self):
        with (
            patch.object(scraper, "fetch_page", return_value=POLICY.encode()),
            patch.object(scraper, "current_kube_version", return_value="1.27"),
            patch.object(scraper, "get_github_releases", return_value=RELEASES),
            patch.object(scraper, "update_compatibility_info") as update,
        ):
            scraper.scrape()

        update.assert_called_once()
        path, rows = update.call_args.args
        self.assertEqual(
            path,
            "../../static/compatibilities/node-feature-discovery.yaml",
        )
        self.assertEqual([row["version"] for row in rows], ["0.19.0", "0.18.3"])

    def test_invalid_policy_encoding_fails_closed(self):
        with patch.object(scraper, "fetch_page", return_value=b"\xff"):
            with self.assertRaisesRegex(ValueError, "Could not decode"):
                scraper.scrape()


if __name__ == "__main__":
    unittest.main()
