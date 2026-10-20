from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_map.migration import merge_inner_data


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(merge_inner_data(root, root / "Backups" / "整合迁移-20261006"), ensure_ascii=False, indent=2))
