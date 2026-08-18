# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""Tests for world-only FIRMS ingest, region column, and Indonesia map focus."""

import ast
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from wildfire_detection.regions import (
    DATA_REGION,
    FIRMS_AREA,
    INITIAL_MAP_BBOX,
    INITIAL_MAP_CENTER,
    INITIAL_MAP_ZOOM,
    bbox_list,
    firms_area_path,
    initial_map_view,
    model_path,
)
from wildfire_detection.models.cell_day_aggregate import CellDayAggregate
from wildfire_detection.models.cell_day_features import CellDayFeatures
from wildfire_detection.models.cell_day_scores import CellDayScores
from wildfire_detection.models.daily_alerts import DailyAlerts
from wildfire_detection.models.raw_hotspot import RawHotspot
from wildfire_detection.services.firms_ingestion import FIRMSClient, FIRMSIngester
from wildfire_detection.api.schemas import InitialMapView, MapBBox, MapConfigResponse


SCRIPTS = [
    ROOT / "scripts" / "fetch_daily.py",
    ROOT / "scripts" / "aggregate_daily.py",
    ROOT / "scripts" / "build_features.py",
    ROOT / "scripts" / "train_model.py",
    ROOT / "scripts" / "score_daily.py",
    ROOT / "scripts" / "select_top_k.py",
    ROOT / "scripts" / "daily_pipeline.py",
]


class TestWorldConfig(unittest.TestCase):
    def test_single_data_scope_is_world(self):
        self.assertEqual(DATA_REGION, "world")
        self.assertEqual(FIRMS_AREA, "world")
        self.assertEqual(firms_area_path(), "world")

    def test_model_filename(self):
        self.assertEqual(model_path(), "isolation_forest_v1.0.pkl")

    def test_indonesia_is_camera_only(self):
        view = initial_map_view()
        self.assertEqual(view["label"], "Indonesia")
        self.assertEqual(view["center_lat"], INITIAL_MAP_CENTER[0])
        self.assertEqual(view["center_lng"], INITIAL_MAP_CENTER[1])
        self.assertEqual(view["zoom"], INITIAL_MAP_ZOOM)
        self.assertEqual(view["bbox"]["west"], INITIAL_MAP_BBOX[0])
        self.assertEqual(view["bbox"]["south"], INITIAL_MAP_BBOX[1])
        self.assertEqual(view["bbox"]["east"], INITIAL_MAP_BBOX[2])
        self.assertEqual(view["bbox"]["north"], INITIAL_MAP_BBOX[3])
        self.assertEqual(bbox_list(), list(INITIAL_MAP_BBOX))
        self.assertEqual(firms_area_path(), "world")


class TestSchemas(unittest.TestCase):
    def test_map_config_schema(self):
        v = initial_map_view()
        cfg = MapConfigResponse(
            data_scope=DATA_REGION,
            initial_view=InitialMapView(
                center_lat=v["center_lat"],
                center_lng=v["center_lng"],
                zoom=v["zoom"],
                bbox=MapBBox(**v["bbox"]),
                label=v["label"],
            ),
        )
        dumped = cfg.model_dump()
        self.assertEqual(dumped["data_scope"], "world")
        self.assertEqual(dumped["initial_view"]["label"], "Indonesia")


class TestModelsHaveRegion(unittest.TestCase):
    def test_region_column_and_unique_keys(self):
        models = [
            (RawHotspot, None),
            (CellDayAggregate, "uq_cell_day_region"),
            (CellDayFeatures, "uq_cell_day_features_region"),
            (CellDayScores, "uq_cell_day_score_region"),
            (DailyAlerts, None),
        ]
        for model, unique_name in models:
            cols = {c.name for c in model.__table__.columns}
            self.assertIn("region", cols, msg=model.__tablename__)
            if unique_name:
                names = {c.name for c in model.__table__.constraints if getattr(c, "name", None)}
                self.assertIn(unique_name, names, msg=model.__tablename__)
                uq = next(c for c in model.__table__.constraints if c.name == unique_name)
                self.assertEqual(list(uq.columns.keys())[:1], ["region"])


