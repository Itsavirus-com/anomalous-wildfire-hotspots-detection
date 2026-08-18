# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Geographic configuration for wildfire detection.

Single data scope: global FIRMS `/world` ingest.
Initial map focus: Indonesia (center + bbox for first render only — not a data filter).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# Canonical FIRMS area + DB tag for all pipeline rows
DATA_REGION = "world"
FIRMS_AREA = "world"

# Model artifact (single global model)
MODEL_FILENAME = "isolation_forest_v1.0.pkl"

# Indonesia focus for initial map load (west, south, east, north)
INITIAL_MAP_BBOX: Tuple[float, float, float, float] = (95.0, -11.0, 141.0, 6.0)
INITIAL_MAP_CENTER: Tuple[float, float] = (-2.5, 118.0)  # lat, lng
INITIAL_MAP_ZOOM: int = 5


def firms_area_path() -> str:
    """FIRMS URL area segment — always global."""
    return FIRMS_AREA


def model_path() -> str:
    """Trained model filename."""
    return MODEL_FILENAME


def initial_map_view() -> Dict:
    """Viewport a client should use on first load (Indonesia focus)."""
    west, south, east, north = INITIAL_MAP_BBOX
    lat, lng = INITIAL_MAP_CENTER
    return {
        "center_lat": lat,
        "center_lng": lng,
        "zoom": INITIAL_MAP_ZOOM,
        "bbox": {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
        },
        "label": "Indonesia",
    }


def bbox_list() -> List[float]:
    return list(INITIAL_MAP_BBOX)
