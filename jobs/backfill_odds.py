"""Backfill Pinnacle closing lines (via OddsPapi) over a date range.

Rate-limited free tier: calls are throttled (~1.2s each) and only made for
fixtures that match a bo3 Tier-1 match, to conserve quota. Re-runnable
(INSERT OR REPLACE by fixture_id).

Usage:
    py -m jobs.backfill_odds 2024-01-01 2026-09-19
"""
from __future__ import annotations

import argparse
import datetime as dt

from cs2edge.db.schema import connect, init_db
from cs2edge.ingest import oddspapi


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("end")
    args = ap.parse_args()

    init_db()
    con = connect()
    try:
        stats = oddspapi.ingest_range(
            con, dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
        )
        print(stats)
    finally:
        con.close()


if __name__ == "__main__":
    main()