class TestNoRegionSwitching(unittest.TestCase):
    def test_scripts_have_no_region_cli_flag(self):
        for path in SCRIPTS:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                attr = getattr(func, "attr", None)
                if attr != "add_argument":
                    continue
                args = []
                for a in node.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        args.append(a.value)
                self.assertNotIn("--region", args, msg=str(path))
                self.assertNotIn("region", args, msg=str(path))

    def test_regions_router_removed(self):
        routers_dir = ROOT / "src" / "wildfire_detection" / "api" / "routers"
        self.assertFalse((routers_dir / "regions.py").exists())
        init_text = (routers_dir / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("regions", init_text)
        self.assertIn("alerts", init_text)


class TestFIRMSIngestion(unittest.TestCase):
    def test_fetch_url_uses_world_area(self):
        client = FIRMSClient(map_key="testkey")
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                return None

            @property
            def text(self):
                return "latitude,longitude,frp\n-2.5,118.0,1.0\n"

        def fake_get(url, timeout=120):
            captured["url"] = url
            return FakeResp()

        with patch("wildfire_detection.services.firms_ingestion.requests.get", fake_get):
            df = client.fetch_hotspots(satellite="MODIS_NRT", days=1)

        self.assertIn("/world/", captured["url"])
        self.assertIn("/MODIS_NRT/", captured["url"])
        self.assertNotIn("/indonesia", captured["url"].lower())
        self.assertEqual(len(df), 1)

    def test_validate_and_parse_hotspot(self):
        ingester = FIRMSIngester(db_session=MagicMock(), h3_resolution=7)
        ok = pd.Series({
            "latitude": -2.5,
            "longitude": 118.0,
            "frp": 12.3,
            "confidence": "n",
            "acq_date": "2026-08-14",
            "acq_time": 930,
        })
        bad_frp = ok.copy()
        bad_frp["frp"] = -1
        bad_lat = ok.copy()
        bad_lat["latitude"] = 99
        self.assertTrue(ingester.validate_hotspot(ok))
        self.assertFalse(ingester.validate_hotspot(bad_frp))
        self.assertFalse(ingester.validate_hotspot(bad_lat))
        self.assertEqual(
            ingester.parse_acquisition_datetime(ok),
            datetime(2026, 8, 14, 9, 30),
        )
        self.assertEqual(ingester.confidence_to_int("h"), 95)
        self.assertEqual(ingester.confidence_to_int(80), 80)

    def test_ingest_tags_region_world(self):
        db = MagicMock()
        ingester = FIRMSIngester(db_session=db, h3_resolution=7)
        df = pd.DataFrame([{
            "latitude": -2.5,
            "longitude": 118.0,
            "frp": 10.0,
            "confidence": "n",
            "acq_date": "2026-08-14",
            "acq_time": 9,
            "satellite": "MODIS_NRT",
        }])
        inserted = ingester.ingest_dataframe(df)
        self.assertEqual(inserted, 1)
        added = db.add.call_args[0][0]
        self.assertEqual(added.region, "world")
        db.commit.assert_called_once()


class TestFetchDailyHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fetch_daily as fd
        cls.fd = fd

    def test_parse_confidence_and_datetime(self):
        self.assertEqual(self.fd.parse_confidence("h"), 95)
        self.assertEqual(self.fd.parse_confidence("n"), 60)
        self.assertEqual(self.fd.parse_confidence(77), 77)
        self.assertEqual(self.fd.parse_confidence(None), 50)
        self.assertEqual(
            self.fd.parse_acq_datetime("2026-08-14", 9),
            datetime(2026, 8, 14, 0, 9),
        )
        self.assertEqual(
            self.fd.parse_acq_datetime("2026-08-14", 1432),
            datetime(2026, 8, 14, 14, 32),
        )
        self.assertIsNone(self.fd.parse_acq_datetime("bad", "xx"))

    def test_fetch_satellite_url_is_world(self):
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                return None

            @property
            def text(self):
                return "latitude,longitude,acq_date,acq_time,frp,confidence\n-2,118,2026-08-14,9,1.0,n\n"

        def fake_get(url, timeout=120):
            captured["url"] = url
            return FakeResp()

        with patch.object(self.fd.requests, "get", fake_get):
            df = self.fd.fetch_satellite("MODIS_NRT", 1)
        self.assertIn("/world/", captured["url"])
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["source_satellite"], "MODIS_NRT")

    def test_h3_resolution_in_valid_range(self):
        self.assertGreaterEqual(self.fd.H3_RESOLUTION, 0)
        self.assertLessEqual(self.fd.H3_RESOLUTION, 15)


