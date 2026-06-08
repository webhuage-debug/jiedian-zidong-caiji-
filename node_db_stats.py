#!/usr/bin/env python3
"""Show SQLite node database totals and protocol distribution."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from node_database import NodeDatabase


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/nodes.db"))
    return parser.parse_args()


def print_table(connection: sqlite3.Connection, table: str) -> None:
    total = connection.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
    print(table + ": " + str(total))
    rows = connection.execute(
        'SELECT protocol, COUNT(*) FROM "' + table + '" GROUP BY protocol ORDER BY COUNT(*) DESC, protocol'
    )
    for protocol, count in rows:
        print("  " + (protocol or "unknown") + ": " + str(count))
    if table == "节点库":
        print("  验证状态:")
        rows = connection.execute(
            'SELECT validation_status, COUNT(*) FROM "节点库" GROUP BY validation_status ORDER BY COUNT(*) DESC'
        )
        for status, count in rows:
            print("    " + status + ": " + str(count))


def main() -> int:
    args = parse_args()
    with NodeDatabase(args.database) as database:
        print_table(database.connection, "节点库")
        print_table(database.connection, "有效节点")
        print("无效节点累计: " + str(database.stats()["invalid_nodes"]))
        print("已过滤重复: " + str(database.counter("duplicate_filtered")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
