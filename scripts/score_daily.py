# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Score Daily Anomalies
Applies trained Isolation Forest model to cell-day features
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import joblib
import numpy as np
import pandas as pd
import logging

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
MODEL_PATH = Path(__file__).parent.parent / 'models' / 'isolation_forest_v1.0.pkl'

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)


def score_anomalies(target_date: date = None):
    """
    Score cell-day features using trained Isolation Forest model.

    Args:
        target_date: Specific date to score (None = all dates)
    """
    # 1. Load model
    if not MODEL_PATH.exists():
        logger.error(f"Model not found at {MODEL_PATH}")
        logger.error("Run: python scripts/train_model.py first!")
        sys.exit(1)

    logger.info(f"Loading model from {MODEL_PATH}...")
    model_package = joblib.load(MODEL_PATH)
    model = model_package['model']
    scaler = model_package['scaler']
    feature_columns = model_package['feature_columns']
    model_version = model_package['version']

    logger.info(f"  Model version: {model_version}")
    logger.info(f"  Trained at: {model_package['trained_at']}")
    logger.info(f"  Features: {feature_columns}")

    # 2. Load features from DB
    engine = create_engine(DATABASE_URL)

    if target_date:
        logger.info(f"\nScoring features for {target_date}...")
        date_filter = "WHERE date = :target_date AND hotspot_count > 0"
        params = {"target_date": target_date}
    else:
        logger.info("\nScoring features for ALL dates...")
        date_filter = "WHERE hotspot_count > 0"
        params = {}

    df = pd.read_sql(
        text(f"""
            SELECT h3_index, date,
                   hotspot_count, total_frp, max_frp,
                   delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
            FROM cell_day_features
            {date_filter}
            ORDER BY date, h3_index
        """),
        engine,
        params=params
    )

    if df.empty:
        logger.warning("No features found to score!")
        return 0

    logger.info(f"Loaded {len(df):,} cell-day records to score")

    # 3. Scale and score
    X = df[feature_columns].fillna(0)
    X_scaled = scaler.transform(X)

    # decision_function: lower = more anomalous
    scores = model.decision_function(X_scaled)
    predictions = model.predict(X_scaled)  # -1 = anomaly, 1 = normal

    df['anomaly_score'] = scores
    df['is_anomaly'] = (predictions == -1)

    logger.info(f"\nScoring results:")
    logger.info(f"  Total scored: {len(df):,}")
    logger.info(f"  Anomalies detected: {df['is_anomaly'].sum():,} ({df['is_anomaly'].mean()*100:.1f}%)")
    logger.info(f"  Score range: {scores.min():.4f} to {scores.max():.4f}")
    logger.info(f"  Score mean: {scores.mean():.4f}")

    # 4. Save scores to DB
    logger.info(f"\nSaving scores to cell_day_scores table...")

    with engine.begin() as conn:
        # Clear existing scores for target date(s)
        if target_date:
            conn.execute(text("DELETE FROM cell_day_scores WHERE date = :date"), {"date": target_date})
        else:
            conn.execute(text("DELETE FROM cell_day_scores"))

        # Insert new scores in batches
        batch_size = 500
        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]
            rows = [
                {
                    "h3_index": row.h3_index,
                    "date": row.date,
                    "anomaly_score": float(row.anomaly_score),
                    "is_anomaly": bool(row.is_anomaly),
                    "model_version": model_version,
                    "scored_at": datetime.now()
                }
                for row in batch.itertuples()
            ]
            conn.execute(
                text("""
                    INSERT INTO cell_day_scores
                        (h3_index, date, anomaly_score, is_anomaly, model_version, scored_at)
                    VALUES
                        (:h3_index, :date, :anomaly_score, :is_anomaly, :model_version, :scored_at)
                    ON CONFLICT (h3_index, date)
                    DO UPDATE SET
                        anomaly_score = EXCLUDED.anomaly_score,
                        is_anomaly = EXCLUDED.is_anomaly,
                        model_version = EXCLUDED.model_version,
                        scored_at = EXCLUDED.scored_at
                """),
                rows
            )

            if (i // batch_size + 1) % 5 == 0:
                logger.info(f"  Saved {min(i+batch_size, len(df)):,} / {len(df):,}")

    # 5. Show top anomalies
    top_anomalies = df.nsmallest(10, 'anomaly_score')
    logger.info(f"\n🔥 Top 10 Most Anomalous Cell-Days:")
    for rank, (_, row) in enumerate(top_anomalies.iterrows(), 1):
        logger.info(
            f"  {rank:2}. [{row['date']}] Cell {row['h3_index'][:12]}... "
            f"score={row['anomaly_score']:.4f} | "
            f"hotspots={row['hotspot_count']} | "
            f"ratio={row['ratio_vs_7d_avg']:.2f}x | "
            f"neighbors={row['neighbor_activity']}"
        )

    logger.info(f"\n✅ Scoring complete! {len(df):,} records saved to cell_day_scores")
    return len(df)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Score cell-day anomalies using trained model')
    parser.add_argument('--date', type=str, help='Specific date to score (YYYY-MM-DD). Default: all dates')
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    logger.info("=" * 60)
    logger.info("📊 Anomaly Scoring")
    logger.info("=" * 60)

    count = score_anomalies(target_date)

    print("\n" + "=" * 60)
    print(f"✅ Scored {count:,} cell-day records!")
    print("\nNext step:")
    print("  Select top-K alerts: python scripts/select_top_k.py")
    print("=" * 60)
