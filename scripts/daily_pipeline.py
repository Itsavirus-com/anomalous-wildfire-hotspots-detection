# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Daily Pipeline Orchestrator — region-aware full detection pipeline.

Usage:
    python scripts/daily_pipeline.py
    python scripts/daily_pipeline.py --days 1
    python scripts/daily_pipeline.py --skip fetch
"""

import os
import sys
import argparse
import traceback
from pathlib import Path
from datetime import datetime, date
from typing import Optional

from dotenv import load_dotenv
import logging

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(ROOT_DIR / 'src'))
sys.path.insert(0, str(SCRIPTS_DIR))

load_dotenv()

from wildfire_detection.regions import DATA_REGION, model_path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def run_step(name: str, fn, *args, dry_run: bool = False, **kwargs) -> dict:
    logger.info(f"\n{'='*55}")
    logger.info(f"  STEP: {name}")
    logger.info(f"{'='*55}")

    if dry_run:
        logger.info(f"  [DRY RUN] Skipping execution of {name}")
        return {"name": name, "status": "skipped", "duration_s": 0, "result": None, "error": None}

    started = datetime.now()
    try:
        result = fn(*args, **kwargs)
        duration = (datetime.now() - started).total_seconds()
        logger.info(f"\n  {name} completed in {duration:.1f}s")
        return {"name": name, "status": "success", "duration_s": duration, "result": result, "error": None}
    except Exception as e:
        duration = (datetime.now() - started).total_seconds()
        logger.error(f"\n  {name} FAILED after {duration:.1f}s")
        logger.error(f"  Error: {type(e).__name__}: {e}")
        logger.debug(traceback.format_exc())
        return {"name": name, "status": "failed", "duration_s": duration, "result": None, "error": str(e)}


def validate_environment():
    errors = []
    db_url = os.getenv("DATABASE_URL")
    if not db_url or "YOUR_DB" in db_url:
        errors.append("DATABASE_URL is not set or still has placeholder value in .env")

    model_file = ROOT_DIR / "models" / model_path()
    legacy = ROOT_DIR / "models" / "isolation_forest_world_v1.0.pkl"
    if not model_file.exists() and not legacy.exists():
        errors.append(
            f"Trained model not found at {model_file}. "
            "Run: python scripts/train_model.py"
        )

    if errors:
        for err in errors:
            logger.error(f"  x {err}")
        return False

    logger.info("  DATABASE_URL configured")
    logger.info("  Trained model found")
    return True


def check_data_exists(target_date: date, region_id: str) -> int:
    from sqlalchemy import create_engine, text
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        count = conn.execute(text("""
            SELECT COUNT(*) FROM raw_hotspots
            WHERE region = :region AND DATE(acq_datetime) = :d
        """), {"region": region_id, "d": target_date}).scalar()
    return count or 0


def run_pipeline(
    target_date: Optional[date] = None,
    dry_run: bool = False,
    skip_steps: list = None,
    top_k: int = 20,
    fetch_days: int = 2,
) -> bool:
    pipeline_start = datetime.now()
    skip_steps = skip_steps or []
    region_id = DATA_REGION

    if target_date is None:
        target_date = date.today()

    logger.info("=" * 55)
    logger.info("  WILDFIRE DETECTION — DAILY PIPELINE")
    logger.info("=" * 55)
    logger.info(f"  Region      : {region_id}")
    logger.info(f"  Target date : {target_date}")
    logger.info(f"  Dry run     : {dry_run}")
    logger.info(f"  Skip steps  : {skip_steps or 'none'}")
    logger.info(f"  Log file    : {log_file.name}")

    logger.info(f"\n{'='*55}")
    logger.info("  PRE-FLIGHT CHECKS")
    logger.info(f"{'='*55}")

    if not validate_environment():
        logger.error("Pre-flight checks failed. Aborting.")
        return False

    if not dry_run and "fetch" in skip_steps:
        hotspot_count = check_data_exists(target_date, region_id)
        if hotspot_count == 0:
            logger.warning(f"  No raw hotspot data for {target_date} ({region_id})")
        else:
            logger.info(f"  Found {hotspot_count:,} raw hotspot records for {target_date}")

    from fetch_daily import fetch_daily
    from aggregate_daily import aggregate_daily
    from build_features import build_features
    from score_daily import score_anomalies
    from select_top_k import select_top_k
    from enrich_h3_metadata import enrich_h3_metadata

    results = []

    if "fetch" not in skip_steps:
        results.append(run_step(
            f"Step 0: Fetch FIRMS hotspots → raw_hotspots ({region_id})",
            fetch_daily,
            target_date,
            fetch_days,
            dry_run=dry_run,
        ))
        if not dry_run and results[-1]["status"] == "success":
            count = check_data_exists(target_date, region_id)
            if count == 0:
                logger.warning(f"  Fetch succeeded but 0 records for {target_date} ({region_id})")
            else:
                logger.info(f"  {count:,} raw hotspot records now in DB for {target_date}")
    else:
        logger.info("\n[SKIPPED] Step 0: Fetch FIRMS data")

    if results and results[-1]["status"] == "failed":
        logger.error("Pipeline halted after Step 0 failure.")
        _print_summary(results, pipeline_start, target_date, region_id)
        return False

    if "aggregate" not in skip_steps:
        results.append(run_step(
            "Step 1: Aggregate hotspots → cell_day_aggregates",
            aggregate_daily, target_date,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 1: Aggregate")

    if results and results[-1]["status"] == "failed":
        _print_summary(results, pipeline_start, target_date, region_id)
        return False

    if "features" not in skip_steps:
        results.append(run_step(
            "Step 2: Build features → cell_day_features",
            build_features, target_date,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 2: Build features")

    if results and results[-1]["status"] == "failed":
        _print_summary(results, pipeline_start, target_date, region_id)
        return False

    if "score" not in skip_steps:
        results.append(run_step(
            "Step 3: Score anomalies → cell_day_scores",
            score_anomalies, target_date,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 3: Score anomalies")

    if results and results[-1]["status"] == "failed":
        _print_summary(results, pipeline_start, target_date, region_id)
        return False

    if "alerts" not in skip_steps:
        results.append(run_step(
            f"Step 4: Select top-{top_k} alerts → daily_alerts",
            select_top_k, target_date, top_k,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 4: Select alerts")

    if "enrich" not in skip_steps:
        results.append(run_step(
            "Step 5: Enrich new H3 cells → h3_cell_metadata",
            enrich_h3_metadata,
            False,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 5: Enrich H3 metadata")

    _print_summary(results, pipeline_start, target_date, region_id)
    failed = [r for r in results if r["status"] == "failed"]
    return len(failed) == 0


def _print_summary(results: list, started: datetime, target_date: date = None, region_id: str = None):
    total_duration = (datetime.now() - started).total_seconds()
    logger.info(f"\n{'='*55}")
    logger.info("  PIPELINE SUMMARY")
    logger.info(f"{'='*55}")
    if region_id:
        logger.info(f"  Region     : {region_id}")
    if target_date:
        logger.info(f"  Date       : {target_date}")
    logger.info(f"  Total time : {total_duration:.1f}s")
    for r in results:
        duration = f"{r['duration_s']:.1f}s" if r["duration_s"] else "—"
        logger.info(f"  [{r['status']:<7}] {r['name'][:45]:<45} [{duration:>6}]")
        if r["error"]:
            logger.info(f"       └─ {r['error'][:60]}")
    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        logger.info(f"\n  {len(failed)} step(s) failed — check log: {log_file.name}")
    else:
        logger.info("\n  All steps completed successfully!")
        logger.info(f"  View results: http://localhost:8000/docs")
    logger.info("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full wildfire detection pipeline")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Validate only — no DB writes")
    parser.add_argument("--skip", type=str, default="", help="Comma-separated steps to skip")
    parser.add_argument("--top-k", type=int, default=int(os.getenv("TOP_K_ALERTS", 20)))
    parser.add_argument("--days", type=int, default=2, help="FIRMS fetch day window (use 1 for world)")
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    skip_steps = [s.strip() for s in args.skip.split(",") if s.strip()]

    success = run_pipeline(
        target_date=target_date,
        dry_run=args.dry_run,
        skip_steps=skip_steps,
        top_k=args.top_k,
        fetch_days=args.days,
    )
    sys.exit(0 if success else 1)
