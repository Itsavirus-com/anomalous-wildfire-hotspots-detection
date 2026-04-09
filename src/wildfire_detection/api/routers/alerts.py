# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Alerts router — GET /api/alerts, GET /api/alerts/history
"""

import json
import time
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import h3
import requests
from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..dependencies import get_db
from ..schemas import AlertItem, AlertsResponse, AlertHistoryItem, AlertHistoryResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["Alerts"])

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {"User-Agent": "WildfireDetectionAPI/1.0"}


def _parse_coherence_reasons(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return []


def _get_cell_coords(h3_index: str):
    lat, lng = h3.cell_to_latlng(h3_index)
    return lat, lng


def _geocode_and_save(h3_index: str, lat: float, lng: float, db_url: str):
    """
    Background task: reverse-geocode a new H3 cell and persist to h3_cell_metadata.
    Called only when province is missing — writes province/regency/district/coords.
    """
    try:
        time.sleep(1)  # Nominatim rate limit
        resp = requests.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lng, "format": "json", "addressdetails": 1},
            headers=NOMINATIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            logger.debug(f"Nominatim: no result for {h3_index}")
            return

        addr = data.get("address", {})
        province = addr.get("state")
        regency  = addr.get("county") or addr.get("city")
        district = addr.get("suburb") or addr.get("town") or addr.get("village")

        from sqlalchemy import create_engine
        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO h3_cell_metadata (h3_index, center_lat, center_lng, province, regency, district, updated_at)
                VALUES (:h3, :lat, :lng, :province, :regency, :district, NOW())
                ON CONFLICT (h3_index) DO UPDATE SET
                    province   = COALESCE(EXCLUDED.province,  h3_cell_metadata.province),
                    regency    = COALESCE(EXCLUDED.regency,   h3_cell_metadata.regency),
                    district   = COALESCE(EXCLUDED.district,  h3_cell_metadata.district),
                    center_lat = EXCLUDED.center_lat,
                    center_lng = EXCLUDED.center_lng,
                    updated_at = NOW()
            """), {"h3": h3_index, "lat": lat, "lng": lng,
                   "province": province, "regency": regency, "district": district})

        logger.info(f"Geocoded new cell {h3_index[:12]}... → {province}, {regency}")

    except Exception as e:
        logger.warning(f"Background geocode failed for {h3_index}: {e}")


@router.get("", response_model=AlertsResponse)
def get_alerts(
    background_tasks: BackgroundTasks,
    date: Optional[date] = Query(default=None, description="Date (YYYY-MM-DD). Defaults to latest available."),
    k: int = Query(default=20, ge=1, le=100, description="Number of alerts to return"),
    coherence: Optional[str] = Query(default=None, description="Filter by coherence level: high, medium, low, isolated"),
    db: Session = Depends(get_db),
):
    """Get top-K anomaly alerts for a specific date, joined with region metadata."""

    # Default to latest available date
    if date is None:
        row = db.execute(text("SELECT MAX(date) as d FROM daily_alerts")).fetchone()
        if row is None or row.d is None:
            raise HTTPException(status_code=404, detail="No alerts found in database")
        date = row.d

    # Build coherence filter
    coherence_filter = ""
    params = {"date": date, "k": k}
    if coherence:
        coherence_filter = "AND a.spatial_coherence_level = :coherence"
        params["coherence"] = coherence

    rows = db.execute(text(f"""
        SELECT
            a.rank, a.h3_index, a.date,
            a.anomaly_score, a.hybrid_score,
            a.spatial_coherence_level, a.coherence_reasons,
            a.needs_manual_review,
            f.hotspot_count, f.total_frp, f.ratio_vs_7d_avg, f.neighbor_activity,
            m.center_lat, m.center_lng, m.province, m.regency
        FROM daily_alerts a
        LEFT JOIN cell_day_features f
            ON a.h3_index = f.h3_index AND a.date = f.date
        LEFT JOIN h3_cell_metadata m
            ON a.h3_index = m.h3_index
        WHERE a.date = :date
        {coherence_filter}
        ORDER BY a.rank
        LIMIT :k
    """), params).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No alerts found for date {date}")

    # Collect cells with missing geocoding so we can enrich them in background
    from ..dependencies import DATABASE_URL as _db_url

    alerts = []
    cells_to_geocode = []

    for row in rows:
        # Fallback: calc coords from H3 if not in metadata yet
        lat = row.center_lat
        lng = row.center_lng
        if lat is None:
            lat, lng = _get_cell_coords(row.h3_index)

        # Schedule background geocoding for cells missing province
        if row.province is None:
            cells_to_geocode.append((row.h3_index, lat, lng))

        alerts.append(AlertItem(
            rank=row.rank,
            h3_index=row.h3_index,
            date=row.date,
            anomaly_score=float(row.anomaly_score),
            hybrid_score=float(row.hybrid_score),
            spatial_coherence_level=row.spatial_coherence_level,
            coherence_reasons=_parse_coherence_reasons(row.coherence_reasons),
            needs_manual_review=bool(row.needs_manual_review),
            hotspot_count=row.hotspot_count,
            total_frp=float(row.total_frp) if row.total_frp else None,
            ratio_vs_7d_avg=float(row.ratio_vs_7d_avg) if row.ratio_vs_7d_avg else None,
            neighbor_activity=row.neighbor_activity,
            center_lat=lat,
            center_lng=lng,
            province=row.province,
            regency=row.regency,
        ))

    # Enrich unmapped cells in background (non-blocking — response goes out immediately)
    for h3_idx, lat, lng in cells_to_geocode:
        background_tasks.add_task(_geocode_and_save, h3_idx, lat, lng, _db_url)

    if cells_to_geocode:
        logger.info(f"Queued {len(cells_to_geocode)} cells for background geocoding")

    return AlertsResponse(date=date, total_alerts=len(alerts), alerts=alerts)


@router.get("/history", response_model=AlertHistoryResponse)
def get_alert_history(
    h3_index: str = Query(..., description="H3 cell index"),
    days: int = Query(default=30, ge=1, le=365, description="Number of days to look back"),
    db: Session = Depends(get_db),
):
    """Get alert history for a specific H3 cell."""
    cutoff = datetime.now().date() - timedelta(days=days)

    meta = db.execute(text("""
        SELECT province, regency FROM h3_cell_metadata WHERE h3_index = :h3
    """), {"h3": h3_index}).fetchone()

    rows = db.execute(text("""
        SELECT date, rank, hybrid_score, spatial_coherence_level
        FROM daily_alerts
        WHERE h3_index = :h3 AND date >= :cutoff
        ORDER BY date DESC
    """), {"h3": h3_index, "cutoff": cutoff}).fetchall()

    return AlertHistoryResponse(
        h3_index=h3_index,
        province=meta.province if meta else None,
        regency=meta.regency if meta else None,
        total_alerts=len(rows),
        alerts=[
            AlertHistoryItem(
                date=r.date,
                rank=r.rank,
                hybrid_score=float(r.hybrid_score),
                spatial_coherence_level=r.spatial_coherence_level,
            ) for r in rows
        ],
    )
