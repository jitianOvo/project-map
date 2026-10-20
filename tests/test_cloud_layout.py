from __future__ import annotations

import unittest
from pathlib import Path

from project_map.locations import cloud_dir


REPO_ROOT = Path(__file__).resolve().parents[1]


class CloudLayoutTests(unittest.TestCase):
    def test_cloud_workspace_is_nested_in_the_main_project(self):
        cloud = cloud_dir(REPO_ROOT)

        self.assertEqual(cloud, REPO_ROOT / "cloud")
        self.assertTrue((cloud / "server" / "http.py").is_file())
        self.assertTrue((cloud / "windows" / "unified_launcher.py").is_file())


if __name__ == "__main__":
    unittest.main()
