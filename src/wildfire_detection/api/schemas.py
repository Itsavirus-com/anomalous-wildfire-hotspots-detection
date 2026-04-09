# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Pydantic v2 schemas for all API responses
"""

from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel


# ─── Shared ──────────────────────────────────────────────────────────────────

class RegionInfo(BaseModel):
    province: Optional[str] = None
    regency: Optional[str] = None
    district: Optional[str] = None


# ─── Alerts ──────────────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    rank: int
    h3_index: str
    date: date
    anomaly_score: float
    hybrid_score: float
    spatial_coherence_level: Optional[str] = None
    coherence_reasons: Optional[List[str]] = None
    needs_manual_review: bool = False
    # From features join
    hotspot_count: Optional[int] = None
    total_frp: Optional[float] = None
    ratio_vs_7d_avg: Optional[float] = None
    neighbor_activity: Optional[int] = None
    # From metadata join
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    province: Optional[str] = None
    regency: Optional[str] = None


class AlertsResponse(BaseModel):
    date: date
    total_alerts: int
    alerts: List[AlertItem]


class AlertHistoryItem(BaseModel):
    date: date
    rank: int
    hybrid_score: float
    spatial_coherence_level: Optional[str] = None


class AlertHistoryResponse(BaseModel):
    h3_index: str
    province: Optional[str] = None
    regency: Optional[str] = None
    total_alerts: int
    alerts: List[AlertHistoryItem]


# ─── Map ─────────────────────────────────────────────────────────────────────

class MapCell(BaseModel):
    h3_index: str
    anomaly_score: float
    is_anomaly: bool
    hotspot_count: Optional[int] = None
    total_frp: Optional[float] = None
    center_lat: float
    center_lng: float
    province: Optional[str] = None


class MapResponse(BaseModel):
    date: date
    total_cells: int
    anomaly_count: int
    cells: List[MapCell]


class MapDatesResponse(BaseModel):
    dates: List[date]
    total: int
    earliest: Optional[date] = None
    latest: Optional[date] = None


# ─── Cells ───────────────────────────────────────────────────────────────────

class CellAggregate(BaseModel):
    hotspot_count: int
    total_frp: Optional[float] = None
    max_frp: Optional[float] = None
    avg_frp: Optional[float] = None


class CellFeatures(BaseModel):
    delta_count_vs_prev_day: Optional[float] = None
    ratio_vs_7d_avg: Optional[float] = None
    neighbor_activity: Optional[int] = None


class CellScore(BaseModel):
    anomaly_score: float
    is_anomaly: bool
    model_version: str


class CellAlert(BaseModel):
    rank: int
    hybrid_score: float
    spatial_coherence_level: Optional[str] = None
    needs_manual_review: bool = False


class CellDetail(BaseModel):
    h3_index: str
    date: date
    center_lat: float
    center_lng: float
    province: Optional[str] = None
    regency: Optional[str] = None
    district: Optional[str] = None
    aggregate: Optional[CellAggregate] = None
    features: Optional[CellFeatures] = None
    score: Optional[CellScore] = None
    alert: Optional[CellAlert] = None


class TimeseriesItem(BaseModel):
    date: date
    hotspot_count: int
    total_frp: Optional[float] = None
    is_anomaly: Optional[bool] = None
    anomaly_score: Optional[float] = None


class CellTimeseriesResponse(BaseModel):
    h3_index: str
    province: Optional[str] = None
    regency: Optional[str] = None
    days: int
    timeseries: List[TimeseriesItem]


class NeighborCell(BaseModel):
    h3_index: str
    hotspot_count: Optional[int] = None
    is_anomaly: Optional[bool] = None
    anomaly_score: Optional[float] = None
    center_lat: float
    center_lng: float


class CellNeighborsResponse(BaseModel):
    h3_index: str
    date: date
    active_neighbor_count: int
    anomalous_neighbor_count: int
    neighbors: List[NeighborCell]


# ─── Stats ───────────────────────────────────────────────────────────────────

class DatabaseStats(BaseModel):
    total_hotspots: int
    total_cell_days: int
    unique_cells: int
    date_range_start: Optional[date] = None
    date_range_end: Optional[date] = None


class ModelStats(BaseModel):
    version: str
    trained_at: Optional[datetime] = None
    training_samples: Optional[int] = None
    contamination: Optional[float] = None


class AlertStats(BaseModel):
    total: int
    high_coherence: int
    medium_coherence: int
    low_coherence: int
    isolated: int
    needs_review: int


class StatsResponse(BaseModel):
    database: DatabaseStats
    model: ModelStats
    alerts: AlertStats


class DailyStatItem(BaseModel):
    date: date
    total_hotspots: int
    active_cells: int
    anomalies_detected: int
    alerts_selected: int
    top_alert_score: Optional[float] = None


class DailyStatsResponse(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None
    days: List[DailyStatItem]


# ─── Pipeline ────────────────────────────────────────────────────────────────

class PipelineStatus(BaseModel):
    status: str
    latest_data_date: Optional[date] = None
    total_hotspots: int
    total_scored: int
    total_alerts: int
    model_version: Optional[str] = None


class ScoreRequest(BaseModel):
    date: date


class ScoreResponse(BaseModel):
    status: str
    date: date
    scored: int
    message: str
