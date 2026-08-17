# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Select Top-K Anomalies with Spatial Coherence Validation (region-scoped)
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, date
from typing import Optional

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import h3
import logging

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wildfire_detection.regions import DATA_REGION

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
TOP_K = int(os.getenv("TOP_K_ALERTS", 20))

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)


def get_spatial_coherence(h3_index: str, current_date: date, region: str, conn) -> dict:
    neighbors = list(h3.grid_ring(h3_index, 1))

    active_result = conn.execute(text("""
        SELECT COUNT(*) as active_count
        FROM cell_day_aggregates
        WHERE region = :region
          AND h3_index = ANY(:neighbors)
          AND date = :current_date
          AND hotspot_count > 0
    """), {"region": region, "neighbors": neighbors, "current_date": current_date}).fetchone()

    anomalous_result = conn.execute(text("""
        SELECT COUNT(*) as anomalous_count
        FROM cell_day_scores
        WHERE region = :region
          AND h3_index = ANY(:neighbors)
          AND date = :current_date
          AND is_anomaly = true
    """), {"region": region, "neighbors": neighbors, "current_date": current_date}).fetchone()

    active_neighbors = active_result.active_count if active_result else 0
    anomalous_neighbors = anomalous_result.anomalous_count if anomalous_result else 0

    reasons = []
    score = 0

    if active_neighbors >= 4:
        score += 3
        reasons.append(f"{active_neighbors}/6 neighbors active")
    elif active_neighbors >= 2:
        score += 2
        reasons.append(f"{active_neighbors}/6 neighbors active")
    elif active_neighbors == 1:
        score += 1
        reasons.append("1/6 neighbor active")
    else:
        reasons.append("no active neighbors")

    if anomalous_neighbors >= 3:
        score += 3
        reasons.append(f"{anomalous_neighbors} anomalous neighbors")
    elif anomalous_neighbors >= 2:
        score += 2
        reasons.append(f"{anomalous_neighbors} anomalous neighbors")
    elif anomalous_neighbors == 1:
        score += 1
        reasons.append("1 anomalous neighbor")

    if score >= 4:
        level = "high"
    elif score >= 2:
        level = "medium"
    elif score >= 1:
        level = "low"
    else:
        level = "isolated"

    return {
        "level": level,
        "score": score,
        "active_neighbors": active_neighbors,
        "anomalous_neighbors": anomalous_neighbors,
        "reasons": reasons,
        "needs_manual_review": level == "isolated",
    }


def calculate_hybrid_score(anomaly_score: float, coherence_score: int) -> float:
    coherence_normalized = coherence_score / 6.0
    ml_component = abs(anomaly_score) * 0.7
    coherence_component = coherence_normalized * 0.3
    return round(ml_component + coherence_component, 6)


def select_top_k(target_date: date = None, k: int = TOP_K):
    region_id = DATA_REGION
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        if target_date:
            dates = [target_date]
        else:
            result = conn.execute(text("""
                SELECT DISTINCT date FROM cell_day_scores
                WHERE region = :region AND is_anomaly = true
                ORDER BY date
            """), {"region": region_id})
            dates = [row.date for row in result]

    logger.info(
        f"Processing {len(dates)} date(s) for region={region_id}, "
        f"selecting top-{k} anomalies per day..."
    )

    total_alerts = 0

    with engine.begin() as conn:
        if target_date:
            conn.execute(
                text("DELETE FROM daily_alerts WHERE region = :region AND date = :date"),
                {"region": region_id, "date": target_date},
            )
        else:
            conn.execute(
                text("DELETE FROM daily_alerts WHERE region = :region"),
                {"region": region_id},
            )

        for current_date in dates:
            anomalies = conn.execute(text("""
                SELECT s.h3_index, s.date, s.anomaly_score,
                       f.hotspot_count, f.total_frp, f.ratio_vs_7d_avg, f.neighbor_activity
                FROM cell_day_scores s
                JOIN cell_day_features f
                  ON s.region = f.region AND s.h3_index = f.h3_index AND s.date = f.date
                WHERE s.region = :region
                  AND s.date = :current_date
                  AND s.is_anomaly = true
                ORDER BY s.anomaly_score ASC
            """), {"region": region_id, "current_date": current_date}).fetchall()

            if not anomalies:
                continue

            scored_anomalies = []
            for anomaly in anomalies:
                coherence = get_spatial_coherence(
                    anomaly.h3_index, current_date, region_id, conn
                )
                hybrid = calculate_hybrid_score(
                    float(anomaly.anomaly_score), coherence['score']
                )
                scored_anomalies.append({
                    "h3_index": anomaly.h3_index,
                    "date": current_date,
                    "anomaly_score": float(anomaly.anomaly_score),
                    "hybrid_score": hybrid,
                    "coherence_level": coherence['level'],
                    "coherence_reasons": json.dumps(coherence['reasons']),
                    "needs_manual_review": coherence['needs_manual_review'],
                })

            scored_anomalies.sort(key=lambda x: x['hybrid_score'], reverse=True)
            top_k = scored_anomalies[:k]

            for rank, alert in enumerate(top_k, 1):
                conn.execute(text("""
                    INSERT INTO daily_alerts (
                        region, h3_index, date, rank,
                        anomaly_score, hybrid_score,
                        spatial_coherence_level, coherence_reasons,
                        needs_manual_review, alert_sent
                    ) VALUES (
                        :region, :h3_index, :date, :rank,
                        :anomaly_score, :hybrid_score,
                        :coherence_level, :coherence_reasons,
                        :needs_manual_review, false
                    )
                """), {
                    "region": region_id,
                    "h3_index": alert['h3_index'],
                    "date": alert['date'],
                    "rank": rank,
                    "anomaly_score": alert['anomaly_score'],
                    "hybrid_score": alert['hybrid_score'],
                    "coherence_level": alert['coherence_level'],
                    "coherence_reasons": alert['coherence_reasons'],
                    "needs_manual_review": alert['needs_manual_review'],
                })

            total_alerts += len(top_k)

    logger.info(f"Top-K selection complete ({region_id}): {total_alerts:,} alerts")
    return total_alerts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Select top-K anomalies with spatial coherence')
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--k', type=int, default=TOP_K, help=f'Top alerts per day (default: {TOP_K})')
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    total = select_top_k(target_date, args.k)
    print(f"\nCreated {total:,} alerts in daily_alerts!")
