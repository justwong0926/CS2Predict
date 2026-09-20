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
    ap.add_argument("--games", action="store_true", help="backfill per-map results (CS2 era)")
    ap.add_argument("--games-only", action="store_true", help="only per-map results")
    args = ap.parse_args()

    init_db()
    con = connect()
    try:
        if not args.games_only:
            n = bo3.backfill_matches(con)
            print(f"matches: {n}")
            if args.teams:
                print(f"teams: {bo3.fetch_teams(con)}")
        if args.games or args.games_only:
            print(f"games: {bo3.backfill_games(con)}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
