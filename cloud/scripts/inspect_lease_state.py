from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/root/项目航图"))
    args = parser.parse_args()
    database = (args.root / "runtime/projects.sqlite3").resolve(strict=True)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        leases = connection.execute("SELECT device,expires FROM editor_leases").fetchall()
        documents = connection.execute("SELECT payload FROM documents").fetchall()
    now = time.time()
    active = [row for row in leases if row[1] > now]
    print(json.dumps({"active_lease_count": len(active), "expired_lease_count": len(leases) - len(active),
                      "owners": ["电脑端" if row[0].startswith(("Windows", "电脑")) else "手机端" for row in active],
                      "document_count": len(documents),
                      "live_document_count": sum(not json.loads(row[0]).get("deleted", False) for row in documents)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
