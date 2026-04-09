# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Map router — GET /api/map, GET /api/map/dates
"""

from datetime import date
from typing import Optional

import h3
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..dependencies import get_db
from ..schemas import MapCell, MapResponse, MapDatesResponse

router = APIRouter(prefix="/map", tags=["Map"])


@router.get("", response_model=MapResponse)
def get_map_cells(
    date: Optional[date] = Query(default=None, description="Date (YYYY-MM-DD). Defaults to latest."),
    db: Session = Depends(get_db),
):
    """
    Get all scored H3 cells for a date — used for rendering the hex map.
    Includes anomaly score, hotspot count, and center coordinates for every cell.
    """
    # Default to latest scored date
    if date is None:
        row = db.execute(text("SELECT MAX(date) as d FROM cell_day_scores")).fetchone()
        if not row or not row.d:
            raise HTTPException(status_code=404, detail="No scored data found")
        date = row.d

    rows = db.execute(text("""
        SELECT
            s.h3_index,
            s.anomaly_score,
            s.is_anomaly,
            f.hotspot_count,
            f.total_frp,
            m.center_lat,
            m.center_lng,
            m.province
        FROM cell_day_scores s
        LEFT JOIN cell_day_features f
            ON s.h3_index = f.h3_index AND s.date = f.date
        LEFT JOIN h3_cell_metadata m
            ON s.h3_index = m.h3_index
        WHERE s.date = :date
        ORDER BY s.anomaly_score ASC
    """), {"date": date}).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No data found for date {date}")

    cells = []
    for row in rows:
        lat = row.center_lat
        lng = row.center_lng
        if lat is None:
            lat, lng = h3.cell_to_latlng(row.h3_index)

        cells.append(MapCell(
            h3_index=row.h3_index,
            anomaly_score=float(row.anomaly_score),
            is_anomaly=bool(row.is_anomaly),
            hotspot_count=row.hotspot_count,
            total_frp=float(row.total_frp) if row.total_frp else None,
            center_lat=lat,
            center_lng=lng,
            province=row.province,
        ))

    anomaly_count = sum(1 for c in cells if c.is_anomaly)

    return MapResponse(
        date=date,
        total_cells=len(cells),
        anomaly_count=anomaly_count,
        cells=cells,
    )


@router.get("/dates", response_model=MapDatesResponse)
def get_available_dates(db: Session = Depends(get_db)):
    """Get all dates for which map/scoring data is available."""
    rows = db.execute(text("""
        SELECT DISTINCT date FROM cell_day_scores ORDER BY date ASC
    """)).fetchall()

    dates = [r.date for r in rows]
    return MapDatesResponse(
        dates=dates,
        total=len(dates),
        earliest=dates[0] if dates else None,
        latest=dates[-1] if dates else None,
    )