class TestAPIWorldScope(unittest.TestCase):
    def test_health(self):
        from wildfire_detection.api.main import health
        resp = health()
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'"status":"ok"', resp.body)

    def test_root_exposes_world_and_indonesia_view(self):
        from wildfire_detection.api.main import root
        body = root()
        self.assertEqual(body["data_scope"], "world")
        self.assertEqual(body["version"], "1.2.0")
        self.assertEqual(body["initial_map_view"]["label"], "Indonesia")
        self.assertEqual(body["endpoints"]["map_config"], "/api/map/config")
        self.assertNotIn("regions", body["endpoints"])

    def test_map_config(self):
        from wildfire_detection.api.routers.map import get_map_config
        dumped = get_map_config().model_dump()
        self.assertEqual(dumped["data_scope"], "world")
        self.assertEqual(dumped["initial_view"]["center_lat"], -2.5)
        self.assertEqual(dumped["initial_view"]["bbox"]["east"], 141.0)

    def test_no_regions_route(self):
        from wildfire_detection.api.main import app
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertNotIn("/api/regions", paths)
        self.assertIn("/api/map/config", paths)

    def test_openapi_has_no_region_query_param(self):
        from wildfire_detection.api.main import app
        schema = app.openapi()
        self.assertNotIn("/api/regions", schema["paths"])
        for path, methods in schema["paths"].items():
            for method, spec in methods.items():
                for param in spec.get("parameters", []):
                    if param.get("in") == "query":
                        self.assertNotEqual(
                            param.get("name"),
                            "region",
                            msg=f"{method.upper()} {path}",
                        )


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL not set")
class TestDatabaseWorldRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, text as sa_text
        cls.engine = create_engine(os.getenv("DATABASE_URL"))
        cls.sa_text = staticmethod(sa_text)
        try:
            with cls.engine.connect() as conn:
                conn.execute(sa_text("SELECT 1"))
            cls.reachable = True
        except Exception as exc:
            cls.reachable = False
            cls.skip_reason = str(exc)

    def setUp(self):
        if not getattr(type(self), "reachable", False):
            self.skipTest(f"database unreachable: {getattr(type(self), 'skip_reason', 'unknown')}")

    def test_region_column_on_pipeline_tables(self):
        from sqlalchemy import text as sa_text
        tables = [
            "raw_hotspots",
            "cell_day_aggregates",
            "cell_day_features",
            "cell_day_scores",
            "daily_alerts",
        ]
        with self.engine.connect() as conn:
            for table in tables:
                row = conn.execute(sa_text("""
                    SELECT data_type FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :t AND column_name = 'region'
                """), {"t": table}).fetchone()
                self.assertIsNotNone(row, msg=f"{table}.region missing")
                self.assertEqual(row[0], "character varying")

    def test_rows_tagged_world(self):
        from sqlalchemy import text as sa_text
        with self.engine.connect() as conn:
            distinct = conn.execute(sa_text(
                "SELECT DISTINCT region FROM raw_hotspots"
            )).fetchall()
            regions = {r[0] for r in distinct}
            if not regions:
                self.skipTest("raw_hotspots is empty")
            self.assertTrue(regions <= {"world"}, msg=f"unexpected regions: {regions}")


if __name__ == "__main__":
    unittest.main()
