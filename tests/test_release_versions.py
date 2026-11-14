from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "check_release_version.py"
SPEC = importlib.util.spec_from_file_location("check_release_version", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
check_release_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_release_version)


class ReleaseVersionTests(unittest.TestCase):
    def test_application_and_cluster_runtime_have_independent_groups(self) -> None:
        application = check_release_version.declared_versions(PROJECT_ROOT)
        cluster = check_release_version.declared_cluster_versions(PROJECT_ROOT)

        self.assertEqual(len(set(application.values())), 1)
        self.assertEqual(len(set(cluster.values())), 1)
        self.assertFalse(set(application).intersection(cluster))
        self.assertNotIn("cluster/install-server.sh", application)
        self.assertIn("cluster/install-server.sh", cluster)

    def test_current_cluster_runtime_remains_at_published_version(self) -> None:
        cluster = check_release_version.declared_cluster_versions(PROJECT_ROOT)
        self.assertEqual(set(cluster.values()), {"1.0.0"})

    def test_about_dialog_and_citation_share_release_date(self) -> None:
        dates = check_release_version.declared_release_dates(PROJECT_ROOT)
        self.assertEqual(set(dates.values()), {"2026-11-13"})


if __name__ == "__main__":
    unittest.main()
