# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Train Isolation Forest ML Model
Trains on historical cell-day features to learn "normal" patterns
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
ML_CONTAMINATION = float(os.getenv("ML_CONTAMINATION", 0.1))
ML_N_ESTIMATORS = int(os.getenv("ML_N_ESTIMATORS", 100))

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)

# Features used for training
FEATURE_COLUMNS = [
    'hotspot_count',
    'total_frp',
    'max_frp',
    'delta_count_vs_prev_day',
    'ratio_vs_7d_avg',
    'neighbor_activity'
]


def load_training_data(engine, days_history: int = 90) -> pd.DataFrame:
    """Load features from database for training"""
    cutoff_date = datetime.now() - timedelta(days=days_history)

    logger.info(f"Loading features from last {days_history} days (since {cutoff_date.date()})...")

    df = pd.read_sql(text("""
        SELECT
            h3_index, date,
            hotspot_count, total_frp, max_frp,
            delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
        FROM cell_day_features
        WHERE date >= :cutoff_date
        AND hotspot_count > 0
        ORDER BY date, h3_index
    """), engine, params={"cutoff_date": cutoff_date.date()})

    logger.info(f"Loaded {len(df):,} cell-day samples")
    logger.info(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    logger.info(f"  Unique cells: {df['h3_index'].nunique():,}")

    return df


def train_isolation_forest(days_history: int = 90):
    """
    Train Isolation Forest on historical features

    Args:
        days_history: Number of days of historical data to use for training
    """
    engine = create_engine(DATABASE_URL)

    # 1. Load training data
    df = load_training_data(engine, days_history)

    if len(df) < 100:
        logger.error(f"Not enough data to train! Only {len(df)} samples. Need at least 100.")
        sys.exit(1)

    # 2. Prepare feature matrix
    X = df[FEATURE_COLUMNS].fillna(0)

    logger.info(f"\nFeature statistics:")
    for col in FEATURE_COLUMNS:
        logger.info(f"  {col}: mean={X[col].mean():.2f}, max={X[col].max():.2f}, std={X[col].std():.2f}")

    # 3. Scale features (important for Isolation Forest)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 4. Train Isolation Forest
    logger.info(f"\nTraining Isolation Forest...")
    logger.info(f"  contamination: {ML_CONTAMINATION} ({ML_CONTAMINATION*100:.0f}% expected anomalies)")
    logger.info(f"  n_estimators: {ML_N_ESTIMATORS} trees")
    logger.info(f"  training samples: {len(X_scaled):,}")

    model = IsolationForest(
        contamination=ML_CONTAMINATION,
        n_estimators=ML_N_ESTIMATORS,
        max_samples='auto',
        random_state=42,
        n_jobs=-1
    )

    model.fit(X_scaled)

    # 5. Evaluate on training data (sanity check)
    scores = model.decision_function(X_scaled)
    predictions = model.predict(X_scaled)

    anomaly_count = (predictions == -1).sum()
    normal_count = (predictions == 1).sum()

    logger.info(f"\nTraining evaluation:")
    logger.info(f"  Total samples: {len(predictions):,}")
    logger.info(f"  Anomalies detected: {anomaly_count:,} ({anomaly_count/len(predictions)*100:.1f}%)")
    logger.info(f"  Normal: {normal_count:,} ({normal_count/len(predictions)*100:.1f}%)")
    logger.info(f"  Score range: {scores.min():.4f} to {scores.max():.4f}")
    logger.info(f"  Score mean: {scores.mean():.4f}")

    # 6. Show top anomalies from training data
    df['anomaly_score'] = scores
    df['is_anomaly'] = predictions == -1

    top_anomalies = df[df['is_anomaly']].nsmallest(5, 'anomaly_score')
    logger.info(f"\nTop 5 anomalies found in training data:")
    for _, row in top_anomalies.iterrows():
        logger.info(f"  Cell {row['h3_index'][:10]}... on {row['date']}")
        logger.info(f"    Score: {row['anomaly_score']:.4f} | Hotspots: {row['hotspot_count']} | FRP: {row['total_frp']:.1f} MW | Ratio: {row['ratio_vs_7d_avg']:.2f}x")

    # 7. Save model + scaler + metadata
    models_dir = Path(__file__).parent.parent / 'models'
    models_dir.mkdir(exist_ok=True)

    model_path = models_dir / 'isolation_forest_v1.0.pkl'

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
        'score_stats': {
            'min': float(scores.min()),
            'max': float(scores.max()),
            'mean': float(scores.mean()),
            'std': float(scores.std()),
        }
    }

    joblib.dump(model_package, model_path)

    logger.info(f"\n✅ Model saved to: {model_path}")
    logger.info(f"   File size: {model_path.stat().st_size / 1024:.1f} KB")

    return model_package


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Train Isolation Forest model')
    parser.add_argument('--days', type=int, default=90, help='Days of history to train on (default: 90)')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🤖 Isolation Forest Training")
    logger.info("=" * 60)

    model_package = train_isolation_forest(days_history=args.days)

    print("\n" + "=" * 60)
    print("✅ Training complete!")
    print(f"   Model: models/isolation_forest_v1.0.pkl")
    print(f"   Trained on: {model_package['training_samples']:,} samples")
    print(f"   Contamination: {model_package['contamination']*100:.0f}%")
    print("\nNext steps:")
    print("  1. Score anomalies: python scripts/score_daily.py")
    print("  2. Select top-K:    python scripts/select_top_k.py")
    print("=" * 60)
