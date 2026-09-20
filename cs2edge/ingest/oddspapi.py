"""OddsPapi ingestion: Pinnacle closing lines for Tier-1 CS2 matches.

Strategy to conserve the free-tier quota: pull CS2 fixtures for a date window,
match each to a bo3 Tier-1 match using our local DB (free), and only call the
per-fixture historical-odds endpoint for matches we actually have. Closing line =
last Pinnacle snapshot at/ before start time; de-vigged to a fair win prob.

Market 171 = Match Winner. players '0'/'1' = participant1/participant2 series.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Iterator

import requests

from cs2edge.config import ODDSPAPI_BASE, ODDSPAPI_KEY
from cs2edge.db.schema import connect, init_db

CS2_SPORT = 17
MATCH_WINNER = "171"

_SESSION = requests.Session()
_MIN_INTERVAL = 1.2  # seconds between calls (free-tier rate limit is tight)
_last_call = [0.0]


def _throttle():
    gap = time.monotonic() - _last_call[0]
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    _last_call[0] = time.monotonic()


def _get(path: str, params: dict) -> dict:
    params = {**params, "apiKey": ODDSPAPI_KEY}
    url = f"{ODDSPAPI_BASE}/v4{path}"
    for attempt in range(6):
        _throttle()
        try:
            r = _SESSION.get(url, params=params, timeout=30)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", 2 ** attempt))
            time.sleep(min(wait, 30))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""


def _windows(start: dt.date, end: dt.date, days: int = 9) -> Iterator[tuple[dt.date, dt.date]]:
    d = start
    while d <= end:
        hi = min(d + dt.timedelta(days=days), end)
        yield d, hi
        d = hi + dt.timedelta(days=1)


def _fixtures(frm: dt.date, to: dt.date) -> list[dict]:
    try:
        d = _get("/fixtures", {"sportId": CS2_SPORT, "from": frm.isoformat(), "to": to.isoformat()})
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return []  # no fixtures in this window
        raise
    return d if isinstance(d, list) else (d.get("data") or d.get("fixtures") or d.get("results") or [])


def _ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


class TeamResolver:
    """bo3 team-name/slug -> team_id, and (date, {ids}) -> match_id."""

    def __init__(self, con):
        self.by_name: dict[str, int] = {}
        for tid, name, slug in con.execute("SELECT team_id, name, slug FROM teams").fetchall():
            for key in (_norm(name), _norm(slug)):
                if key:
                    self.by_name.setdefault(key, tid)
        self.matches: dict[tuple, list[tuple]] = {}
        for mid, t1, t2, sd in con.execute(
            "SELECT match_id, team1_id, team2_id, start_date FROM matches"
        ).fetchall():
            if t1 and t2:
                self.matches.setdefault(frozenset((t1, t2)), []).append((mid, sd))

    def team_id(self, *names) -> int | None:
        for n in names:
            tid = self.by_name.get(_norm(n))
            if tid:
                return tid
        return None

    def match_id(self, id1, id2, start) -> int | None:
        cands = self.matches.get(frozenset((id1, id2)))
        if not cands:
            return None
        if start is None:
            return cands[0][0]
        best, bestdiff = None, None
        for mid, sd in cands:
            if sd is None:
                continue
            sd_ = sd.replace(tzinfo=dt.timezone.utc) if sd.tzinfo is None else sd
            diff = abs((sd_ - start).total_seconds())
            if diff <= 36 * 3600 and (bestdiff is None or diff < bestdiff):
                best, bestdiff = mid, diff
        return best


def _closing(history: dict, start: dt.datetime | None):
    """Return (price1, price2, limit, close_ts, n) from Pinnacle match-winner.

    Market 171 has two outcomes: '171' (participant1) and '172' (participant2),
    each with a single price series under players['0'].
    """
    try:
        outcomes = history["bookmakers"]["pinnacle"]["markets"][MATCH_WINNER]["outcomes"]
        s0 = outcomes["171"]["players"]["0"]
        s1 = outcomes["172"]["players"]["0"]
    except (KeyError, TypeError):
        return None
    if not s0 or not s1:
        return None

    def last_before(snaps):
        chosen = None
        for snap in snaps:
            ts = _ts(snap.get("createdAt"))
            if ts is None:
                continue
            if start is None or ts <= start + dt.timedelta(minutes=5):
                if chosen is None or ts >= _ts(chosen["createdAt"]):
                    chosen = snap
        return chosen or (snaps[-1] if snaps else None)

    c0, c1 = last_before(s0), last_before(s1)
    if not c0 or not c1:
        return None
    return (c0.get("price"), c1.get("price"), c0.get("limit"),
            _ts(c0.get("createdAt")), len(s0) + len(s1))


def _devig(p1, p2):
    if not p1 or not p2:
        return None, None
    i1, i2 = 1 / p1, 1 / p2
    return i1 / (i1 + i2), i2 / (i1 + i2)


def ingest_range(con, start: dt.date, end: dt.date) -> dict:
    resolver = TeamResolver(con)
    stats = {"fixtures": 0, "matched": 0, "odds_stored": 0, "no_pinnacle": 0}
    rows = []
    for frm, to in _windows(start, end):
        for f in _fixtures(frm, to):
            stats["fixtures"] += 1
            start_ts = _ts(f.get("startTime"))
            id1 = resolver.team_id(f.get("participant1Name"), f.get("participant1ShortName"), f.get("participant1Abbr"))
            id2 = resolver.team_id(f.get("participant2Name"), f.get("participant2ShortName"), f.get("participant2Abbr"))
            if id1 is None or id2 is None:
                continue
            mid = resolver.match_id(id1, id2, start_ts)
            if mid is None:
                continue
            stats["matched"] += 1
            if not (f.get("externalProviders") or {}).get("pinnacleId"):
                stats["no_pinnacle"] += 1
                continue
            fid = f["fixtureId"]
            try:
                hist = _get("/historical-odds", {"fixtureId": fid, "bookmakers": "pinnacle"})
            except requests.RequestException:
                continue
            close = _closing(hist, start_ts)
            if not close:
                continue
            p1, p2, lim, cts, n = close
            f1, f2 = _devig(p1, p2)
            rows.append([fid, mid, f.get("participant1Name"), f.get("participant2Name"),
                         start_ts, cts, p1, p2, f1, f2, lim, n])
            stats["odds_stored"] += 1
    if rows:
        con.executemany(
            "INSERT OR REPLACE INTO odds_pinnacle (fixture_id, match_id, p1_name, p2_name, "
            "start_time, close_ts, team1_close_price, team2_close_price, team1_fair, "
            "team2_fair, close_limit, n_snapshots) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return stats


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("start"); ap.add_argument("end")
    a = ap.parse_args()
    init_db()
    con = connect()
    try:
        print(ingest_range(con, dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)))
    finally:
        con.close()


if __name__ == "__main__":
    main()
