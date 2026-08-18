# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Score Daily Anomalies — region-scoped Isolation Forest scoring
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date
from typing import Optional

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import joblib
import pandas as pd
import logging

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wildfire_detection.regions import DATA_REGION, model_path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)


def _resolve_model_file() -> Path:
    models_dir = Path(__file__).parent.parent / 'models'
    path = models_dir / model_path()
    if not path.exists():
        for alt in ("isolation_forest_world_v1.0.pkl", "isolation_forest_v1.0.pkl"):
            legacy = models_dir / alt
            if legacy.exists():
                return legacy
    return path


def score_anomalies(target_date: date = None):
    region_id = DATA_REGION
    model_file = _resolve_model_file()

    if not model_file.exists():
        logger.error(f"Model not found at {model_file}")
        logger.error("Run: python scripts/train_model.py")
        sys.exit(1)

    logger.info(f"Loading model from {model_file}...")
    model_package = joblib.load(model_file)
    model = model_package['model']
    scaler = model_package['scaler']
    feature_columns = model_package['feature_columns']
    model_version = model_package['version']

    engine = create_engine(DATABASE_URL)

    if target_date:
        logger.info(f"\nScoring features for {target_date} ({region_id})...")
        date_filter = "AND date = :target_date"
        params = {"target_date": target_date, "region": region_id}
    else:
        logger.info(f"\nScoring features for ALL dates ({region_id})...")
        date_filter = ""
        params = {"region": region_id}

    df = pd.read_sql(
        text(f"""
            SELECT h3_index, date,
                   hotspot_count, total_frp, max_frp,
                   delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
            FROM cell_day_features
            WHERE region = :region AND hotspot_count > 0 {date_filter}
            ORDER BY date, h3_index
        """),
        engine,
        params=params,
    )

    if df.empty:
        logger.warning("No features found to score!")
        return 0

    logger.info(f"Loaded {len(df):,} cell-day records to score")

    X = df[feature_columns].fillna(0)
    X_scaled = scaler.transform(X)
    scores = model.decision_function(X_scaled)
    predictions = model.predict(X_scaled)

    df['anomaly_score'] = scores
    df['is_anomaly'] = (predictions == -1)

    logger.info(f"Anomalies detected: {df['is_anomaly'].sum():,} ({df['is_anomaly'].mean()*100:.1f}%)")

    with engine.begin() as conn:
        if target_date:
            conn.execute(
                text("DELETE FROM cell_day_scores WHERE region = :region AND date = :date"),
                {"region": region_id, "date": target_date},
            )
        else:
            conn.execute(
                text("DELETE FROM cell_day_scores WHERE region = :region"),
                {"region": region_id},
            )

        batch_size = 500
        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i + batch_size]
            rows = [
                {
                    "region": region_id,
                    "h3_index": row.h3_index,
                    "date": row.date,
                    "anomaly_score": float(row.anomaly_score),
                    "is_anomaly": bool(row.is_anomaly),
                    "model_version": model_version,
                    "scored_at": datetime.now(),
                }
                for row in batch.itertuples()
            ]
            conn.execute(
                text("""
                    INSERT INTO cell_day_scores
                        (region, h3_index, date, anomaly_score, is_anomaly, model_version, scored_at)
                    VALUES
                        (:region, :h3_index, :date, :anomaly_score, :is_anomaly, :model_version, :scored_at)
                    ON CONFLICT (region, h3_index, date)
                    DO UPDATE SET
                        anomaly_score = EXCLUDED.anomaly_score,
                        is_anomaly = EXCLUDED.is_anomaly,
                        model_version = EXCLUDED.model_version,
                        scored_at = EXCLUDED.scored_at
                """),
                rows,
            )

    logger.info(f"Scoring complete! {len(df):,} records saved ({region_id})")
    return len(df)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Score cell-day anomalies using trained model')
    parser.add_argument('--date', type=str, help='Specific date to score (YYYY-MM-DD)')
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    count = score_anomalies(target_date)
    print(f"\nScored {count:,} cell-day records!")
    print("Next: python scripts/select_top_k.py")
