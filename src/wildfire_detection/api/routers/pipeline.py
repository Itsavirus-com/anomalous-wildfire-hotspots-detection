# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Pipeline router — GET /api/pipeline/status, POST /api/pipeline/score
"""

import sys
import subprocess
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..dependencies import get_db
from ..schemas import PipelineStatus, ScoreRequest, ScoreResponse

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])

SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "scripts"


@router.get("/status", response_model=PipelineStatus)
def get_pipeline_status(db: Session = Depends(get_db)):
    """Health check — shows latest data date, total counts, and model version."""

    stats = db.execute(text("""
        SELECT
            (SELECT MAX(date)    FROM cell_day_scores)  AS latest_date,
            (SELECT COUNT(*)     FROM raw_hotspots)     AS total_hotspots,
            (SELECT COUNT(*)     FROM cell_day_scores)  AS total_scored,
            (SELECT COUNT(*)     FROM daily_alerts)     AS total_alerts,
            (SELECT model_version FROM cell_day_scores
             ORDER BY scored_at DESC LIMIT 1)           AS model_version
    """)).fetchone()

    return PipelineStatus(
        status="healthy",
        latest_data_date=stats.latest_date,
        total_hotspots=stats.total_hotspots or 0,
        total_scored=stats.total_scored or 0,
        total_alerts=stats.total_alerts or 0,
        model_version=stats.model_version,
    )


def _run_scoring(target_date: date):
    """Run score_daily.py for a specific date as a subprocess."""
    script = SCRIPTS_DIR / "score_daily.py"
    subprocess.run(
        [sys.executable, str(script), "--date", target_date.isoformat()],
        check=True,
        capture_output=True,
    )
    script_k = SCRIPTS_DIR / "select_top_k.py"
    subprocess.run(
        [sys.executable, str(script_k), "--date", target_date.isoformat()],
        check=True,
        capture_output=True,
    )


@router.post("/score", response_model=ScoreResponse)
def trigger_score(
    request: ScoreRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger re-scoring for a specific date.
    Runs score_daily.py + select_top_k.py in the background.
    """
    # Check data exists for that date
    count = db.execute(text("""
        SELECT COUNT(*) as cnt FROM cell_day_features WHERE date = :date
    """), {"date": request.date}).fetchone()

    if not count or count.cnt == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No feature data found for {request.date}. Run aggregate + build_features first."
        )

    # Queue scoring as background task
    background_tasks.add_task(_run_scoring, request.date)

    return ScoreResponse(
        status="queued",
        date=request.date,
        scored=count.cnt,
        message=f"Scoring {count.cnt} cells for {request.date}. Check /api/pipeline/status for updates.",
    )
