"""Map-level team Elo for CS2.

Rates each (team, map) separately from per-map results, capturing map-pool skill
(a team strong on Mirage, weak on Inferno) that series-level pricing under-models.
Two wins over plain match Elo: (1) ~2x more data (map results >> match results),
(2) per-map granularity.

Series win prob is derived from the average per-map win prob across the active
pool via the binomial (iid-map approximation; veto modeling is a later step).
Still leakage-free: a match is predicted from ratings built on strictly prior maps.
"""
from __future__ import annotations

import datetime as dt
import math

BASE = 1500.0
K = 32.0
DECAY_PER_DAY = 0.15


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def series_prob(p: float, bo: int) -> float:
    """P(win the Bo-n series) given iid per-map win prob p."""
    need = bo // 2 + 1
    return sum(math.comb(bo, k) * p ** k * (1 - p) ** (bo - k) for k in range(need, bo + 1))


class MapEloEngine:
    def __init__(self, k: float = K, decay_per_day: float = DECAY_PER_DAY):
        self.k = k
        self.decay_per_day = decay_per_day
        self.rating: dict[tuple[int, str], float] = {}
        self.last: dict[tuple[int, str], dt.datetime] = {}
        self.team_maps: dict[int, set] = {}

    def _team_mean(self, team: int) -> float:
        maps = self.team_maps.get(team)
        if not maps:
            return BASE
        return sum(self.rating[(team, m)] for m in maps) / len(maps)

    def _get(self, team: int, mp: str, when) -> float:
        key = (team, mp)
        if key not in self.rating:
            return self._team_mean(team)  # unseen map for this team -> its overall level
        r = self.rating[key]
        if self.decay_per_day and when is not None:
            last = self.last.get(key)
            if last is not None:
                last = last.replace(tzinfo=dt.timezone.utc) if last.tzinfo is None else last
                w = when.replace(tzinfo=dt.timezone.utc) if when.tzinfo is None else when
                days = max(0.0, (w - last).total_seconds() / 86400.0)
                r = r + (BASE - r) * min(days * self.decay_per_day, 150.0) / 400.0
        return r

    def predict_map(self, t1: int, t2: int, mp: str, when=None) -> float:
        return expected(self._get(t1, mp, when), self._get(t2, mp, when))

    def predict_series(self, t1: int, t2: int, bo: int, pool: list[str], when=None) -> float:
        ps = [self.predict_map(t1, t2, m, when) for m in pool]
        pbar = sum(ps) / len(ps) if ps else 0.5
        return series_prob(pbar, bo if bo in (1, 3, 5) else 3)

    def update_map(self, t1: int, t2: int, mp: str, t1_won: bool, when=None):
        r1, r2 = self._get(t1, mp, when), self._get(t2, mp, when)
        e1 = expected(r1, r2)
        s1 = 1.0 if t1_won else 0.0
        self.rating[(t1, mp)] = r1 + self.k * (s1 - e1)
        self.rating[(t2, mp)] = r2 + self.k * ((1 - s1) - (1 - e1))
        self.team_maps.setdefault(t1, set()).add(mp)
        self.team_maps.setdefault(t2, set()).add(mp)
        if when is not None:
            self.last[(t1, mp)] = when
            self.last[(t2, mp)] = when
