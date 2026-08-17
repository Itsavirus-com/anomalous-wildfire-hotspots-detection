# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Train Isolation Forest ML Model (per-region)
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wildfire_detection.regions import DATA_REGION, model_path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
ML_CONTAMINATION = float(os.getenv("ML_CONTAMINATION", 0.1))
ML_N_ESTIMATORS = int(os.getenv("ML_N_ESTIMATORS", 100))

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)

FEATURE_COLUMNS = [
    'hotspot_count',
    'total_frp',
    'max_frp',
    'delta_count_vs_prev_day',
    'ratio_vs_7d_avg',
    'neighbor_activity'
]


def load_training_data(engine, region: str, days_history: int = 90) -> pd.DataFrame:
    cutoff_date = datetime.now() - timedelta(days=days_history)
    logger.info(
        f"Loading features for region={region} from last {days_history} days "
        f"(since {cutoff_date.date()})..."
    )
    df = pd.read_sql(text("""
        SELECT
            h3_index, date,
            hotspot_count, total_frp, max_frp,
            delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
        FROM cell_day_features
        WHERE region = :region
          AND date >= :cutoff_date
          AND hotspot_count > 0
        ORDER BY date, h3_index
    """), engine, params={"region": region, "cutoff_date": cutoff_date.date()})

    logger.info(f"Loaded {len(df):,} cell-day samples")
    if not df.empty:
        logger.info(f"  Date range: {df['date'].min()} to {df['date'].max()}")
        logger.info(f"  Unique cells: {df['h3_index'].nunique():,}")
    return df


def train_isolation_forest(days_history: int = 90):
    region_id = DATA_REGION
    engine = create_engine(DATABASE_URL)
    df = load_training_data(engine, region_id, days_history)

    if len(df) < 100:
        logger.error(f"Not enough data to train! Only {len(df)} samples. Need at least 100.")
        sys.exit(1)

    X = df[FEATURE_COLUMNS].fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    logger.info(f"\nTraining Isolation Forest for region={region_id}...")
    logger.info(f"  contamination: {ML_CONTAMINATION}")
    logger.info(f"  n_estimators: {ML_N_ESTIMATORS}")
    logger.info(f"  training samples: {len(X_scaled):,}")

    model = IsolationForest(
        contamination=ML_CONTAMINATION,
        n_estimators=ML_N_ESTIMATORS,
        max_samples='auto',
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    scores = model.decision_function(X_scaled)
    predictions = model.predict(X_scaled)
    anomaly_count = (predictions == -1).sum()

    logger.info(f"\nTraining evaluation:")
    logger.info(f"  Anomalies: {anomaly_count:,} ({anomaly_count/len(predictions)*100:.1f}%)")

    models_dir = Path(__file__).parent.parent / 'models'
    models_dir.mkdir(exist_ok=True)
    out_path = models_dir / model_path()

    model_package = {
        'model': model,
        'scaler': scaler,
        'feature_columns': FEATURE_COLUMNS,
        'trained_at': datetime.now(),
        'training_days': days_history,
        'training_samples': len(X_scaled),
        'contamination': ML_CONTAMINATION,
        'n_estimators': ML_N_ESTIMATORS,
        'version': 'v1.0',
        'region': region_id,
        'score_stats': {
            'min': float(scores.min()),
            'max': float(scores.max()),
            'mean': float(scores.mean()),
            'std': float(scores.std()),
        }
    }
    joblib.dump(model_package, out_path)
    logger.info(f"\nModel saved to: {out_path}")
    return model_package


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Train Isolation Forest model')
    parser.add_argument('--days', type=int, default=90, help='Days of history to train on')
    args = parser.parse_args()

    model_package = train_isolation_forest(days_history=args.days)

    print("\n" + "=" * 60)
    print("Training complete!")
    print(f"   Model: models/{model_path()}")
    print(f"   Trained on: {model_package['training_samples']:,} samples")
    print("\nNext: python scripts/score_daily.py")
    print("=" * 60)
