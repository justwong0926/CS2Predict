"""DuckDB schema for the CS2 data lake.

Match-level spine from bo3.gg (Tier-1 CS2). Map-level detail, player stats, and
odds tables are added as those ingesters land.
"""
from __future__ import annotations

import duckdb

from cs2edge.config import DUCKDB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    team_id     BIGINT PRIMARY KEY,
    slug        VARCHAR,
    name        VARCHAR,
    rank        INTEGER,
    country_id  INTEGER,
    updated_at  TIMESTAMP DEFAULT now()
);

-- One row per Tier-1 CS2 match (series). bo3 match_id is the canonical key.
CREATE TABLE IF NOT EXISTS matches (
    match_id       BIGINT PRIMARY KEY,
    slug           VARCHAR,
    discipline_id  INTEGER,
    tier           VARCHAR,
    tier_rank      INTEGER,
    bo_type        INTEGER,        -- 1 = Bo1, 3 = Bo3, 5 = Bo5
    tournament_id  BIGINT,
    team1_id       BIGINT,
    team2_id       BIGINT,
    winner_team_id BIGINT,
    team1_score    INTEGER,        -- maps won
    team2_score    INTEGER,
    start_date     TIMESTAMP,
    end_date       TIMESTAMP,
    status         VARCHAR,
    ingested_at    TIMESTAMP DEFAULT now()
);
"""


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DUCKDB_PATH), read_only=read_only)


def init_db() -> None:
    con = connect()
    try:
        con.execute(SCHEMA)
    finally:
        con.close()


if __name__ == "__main__":
    init_db()
    print(f"initialized schema at {DUCKDB_PATH}")
