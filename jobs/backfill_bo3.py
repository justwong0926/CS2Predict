"""Backfill the bo3.gg Tier-1 CS2 match spine into DuckDB.

Usage:
    py -m jobs.backfill_bo3            # matches only
    py -m jobs.backfill_bo3 --teams   # also refresh the teams dimension
"""
from __future__ import annotations

import argparse

from cs2edge.db.schema import connect, init_db
from cs2edge.ingest import bo3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", action="store_true", help="also backfill teams")
    args = ap.parse_args()

    init_db()
    con = connect()
    try:
        n = bo3.backfill_matches(con)
        print(f"matches: {n}")
        if args.teams:
            t = bo3.fetch_teams(con)
            print(f"teams: {t}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
