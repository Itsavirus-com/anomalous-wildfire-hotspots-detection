"""
Smoke test for NASA FIRMS world endpoint + initial map view helpers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wildfire_detection.regions import (
    DATA_REGION,
    firms_area_path,
    initial_map_view,
    model_path,
)


def test_world_only_config():
    assert DATA_REGION == "world"
    assert firms_area_path() == "world"
    assert model_path() == "isolation_forest_v1.0.pkl"
    view = initial_map_view()
    assert view["label"] == "Indonesia"
    assert view["center_lat"] == -2.5
    assert view["bbox"]["west"] == 95.0
    print("world-only config OK")
    print("initial_view:", view)


if __name__ == "__main__":
    test_world_only_config()
    print("All checks passed")
