# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Daily Pipeline Orchestrator
Runs the full wildfire detection pipeline for a given date in one command.

Pipeline order:
    Step 1: Aggregate raw hotspots → cell_day_aggregates
    Step 2: Build features        → cell_day_features
    Step 3: Score anomalies       → cell_day_scores
    Step 4: Select top-K alerts   → daily_alerts
    Step 5: Enrich new H3 cells   → h3_cell_metadata (new cells only)

Usage:
    # Run for today
    python scripts/daily_pipeline.py

    # Run for a specific date
    python scripts/daily_pipeline.py --date 2026-01-15

    # Dry run (validate only, no DB writes)
    python scripts/daily_pipeline.py --dry-run

    # Skip specific steps
    python scripts/daily_pipeline.py --skip enrich
"""

import os
import sys
import argparse
import traceback
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional

from dotenv import load_dotenv
import logging

# ─── Path setup ───────────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(ROOT_DIR / 'src'))
sys.path.insert(0, str(SCRIPTS_DIR))

load_dotenv()

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ─── Logging ──────────────────────────────────────────────────────────────────
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


# ─── Step runners ─────────────────────────────────────────────────────────────

def run_step(name: str, fn, *args, dry_run: bool = False, **kwargs) -> dict:
    """
    Run a single pipeline step, capture timing + success/failure.
    Returns: {"name", "status", "duration_s", "result", "error"}
    """
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
        logger.info(f"\n  ✅ {name} completed in {duration:.1f}s")
        return {"name": name, "status": "success", "duration_s": duration, "result": result, "error": None}
    except Exception as e:
        duration = (datetime.now() - started).total_seconds()
        logger.error(f"\n  ❌ {name} FAILED after {duration:.1f}s")
        logger.error(f"  Error: {type(e).__name__}: {e}")
        logger.debug(traceback.format_exc())
        return {"name": name, "status": "failed", "duration_s": duration, "result": None, "error": str(e)}


def validate_environment():
    """Check that all required env vars and model file exist before running."""
    errors = []

    db_url = os.getenv("DATABASE_URL")
    if not db_url or "YOUR_DB" in db_url:
        errors.append("DATABASE_URL is not set or still has placeholder value in .env")

    model_path = ROOT_DIR / "models" / "isolation_forest_v1.0.pkl"
    if not model_path.exists():
        errors.append(f"Trained model not found at {model_path}. Run: python scripts/train_model.py first")

    if errors:
        for err in errors:
            logger.error(f"  ✗ {err}")
        return False

    logger.info(f"  ✓ DATABASE_URL configured")
    logger.info(f"  ✓ Trained model found")
    return True


def check_data_exists(target_date: date) -> int:
    """Check how many raw hotspot records exist for the target date."""
    from sqlalchemy import create_engine, text
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        count = conn.execute(text("""
            SELECT COUNT(*) FROM raw_hotspots
            WHERE DATE(acq_datetime) = :d
        """), {"d": target_date}).scalar()
    return count or 0


def run_pipeline(
    target_date: Optional[date] = None,
    dry_run: bool = False,
    skip_steps: list = None,
    top_k: int = 20,
) -> bool:
    """
    Run the full daily detection pipeline.

    Args:
        target_date: Date to process. Defaults to yesterday (last complete day).
        dry_run: If True, validate only — no DB writes.
        skip_steps: List of step names to skip. Options: aggregate, features, score, alerts, enrich
        top_k: Number of top alerts to select per day.

    Returns:
        True if all steps succeeded, False if any failed.
    """
    pipeline_start = datetime.now()
    skip_steps = skip_steps or []

    # Default: today — FIRMS NRT 'last 1 day' is a rolling 24h window ending NOW,
    # so the data it returns is for today's satellite passes, not yesterday.
    if target_date is None:
        target_date = date.today()

    logger.info("=" * 55)
    logger.info("  🔥 WILDFIRE DETECTION — DAILY PIPELINE")
    logger.info("=" * 55)
    logger.info(f"  Target date : {target_date}")
    logger.info(f"  Dry run     : {dry_run}")
    logger.info(f"  Skip steps  : {skip_steps or 'none'}")
    logger.info(f"  Log file    : {log_file.name}")
    logger.info(f"  Started at  : {pipeline_start.strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Pre-flight checks ──────────────────────────────────────────────────────
    logger.info(f"\n{'='*55}")
    logger.info("  PRE-FLIGHT CHECKS")
    logger.info(f"{'='*55}")

    if not validate_environment():
        logger.error("Pre-flight checks failed. Aborting.")
        return False

    if not dry_run and "fetch" in skip_steps:
        # Only check pre-existing data when fetch is skipped
        hotspot_count = check_data_exists(target_date)
        if hotspot_count == 0:
            logger.warning(f"  ⚠ No raw hotspot data for {target_date} — pipeline may produce 0 results")
        else:
            logger.info(f"  ✓ Found {hotspot_count:,} existing raw hotspot records for {target_date}")

    # ── Import step modules ────────────────────────────────────────────────────
    from fetch_daily import fetch_daily
    from aggregate_daily import aggregate_daily
    from build_features import build_features
    from score_daily import score_anomalies
    from select_top_k import select_top_k
    from enrich_h3_metadata import enrich_h3_metadata

    # ── Execute steps ──────────────────────────────────────────────────────────
    results = []

    # Step 0: Fetch live data from FIRMS API
    # Use days=2 to cover a 48h window — FIRMS rolling window straddles midnight
    if "fetch" not in skip_steps:
        results.append(run_step(
            "Step 0: Fetch FIRMS hotspots → raw_hotspots",
            fetch_daily, target_date, 2,
            dry_run=dry_run,
        ))

        # After fetch, verify data actually landed for target_date
        if not dry_run and results[-1]["status"] == "success":
            count = check_data_exists(target_date)
            if count == 0:
                logger.warning(f"  ⚠ Fetch succeeded but 0 records for {target_date} in DB")
                logger.warning(f"    Satellite may not have passed Indonesia yet, or low fire activity")
                logger.warning(f"    Continuing — steps 1-4 will process 0 records for this date")
            else:
                logger.info(f"  ✓ {count:,} raw hotspot records now in DB for {target_date}")
    else:
        logger.info("\n[SKIPPED] Step 0: Fetch FIRMS data")

    if results and results[-1]["status"] == "failed":
        logger.error("Pipeline halted after Step 0 failure.")
        _print_summary(results, pipeline_start)
        return False

    # Step 1: Aggregate
    if "aggregate" not in skip_steps:
        results.append(run_step(
            "Step 1: Aggregate hotspots → cell_day_aggregates",
            aggregate_daily, target_date,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 1: Aggregate")

    if results and results[-1]["status"] == "failed":
        logger.error("Pipeline halted after Step 1 failure.")
        _print_summary(results, pipeline_start)
        return False

    # Step 2: Build features
    if "features" not in skip_steps:
        results.append(run_step(
            "Step 2: Build features → cell_day_features",
            build_features, target_date,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 2: Build features")

    if results and results[-1]["status"] == "failed":
        logger.error("Pipeline halted after Step 2 failure.")
        _print_summary(results, pipeline_start)
        return False

    # Step 3: Score anomalies
    if "score" not in skip_steps:
        results.append(run_step(
            "Step 3: Score anomalies → cell_day_scores",
            score_anomalies, target_date,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 3: Score anomalies")

    if results and results[-1]["status"] == "failed":
        logger.error("Pipeline halted after Step 3 failure.")
        _print_summary(results, pipeline_start)
        return False

    # Step 4: Select top-K alerts
    if "alerts" not in skip_steps:
        results.append(run_step(
            f"Step 4: Select top-{top_k} alerts → daily_alerts",
            select_top_k, target_date, top_k,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 4: Select alerts")

    # Step 5: Enrich new H3 cells (non-blocking — failure here is OK)
    if "enrich" not in skip_steps:
        results.append(run_step(
            "Step 5: Enrich new H3 cells → h3_cell_metadata",
            enrich_h3_metadata,
            dry_run=dry_run,
        ))
    else:
        logger.info("\n[SKIPPED] Step 5: Enrich H3 metadata")

    # ── Final summary ──────────────────────────────────────────────────────────
    _print_summary(results, pipeline_start, target_date)

    failed = [r for r in results if r["status"] == "failed"]
    return len(failed) == 0


def _print_summary(results: list, started: datetime, target_date: date = None):
    """Print a clean summary table of all step results."""
    total_duration = (datetime.now() - started).total_seconds()

    logger.info(f"\n{'='*55}")
    logger.info("  PIPELINE SUMMARY")
    logger.info(f"{'='*55}")
    if target_date:
        logger.info(f"  Date       : {target_date}")
    logger.info(f"  Total time : {total_duration:.1f}s ({total_duration/60:.1f} min)")
    logger.info("")

    icons = {"success": "✅", "failed": "❌", "skipped": "⏭"}
    for r in results:
        icon = icons.get(r["status"], "?")
        duration = f"{r['duration_s']:.1f}s" if r["duration_s"] else "—"
        logger.info(f"  {icon}  {r['name'][:45]:<45} [{duration:>6}]")
        if r["error"]:
            logger.info(f"       └─ {r['error'][:60]}")

    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        logger.info(f"\n  ❌ {len(failed)} step(s) failed — check log: {log_file.name}")
    else:
        logger.info(f"\n  🎉 All steps completed successfully!")
        logger.info(f"  📊 View results at: http://localhost:8000/docs")
    logger.info("=" * 55)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the full wildfire detection pipeline for a given date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
  # Run for today (default)
  python scripts/daily_pipeline.py

  # Run for a specific historical date
  python scripts/daily_pipeline.py --date 2025-12-01

  # Dry run — validate only, no writes
  python scripts/daily_pipeline.py --dry-run

  # Skip enrichment (faster, if metadata already up to date)
  python scripts/daily_pipeline.py --skip enrich

  # Reprocess historical date — skip fetch (data already in DB)
  python scripts/daily_pipeline.py --date 2025-12-01 --skip fetch
        """
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Target date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate environment only — no DB writes"
    )
    parser.add_argument(
        "--skip", type=str, default="",
        help="Comma-separated steps to skip: aggregate,features,score,alerts,enrich"
    )
    parser.add_argument(
        "--top-k", type=int, default=int(os.getenv("TOP_K_ALERTS", 20)),
        help="Number of top alerts to select (default: TOP_K_ALERTS env or 20)"
    )

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
    )

    sys.exit(0 if success else 1)
