# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Stats router — GET /api/stats, GET /api/stats/daily
"""

from datetime import date
from typing import Optional
from pathlib import Path

import joblib
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..dependencies import get_db
from ..schemas import (
    StatsResponse, DatabaseStats, ModelStats, AlertStats,
    DailyStatsResponse, DailyStatItem,
)

router = APIRouter(prefix="/stats", tags=["Stats"])

MODEL_PATH = Path(__file__).parent.parent.parent.parent.parent / "models" / "isolation_forest_v1.0.pkl"


def _load_model_meta() -> dict:
    try:
        pkg = joblib.load(MODEL_PATH)
        return {
            "version": pkg.get("version", "v1.0"),
            "trained_at": pkg.get("trained_at"),
            "training_samples": pkg.get("training_samples"),
            "contamination": pkg.get("contamination"),
        }
    except Exception:
        return {"version": "unknown", "trained_at": None, "training_samples": None, "contamination": None}


@router.get("", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    """Overall system statistics — database counts, model info, and alert breakdown."""

    db_stats = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM raw_hotspots)          AS total_hotspots,
            (SELECT COUNT(*) FROM cell_day_scores)       AS total_cell_days,
            (SELECT COUNT(DISTINCT h3_index) FROM cell_day_scores) AS unique_cells,
            (SELECT MIN(date) FROM cell_day_scores)      AS date_range_start,
            (SELECT MAX(date) FROM cell_day_scores)      AS date_range_end
    """)).fetchone()

    alert_stats = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN spatial_coherence_level = 'high'     THEN 1 ELSE 0 END) AS high_coherence,
            SUM(CASE WHEN spatial_coherence_level = 'medium'   THEN 1 ELSE 0 END) AS medium_coherence,
            SUM(CASE WHEN spatial_coherence_level = 'low'      THEN 1 ELSE 0 END) AS low_coherence,
            SUM(CASE WHEN spatial_coherence_level = 'isolated' THEN 1 ELSE 0 END) AS isolated,
            SUM(CASE WHEN needs_manual_review = true           THEN 1 ELSE 0 END) AS needs_review
        FROM daily_alerts
    """)).fetchone()

    model_meta = _load_model_meta()

    return StatsResponse(
        database=DatabaseStats(
            total_hotspots=db_stats.total_hotspots or 0,
            total_cell_days=db_stats.total_cell_days or 0,
            unique_cells=db_stats.unique_cells or 0,
            date_range_start=db_stats.date_range_start,
            date_range_end=db_stats.date_range_end,
        ),
        model=ModelStats(
            version=model_meta["version"],
            trained_at=model_meta["trained_at"],
            training_samples=model_meta["training_samples"],
            contamination=model_meta["contamination"],
        ),
        alerts=AlertStats(
            total=alert_stats.total or 0,
            high_coherence=alert_stats.high_coherence or 0,
            medium_coherence=alert_stats.medium_coherence or 0,
            low_coherence=alert_stats.low_coherence or 0,
            isolated=alert_stats.isolated or 0,
            needs_review=alert_stats.needs_review or 0,
        ),
    )


@router.get("/daily", response_model=DailyStatsResponse)
def get_daily_stats(
    start: Optional[date] = Query(default=None, description="Start date"),
    end: Optional[date] = Query(default=None, description="End date"),
    db: Session = Depends(get_db),
):
    """Per-day statistics for chart rendering — hotspots, anomalies, and alerts per day."""

    params = {}
    date_filter = ""
    if start:
        date_filter += " AND s.date >= :start"
        params["start"] = start
    if end:
        date_filter += " AND s.date <= :end"
        params["end"] = end

    rows = db.execute(text(f"""
        SELECT
            s.date,
            COALESCE(SUM(f.hotspot_count), 0)           AS total_hotspots,
            COUNT(DISTINCT s.h3_index)                  AS active_cells,
            SUM(CASE WHEN s.is_anomaly THEN 1 ELSE 0 END) AS anomalies_detected,
            COUNT(DISTINCT a.h3_index)                  AS alerts_selected,
            MIN(a.hybrid_score)                         AS top_alert_score
        FROM cell_day_scores s
        LEFT JOIN cell_day_features f
            ON s.h3_index = f.h3_index AND s.date = f.date
        LEFT JOIN daily_alerts a
            ON s.h3_index = a.h3_index AND s.date = a.date
        WHERE 1=1 {date_filter}
        GROUP BY s.date
        ORDER BY s.date ASC
    """), params).fetchall()

    return DailyStatsResponse(
        start=start,
        end=end,
        days=[
            DailyStatItem(
                date=r.date,
                total_hotspots=r.total_hotspots or 0,
                active_cells=r.active_cells or 0,
                anomalies_detected=r.anomalies_detected or 0,
                alerts_selected=r.alerts_selected or 0,
                top_alert_score=float(r.top_alert_score) if r.top_alert_score else None,
            ) for r in rows
        ],
    )
