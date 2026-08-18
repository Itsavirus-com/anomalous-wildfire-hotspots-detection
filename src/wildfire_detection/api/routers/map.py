# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Map router — world hotspot cells + Indonesia initial camera for first load.
"""

from datetime import date
from typing import Optional

import h3
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..dependencies import get_db
from ..schemas import (
    MapCell, MapResponse, MapDatesResponse, MapConfigResponse,
    InitialMapView, MapBBox,
)
from wildfire_detection.regions import DATA_REGION, initial_map_view

router = APIRouter(prefix="/map", tags=["Map"])


def _initial_view_model() -> InitialMapView:
    v = initial_map_view()
    return InitialMapView(
        center_lat=v["center_lat"],
        center_lng=v["center_lng"],
        zoom=v["zoom"],
        bbox=MapBBox(**v["bbox"]),
        label=v["label"],
    )


@router.get("/config", response_model=MapConfigResponse)
def get_map_config():
    """
    Bootstrap config for map clients.
    Data is global; `initial_view` centers the camera on Indonesia on first load.
    """
    return MapConfigResponse(
        data_scope=DATA_REGION,
        initial_view=_initial_view_model(),
    )


@router.get("", response_model=MapResponse)
def get_map_cells(
    date: Optional[date] = Query(default=None, description="Date (YYYY-MM-DD). Defaults to latest."),
    db: Session = Depends(get_db),
):
    """All scored H3 cells for a date (world data) + Indonesia initial_view."""
    if date is None:
        row = db.execute(text(
            "SELECT MAX(date) as d FROM cell_day_scores WHERE region = :r"
        ), {"r": DATA_REGION}).fetchone()
        if not row or not row.d:
            raise HTTPException(status_code=404, detail="No scored data found")
        date = row.d

    rows = db.execute(text("""
        SELECT
            s.h3_index, s.anomaly_score, s.is_anomaly,
            f.hotspot_count, f.total_frp,
            m.center_lat, m.center_lng, m.province
        FROM cell_day_scores s
        LEFT JOIN cell_day_features f
            ON s.region = f.region AND s.h3_index = f.h3_index AND s.date = f.date
        LEFT JOIN h3_cell_metadata m ON s.h3_index = m.h3_index
        WHERE s.region = :r AND s.date = :date
        ORDER BY s.anomaly_score ASC
    """), {"r": DATA_REGION, "date": date}).fetchall()

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

    return MapResponse(
        date=date,
        total_cells=len(cells),
        anomaly_count=sum(1 for c in cells if c.is_anomaly),
        cells=cells,
        initial_view=_initial_view_model(),
    )


@router.get("/dates", response_model=MapDatesResponse)
def get_available_dates(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT DISTINCT date FROM cell_day_scores
        WHERE region = :r ORDER BY date ASC
    """), {"r": DATA_REGION}).fetchall()
    dates = [r.date for r in rows]
    return MapDatesResponse(
        dates=dates,
        total=len(dates),
        earliest=dates[0] if dates else None,
        latest=dates[-1] if dates else None,
    )
