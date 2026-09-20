"""Recency-weighted team Elo for CS2 (baseline).

Online/walk-forward by construction: each match is predicted from ratings built
on strictly prior matches, so the backtest is leakage-free. Recency is governed
by K (higher = more weight on recent results) plus an optional time-decay that
regresses idle teams toward the mean (CS2 teams go cold over roster breaks).

This is the team-level baseline. Player-based ratings (roster-aware) come next
and should beat it, since team Elo carries a rating through lineup changes.
"""
from __future__ import annotations

import datetime as dt
import math

BASE = 1500.0
K = 40.0
DECAY_PER_DAY = 0.20   # rating points pulled toward BASE per idle day
DECAY_CAP = 150.0


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


class EloEngine:
    def __init__(self, k: float = K, decay_per_day: float = DECAY_PER_DAY):
        self.k = k
        self.decay_per_day = decay_per_day
        self.rating: dict[int, float] = {}
        self.last_played: dict[int, dt.datetime] = {}

    def _get(self, team_id: int, when: dt.datetime | None) -> float:
        r = self.rating.get(team_id, BASE)
        if self.decay_per_day and when is not None:
            last = self.last_played.get(team_id)
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=dt.timezone.utc)
                w = when.replace(tzinfo=dt.timezone.utc) if when.tzinfo is None else when
                days = max(0.0, (w - last).total_seconds() / 86400.0)
                pull = min(days * self.decay_per_day, DECAY_CAP)
                r = r + (BASE - r) * (pull / 400.0)  # gentle regression toward mean
        return r

    def predict(self, team1: int, team2: int, when: dt.datetime | None = None) -> float:
        """P(team1 wins the match), pre-match."""
        return expected(self._get(team1, when), self._get(team2, when))

    def update(self, team1: int, team2: int, team1_won: bool, when: dt.datetime | None = None):
        r1, r2 = self._get(team1, when), self._get(team2, when)
        e1 = expected(r1, r2)
        s1 = 1.0 if team1_won else 0.0
        self.rating[team1] = r1 + self.k * (s1 - e1)
        self.rating[team2] = r2 + self.k * ((1 - s1) - (1 - e1))
        if when is not None:
            self.last_played[team1] = when
            self.last_played[team2] = when


def run_chronological(matches: list[dict]) -> list[dict]:
    """matches sorted by start_date asc. Returns per-match pre-match prediction
    (p1_pred) alongside the actual result, then updates ratings — leakage-free."""
    engine = EloEngine()
    out = []
    for m in matches:
        t1, t2 = m["team1_id"], m["team2_id"]
        w = m["winner_team_id"]
        when = m["start_date"]
        if not t1 or not t2 or not w:
            continue
        p1 = engine.predict(t1, t2, when)
        team1_won = (w == t1)
        out.append({
            "match_id": m["match_id"], "team1_id": t1, "team2_id": t2,
            "start_date": when, "p1_pred": p1, "team1_won": int(team1_won),
        })
        engine.update(t1, t2, team1_won, when)
    return out
