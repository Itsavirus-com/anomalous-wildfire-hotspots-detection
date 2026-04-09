# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Cells router — GET /api/cells/{h3_index}, /timeseries, /neighbors
"""

from datetime import date, datetime, timedelta
from typing import Optional

import h3
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..dependencies import get_db
from ..schemas import (
    CellDetail, CellAggregate, CellFeatures, CellScore, CellAlert,
    CellTimeseriesResponse, TimeseriesItem,
    CellNeighborsResponse, NeighborCell,
)

router = APIRouter(prefix="/cells", tags=["Cells"])


def _cell_coords(h3_index: str, meta_row) -> tuple:
    if meta_row and meta_row.center_lat:
        return meta_row.center_lat, meta_row.center_lng
    return h3.cell_to_latlng(h3_index)


@router.get("/{h3_index}", response_model=CellDetail)
def get_cell_detail(
    h3_index: str,
    date: Optional[date] = Query(default=None, description="Date (YYYY-MM-DD). Defaults to latest."),
    db: Session = Depends(get_db),
):
    """Full detail for a specific H3 cell on a given date."""

    if date is None:
        row = db.execute(text(
            "SELECT MAX(date) as d FROM cell_day_scores WHERE h3_index = :h3"
        ), {"h3": h3_index}).fetchone()
        if not row or not row.d:
            raise HTTPException(status_code=404, detail=f"Cell {h3_index} not found")
        date = row.d

    agg = db.execute(text("""
        SELECT hotspot_count, total_frp, max_frp, avg_frp
        FROM cell_day_aggregates
        WHERE h3_index = :h3 AND date = :date
    """), {"h3": h3_index, "date": date}).fetchone()

    feat = db.execute(text("""
        SELECT delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
        FROM cell_day_features
        WHERE h3_index = :h3 AND date = :date
    """), {"h3": h3_index, "date": date}).fetchone()

    score = db.execute(text("""
        SELECT anomaly_score, is_anomaly, model_version
        FROM cell_day_scores
        WHERE h3_index = :h3 AND date = :date
    """), {"h3": h3_index, "date": date}).fetchone()

    alert = db.execute(text("""
        SELECT rank, hybrid_score, spatial_coherence_level, needs_manual_review
        FROM daily_alerts
        WHERE h3_index = :h3 AND date = :date
    """), {"h3": h3_index, "date": date}).fetchone()

    meta = db.execute(text("""
        SELECT center_lat, center_lng, province, regency, district
        FROM h3_cell_metadata WHERE h3_index = :h3
    """), {"h3": h3_index}).fetchone()

    lat, lng = _cell_coords(h3_index, meta)

    return CellDetail(
        h3_index=h3_index,
        date=date,
        center_lat=lat,
        center_lng=lng,
        province=meta.province if meta else None,
        regency=meta.regency if meta else None,
        district=meta.district if meta else None,
        aggregate=CellAggregate(
            hotspot_count=agg.hotspot_count,
            total_frp=float(agg.total_frp) if agg and agg.total_frp else None,
            max_frp=float(agg.max_frp) if agg and agg.max_frp else None,
            avg_frp=float(agg.avg_frp) if agg and agg.avg_frp else None,
        ) if agg else None,
        features=CellFeatures(
            delta_count_vs_prev_day=float(feat.delta_count_vs_prev_day) if feat and feat.delta_count_vs_prev_day is not None else None,
            ratio_vs_7d_avg=float(feat.ratio_vs_7d_avg) if feat and feat.ratio_vs_7d_avg is not None else None,
            neighbor_activity=feat.neighbor_activity if feat else None,
        ) if feat else None,
        score=CellScore(
            anomaly_score=float(score.anomaly_score),
            is_anomaly=bool(score.is_anomaly),
            model_version=score.model_version,
        ) if score else None,
        alert=CellAlert(
            rank=alert.rank,
            hybrid_score=float(alert.hybrid_score),
            spatial_coherence_level=alert.spatial_coherence_level,
            needs_manual_review=bool(alert.needs_manual_review),
        ) if alert else None,
    )


@router.get("/{h3_index}/timeseries", response_model=CellTimeseriesResponse)
def get_cell_timeseries(
    h3_index: str,
    days: int = Query(default=30, ge=1, le=365, description="Number of days to show"),
    db: Session = Depends(get_db),
):
    """30-day time series for a cell — use for chart rendering."""
    cutoff = datetime.now().date() - timedelta(days=days)

    meta = db.execute(text(
        "SELECT province, regency FROM h3_cell_metadata WHERE h3_index = :h3"
    ), {"h3": h3_index}).fetchone()

    rows = db.execute(text("""
        SELECT
            f.date, f.hotspot_count, f.total_frp,
            s.is_anomaly, s.anomaly_score
        FROM cell_day_features f
        LEFT JOIN cell_day_scores s
            ON f.h3_index = s.h3_index AND f.date = s.date
        WHERE f.h3_index = :h3 AND f.date >= :cutoff
        ORDER BY f.date ASC
    """), {"h3": h3_index, "cutoff": cutoff}).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No timeseries data for cell {h3_index}")

    return CellTimeseriesResponse(
        h3_index=h3_index,
        province=meta.province if meta else None,
        regency=meta.regency if meta else None,
        days=days,
        timeseries=[
            TimeseriesItem(
                date=r.date,
                hotspot_count=r.hotspot_count,
                total_frp=float(r.total_frp) if r.total_frp else None,
                is_anomaly=bool(r.is_anomaly) if r.is_anomaly is not None else None,
                anomaly_score=float(r.anomaly_score) if r.anomaly_score is not None else None,
            ) for r in rows
        ],
    )


@router.get("/{h3_index}/neighbors", response_model=CellNeighborsResponse)
def get_cell_neighbors(
    h3_index: str,
    date: Optional[date] = Query(default=None, description="Date (YYYY-MM-DD). Defaults to latest."),
    db: Session = Depends(get_db),
):
    """Get activity of all 6 neighboring H3 cells for a given date."""
    if date is None:
        row = db.execute(text(
            "SELECT MAX(date) as d FROM cell_day_scores WHERE h3_index = :h3"
        ), {"h3": h3_index}).fetchone()
        date = row.d if row else datetime.now().date()

    neighbor_ids = list(h3.grid_ring(h3_index, 1))

    rows = db.execute(text("""
        SELECT
            s.h3_index, f.hotspot_count, s.is_anomaly, s.anomaly_score,
            m.center_lat, m.center_lng
        FROM cell_day_scores s
        LEFT JOIN cell_day_features f
            ON s.h3_index = f.h3_index AND s.date = f.date
        LEFT JOIN h3_cell_metadata m
            ON s.h3_index = m.h3_index
        WHERE s.h3_index = ANY(:neighbors) AND s.date = :date
    """), {"neighbors": neighbor_ids, "date": date}).fetchall()

    neighbors = []
    for row in rows:
        lat = row.center_lat
        lng = row.center_lng
        if lat is None:
            lat, lng = h3.cell_to_latlng(row.h3_index)

        neighbors.append(NeighborCell(
            h3_index=row.h3_index,
            hotspot_count=row.hotspot_count,
            is_anomaly=bool(row.is_anomaly) if row.is_anomaly is not None else None,
            anomaly_score=float(row.anomaly_score) if row.anomaly_score is not None else None,
            center_lat=lat,
            center_lng=lng,
        ))

    active = sum(1 for n in neighbors if n.hotspot_count and n.hotspot_count > 0)
    anomalous = sum(1 for n in neighbors if n.is_anomaly)

    return CellNeighborsResponse(
        h3_index=h3_index,
        date=date,
        active_neighbor_count=active,
        anomalous_neighbor_count=anomalous,
        neighbors=neighbors,
    )
