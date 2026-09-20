"""Backtest the Elo baseline: overall calibration, then vs Pinnacle on 2026.

Elo is built over all CS2-era matches (2024+) chronologically (leakage-free),
then graded against the Pinnacle closing line on the 2026 matches we have odds
for. Orientation (which team the market's p1 refers to) is resolved by name.

Usage: py -m jobs.test_elo
"""
from __future__ import annotations

import re

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from cs2edge.db.schema import connect
from cs2edge.model.elo import run_chronological

CS2_ERA = "2024-01-01"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""


def metrics(name, y, p):
    p = np.clip(np.array(p), 1e-6, 1 - 1e-6)
    y = np.array(y)
    print(f"  {name:8} n={len(y)}  logloss={log_loss(y,p,labels=[0,1]):.4f}  "
          f"brier={brier_score_loss(y,p):.4f}  auc={roc_auc_score(y,p):.3f}  "
          f"acc={((p>=.5).astype(int)==y).mean():.3f}")


def main() -> None:
    con = connect(read_only=True)
    try:
        matches = con.execute(
            "SELECT match_id, team1_id, team2_id, winner_team_id, start_date "
            "FROM matches WHERE start_date >= ? AND team1_id IS NOT NULL "
            "AND team2_id IS NOT NULL AND winner_team_id IS NOT NULL "
            "ORDER BY start_date, match_id",
            [CS2_ERA],
        ).pl().to_dicts()

        odds = con.execute(
            """
            SELECT o.match_id, o.p1_name, o.team1_fair, o.team2_fair,
                   m.team1_id, m.team2_id, t1.name t1name, t2.name t2name,
                   (m.winner_team_id = m.team1_id) AS team1_won
            FROM odds_pinnacle o
            JOIN matches m USING (match_id)
            JOIN teams t1 ON t1.team_id = m.team1_id
            JOIN teams t2 ON t2.team_id = m.team2_id
            WHERE year(m.start_date) = 2026
            """
        ).fetchall()
    finally:
        con.close()

    preds = run_chronological(matches)
    print(f"CS2-era matches (2024+): {len(matches)}")

    # overall Elo calibration vs actual (all matches with a prediction)
    y_all = [p["team1_won"] for p in preds]
    p_all = [p["p1_pred"] for p in preds]
    print("\n=== Elo vs actual (all 2024+ matches) ===")
    metrics("elo", y_all, p_all)

    # vs Pinnacle on 2026 odds set
    pred_by_match = {p["match_id"]: p["p1_pred"] for p in preds}
    y, pm, pk = [], [], []
    for match_id, p1_name, f1, f2, t1id, t2id, t1n, t2n, t1won in odds:
        if match_id not in pred_by_match:
            continue
        # market fair prob for bo3 team1: align p1_name to team1 or team2
        if _norm(p1_name) == _norm(t1n):
            mkt_t1 = f1
        elif _norm(p1_name) == _norm(t2n):
            mkt_t1 = f2
        else:
            mkt_t1 = f1  # fallback: assume participant1 == team1
        y.append(int(t1won))
        pm.append(pred_by_match[match_id])
        pk.append(mkt_t1)

    print(f"\n=== model vs Pinnacle (2026 test set, n={len(y)}) ===")
    if y:
        metrics("ELO", y, pm)
        metrics("PINNACLE", y, pk)
        ll_m = log_loss(np.array(y), np.clip(pm, 1e-6, 1-1e-6), labels=[0, 1])
        ll_k = log_loss(np.array(y), np.clip(pk, 1e-6, 1-1e-6), labels=[0, 1])
        print(f"\n  model - pinnacle logloss = {ll_m - ll_k:+.4f} "
              f"(negative = model beats the close)")


if __name__ == "__main__":
    main()
