"""bo3.gg ingestion (Tier-1 CS2 match spine).

bo3.gg is the HLTV-equivalent that doesn't block automation, but it does require
browser-like headers. JSON:API style: filters use filter[matches.<field>][op]=v,
pagination via page[offset]/page[limit]. discipline_id 1 = CS2, tier 'a' = Tier-1.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Iterator

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from cs2edge.config import BO3_BASE
from cs2edge.db.schema import connect, init_db

_HEADERS = {
    "origin": "https://bo3.gg",
    "referer": "https://bo3.gg/",
    "accept": "application/json, text/plain, */*",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
}
_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)

CS2_DISCIPLINE = 1
TIER1 = "a"


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
def _get(path: str, params: dict[str, Any]) -> dict:
    r = _SESSION.get(f"{BO3_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def iter_finished_matches(limit: int = 100) -> Iterator[dict]:
    """All finished Tier-1 CS2 matches, oldest first (stable for resumable paging)."""
    offset = 0
    while True:
        params = {
            "page[offset]": offset,
            "page[limit]": limit,
            "sort": "start_date",
            "filter[matches.status][eq]": "finished",
            "filter[matches.discipline_id][eq]": CS2_DISCIPLINE,
            "filter[matches.tier][eq]": TIER1,
        }
        data = _get("/api/v1/matches", params)
        results = data.get("results", [])
        if not results:
            break
        yield from results
        offset += limit
        if offset >= data.get("total", {}).get("count", 0):
            break


def parse_match(m: dict) -> dict:
    return {
        "match_id": m.get("id"),
        "slug": m.get("slug"),
        "discipline_id": m.get("discipline_id"),
        "tier": m.get("tier"),
        "tier_rank": m.get("tier_rank"),
        "bo_type": m.get("bo_type"),
        "tournament_id": m.get("tournament_id"),
        "team1_id": m.get("team1_id"),
        "team2_id": m.get("team2_id"),
        "winner_team_id": m.get("winner_team_id"),
        "team1_score": m.get("team1_score"),
        "team2_score": m.get("team2_score"),
        "start_date": _ts(m.get("start_date")),
        "end_date": _ts(m.get("end_date")),
        "status": m.get("status"),
    }


_MATCH_COLS = [
    "match_id", "slug", "discipline_id", "tier", "tier_rank", "bo_type",
    "tournament_id", "team1_id", "team2_id", "winner_team_id",
    "team1_score", "team2_score", "start_date", "end_date", "status",
]


def _upsert_matches(con, rows: list[dict]) -> int:
    if not rows:
        return 0
    updates = ", ".join(f"{c}=excluded.{c}" for c in _MATCH_COLS if c != "match_id")
    con.executemany(
        f"INSERT INTO matches ({', '.join(_MATCH_COLS)}) "
        f"VALUES ({', '.join('?' * len(_MATCH_COLS))}) "
        f"ON CONFLICT (match_id) DO UPDATE SET {updates}",
        [[r[c] for c in _MATCH_COLS] for r in rows],
    )
    return len(rows)


def backfill_matches(con, batch: int = 100) -> int:
    buf, total = [], 0
    for m in iter_finished_matches(limit=batch):
        buf.append(parse_match(m))
        if len(buf) >= batch:
            total += _upsert_matches(con, buf)
            buf = []
            if total % 500 == 0:
                print(f"  {total} matches ...")
    total += _upsert_matches(con, buf)
    return total


def fetch_teams(con, limit: int = 100) -> int:
    """Pull team names/ranks referenced by matches (all teams; CS2 spans many)."""
    offset, total = 0, 0
    while True:
        data = _get("/api/v1/teams", {"page[offset]": offset, "page[limit]": limit})
        results = data.get("results", [])
        if not results:
            break
        rows = [[t.get("id"), t.get("slug"), t.get("name"), t.get("rank"),
                 t.get("country_id")] for t in results]
        con.executemany(
            "INSERT INTO teams (team_id, slug, name, rank, country_id) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (team_id) DO UPDATE SET "
            "slug=excluded.slug, name=excluded.name, rank=excluded.rank, "
            "country_id=excluded.country_id",
            rows,
        )
        total += len(rows)
        offset += limit
        if offset >= data.get("total", {}).get("count", 0):
            break
    return total


def _norm(s):
    import re
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""


def fetch_games(match_id: int) -> list[dict]:
    data = _get("/api/v1/games", {"filter[games.match_id][eq]": match_id, "page[limit]": 20})
    return data.get("results", [])


def backfill_games(con, since: str = "2024-01-01") -> dict:
    """Per-map results for CS2-era matches. Winner resolved to team id via the
    match's two teams (clan_name -> team1/team2)."""
    matches = con.execute(
        "SELECT m.match_id, m.team1_id, m.team2_id, t1.name, t2.name "
        "FROM matches m JOIN teams t1 ON t1.team_id=m.team1_id "
        "JOIN teams t2 ON t2.team_id=m.team2_id "
        "WHERE m.start_date >= ? AND m.match_id NOT IN (SELECT DISTINCT match_id FROM games) "
        "ORDER BY m.start_date",
        [since],
    ).fetchall()
    n_matches = n_maps = 0
    buf = []
    for match_id, t1, t2, n1, n2 in matches:
        norm1, norm2 = _norm(n1), _norm(n2)
        for g in fetch_games(match_id):
            if g.get("status") != "finished":
                continue
            wn = _norm(g.get("winner_clan_name"))
            if wn == norm1:
                win, lose = t1, t2
            elif wn == norm2:
                win, lose = t2, t1
            else:
                continue  # unresolved winner name
            buf.append([g.get("id"), match_id, g.get("map_name"), g.get("number"),
                        win, lose, g.get("winner_clan_score"), g.get("loser_clan_score"),
                        _ts(g.get("begin_at")), g.get("status")])
            n_maps += 1
        n_matches += 1
        if len(buf) >= 200:
            _store_games(con, buf); buf = []
        if n_matches % 200 == 0:
            print(f"  {n_matches} matches, {n_maps} maps ...")
    _store_games(con, buf)
    return {"matches": n_matches, "maps": n_maps}


_GAME_COLS = ["game_id", "match_id", "map_name", "map_number", "winner_team_id",
              "loser_team_id", "winner_score", "loser_score", "start_date", "status"]


def _store_games(con, rows):
    if rows:
        con.executemany(
            f"INSERT OR REPLACE INTO games ({', '.join(_GAME_COLS)}) "
            f"VALUES ({', '.join('?' * len(_GAME_COLS))})",
            rows,
        )


if __name__ == "__main__":
    init_db()
    con = connect()
    try:
        n = backfill_matches(con)
        print(f"matches: {n}")
    finally:
        con.close()
