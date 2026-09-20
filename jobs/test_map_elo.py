"""Backtest map-level Elo vs match Elo vs Pinnacle (2026 test set).

Builds ratings chronologically from per-map results (leakage-free: each match is
predicted before its own maps update the ratings), then grades on the 2026 games
we have Pinnacle odds for.

Usage: py -m jobs.test_map_elo
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from cs2edge.db.schema import connect
from cs2edge.model.elo import run_chronological
from cs2edge.model.map_elo import MapEloEngine

CS2_ERA = "2024-01-01"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""


def _m(name, y, p):
    p = np.clip(np.array(p), 1e-6, 1 - 1e-6); y = np.array(y)
    print(f"  {name:9} n={len(y)}  logloss={log_loss(y,p,labels=[0,1]):.4f}  "
          f"brier={brier_score_loss(y,p):.4f}  auc={roc_auc_score(y,p):.3f}  "
          f"acc={((p>=.5).astype(int)==y).mean():.3f}")


def main() -> None:
    con = connect(read_only=True)
    try:
        matches = con.execute(
            "SELECT match_id, team1_id, team2_id, winner_team_id, bo_type, start_date "
            "FROM matches WHERE start_date >= ? AND team1_id IS NOT NULL AND team2_id "
            "IS NOT NULL AND winner_team_id IS NOT NULL ORDER BY start_date, match_id",
            [CS2_ERA],
        ).pl().to_dicts()
        game_rows = con.execute(
            "SELECT match_id, map_name, winner_team_id, loser_team_id, map_number "
            "FROM games WHERE winner_team_id IS NOT NULL ORDER BY match_id, map_number"
        ).fetchall()
        pool_rows = con.execute(
            "SELECT map_name, count(*) c FROM games GROUP BY map_name ORDER BY c DESC LIMIT 7"
        ).fetchall()
        odds = con.execute(
            """SELECT o.match_id, o.p1_name, o.team1_fair, o.team2_fair,
                      m.team1_id, t1.name t1name, t2.name t2name,
                      (m.winner_team_id=m.team1_id) team1_won
               FROM odds_pinnacle o JOIN matches m USING(match_id)
               JOIN teams t1 ON t1.team_id=m.team1_id JOIN teams t2 ON t2.team_id=m.team2_id
               WHERE year(m.start_date)=2026"""
        ).fetchall()
    finally:
        con.close()

    games_by_match = defaultdict(list)
    for match_id, mp, w, l, num in game_rows:
        games_by_match[match_id].append((mp, w, l))
    pool = [r[0] for r in pool_rows]
    print(f"matches {len(matches)} | maps {len(game_rows)} | active pool {pool}")

    # ---- map Elo, chronological by match ----
    eng = MapEloEngine()
    map_pred = {}
    for m in matches:
        t1, t2, bo, when = m["team1_id"], m["team2_id"], m["bo_type"] or 3, m["start_date"]
        map_pred[m["match_id"]] = eng.predict_series(t1, t2, bo, pool, when)
        for mp, w, l in games_by_match.get(m["match_id"], []):
            eng.update_map(w, l, mp, True, when)

    # ---- match Elo baseline ----
    match_pred = {p["match_id"]: p["p1_pred"] for p in run_chronological(matches)}

    # overall calibration vs actual
    y_all = [1 if m["winner_team_id"] == m["team1_id"] else 0 for m in matches]
    print("\n=== overall vs actual (2024+) ===")
    _m("map-elo", y_all, [map_pred[m["match_id"]] for m in matches])
    _m("match-elo", y_all, [match_pred[m["match_id"]] for m in matches])

    # vs Pinnacle on 2026
    y, p_map, p_match, p_pin = [], [], [], []
    for match_id, p1_name, f1, f2, t1id, t1n, t2n, t1won in odds:
        if match_id not in map_pred:
            continue
        mkt_t1 = f1 if _norm(p1_name) == _norm(t1n) else (f2 if _norm(p1_name) == _norm(t2n) else f1)
        y.append(int(t1won)); p_map.append(map_pred[match_id])
        p_match.append(match_pred[match_id]); p_pin.append(mkt_t1)

    print(f"\n=== vs Pinnacle (2026, n={len(y)}) ===")
    if y:
        _m("MAP-ELO", y, p_map)
        _m("MATCH-ELO", y, p_match)
        _m("PINNACLE", y, p_pin)
        llm = log_loss(np.array(y), np.clip(p_map, 1e-6, 1-1e-6), labels=[0, 1])
        llk = log_loss(np.array(y), np.clip(p_pin, 1e-6, 1-1e-6), labels=[0, 1])
        print(f"\n  map-elo - pinnacle logloss = {llm - llk:+.4f} (negative = beats close)")


if __name__ == "__main__":
    main()
