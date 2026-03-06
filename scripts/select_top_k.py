"""
Select Top-K Anomalies with Spatial Coherence Validation
Picks the top-K most anomalous cells per day and validates spatial coherence
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import pandas as pd
import h3
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
TOP_K = int(os.getenv("TOP_K_ALERTS", 20))

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)


def get_spatial_coherence(h3_index: str, current_date: date, conn) -> dict:
    """
    Check how spatially coherent an anomaly is.
    Wildfires spread → anomalies should cluster with active neighbors.

    Returns:
        dict with level, score, reasons
    """
    # Get 6 neighboring cells
    neighbors = list(h3.grid_ring(h3_index, 1))

    # Count active neighbors (any hotspot activity)
    active_result = conn.execute(text("""
        SELECT COUNT(*) as active_count
        FROM cell_day_aggregates
        WHERE h3_index = ANY(:neighbors)
        AND date = :current_date
        AND hotspot_count > 0
    """), {"neighbors": neighbors, "current_date": current_date}).fetchone()

    # Count anomalous neighbors (also flagged as anomaly)
    anomalous_result = conn.execute(text("""
        SELECT COUNT(*) as anomalous_count
        FROM cell_day_scores
        WHERE h3_index = ANY(:neighbors)
        AND date = :current_date
        AND is_anomaly = true
    """), {"neighbors": neighbors, "current_date": current_date}).fetchone()

    active_neighbors = active_result.active_count if active_result else 0
    anomalous_neighbors = anomalous_result.anomalous_count if anomalous_result else 0

    # Determine coherence level
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
        reasons.append(f"1/6 neighbor active")
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
        reasons.append(f"1 anomalous neighbor")

    # Level classification
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
        "needs_manual_review": level == "isolated"
    }


def calculate_hybrid_score(anomaly_score: float, coherence_score: int) -> float:
    """
    Combine ML anomaly score with spatial coherence.
    Lower anomaly_score = more anomalous (negative = bad)
    Higher coherence_score = more spatially coherent (good)

    Hybrid: more negative + more coherent = highest priority
    """
    # Normalize coherence to 0-1 range (max coherence score = 6)
    coherence_normalized = coherence_score / 6.0

    # Hybrid: weight 70% ML score + 30% spatial coherence boost
    # Anomaly score is negative for anomalies, so we flip it
    ml_component = abs(anomaly_score) * 0.7
    coherence_component = coherence_normalized * 0.3

    return round(ml_component + coherence_component, 6)


def select_top_k(target_date: date = None, k: int = TOP_K):
    """
    Select top-K most anomalous cells per day with spatial coherence.

    Args:
        target_date: Specific date (None = all dates)
        k: Number of top alerts per day
    """
    engine = create_engine(DATABASE_URL)

    # Get list of dates to process
    with engine.connect() as conn:
        if target_date:
            dates = [target_date]
        else:
            result = conn.execute(text("""
                SELECT DISTINCT date FROM cell_day_scores
                WHERE is_anomaly = true
                ORDER BY date
            """))
            dates = [row.date for row in result]

    logger.info(f"Processing {len(dates)} date(s), selecting top-{k} anomalies per day...")

    total_alerts = 0

    with engine.begin() as conn:
        # Clear existing alerts for target date(s)
        if target_date:
            conn.execute(text("DELETE FROM daily_alerts WHERE date = :date"), {"date": target_date})
        else:
            conn.execute(text("DELETE FROM daily_alerts"))

        for current_date in dates:
            # Get anomalous cells for this date, ranked by score
            anomalies = conn.execute(text("""
                SELECT s.h3_index, s.date, s.anomaly_score,
                       f.hotspot_count, f.total_frp, f.ratio_vs_7d_avg, f.neighbor_activity
                FROM cell_day_scores s
                JOIN cell_day_features f ON s.h3_index = f.h3_index AND s.date = f.date
                WHERE s.date = :current_date
                AND s.is_anomaly = true
                ORDER BY s.anomaly_score ASC
            """), {"current_date": current_date}).fetchall()

            if not anomalies:
                continue

            # Score each anomaly with spatial coherence
            scored_anomalies = []
            for anomaly in anomalies:
                coherence = get_spatial_coherence(anomaly.h3_index, current_date, conn)
                hybrid = calculate_hybrid_score(float(anomaly.anomaly_score), coherence['score'])

                scored_anomalies.append({
                    "h3_index": anomaly.h3_index,
                    "date": current_date,
                    "anomaly_score": float(anomaly.anomaly_score),
                    "hybrid_score": hybrid,
                    "coherence_level": coherence['level'],
                    "coherence_score": coherence['score'],
                    "coherence_reasons": json.dumps(coherence['reasons']),
                    "needs_manual_review": coherence['needs_manual_review'],
                })

            # Sort by hybrid score (higher = higher priority)
            scored_anomalies.sort(key=lambda x: x['hybrid_score'], reverse=True)

            # Take top-K
            top_k = scored_anomalies[:k]

            # Insert into daily_alerts
            for rank, alert in enumerate(top_k, 1):
                conn.execute(text("""
                    INSERT INTO daily_alerts (
                        h3_index, date, rank,
                        anomaly_score, hybrid_score,
                        spatial_coherence_level, coherence_reasons,
                        needs_manual_review, alert_sent
                    ) VALUES (
                        :h3_index, :date, :rank,
                        :anomaly_score, :hybrid_score,
                        :coherence_level, :coherence_reasons,
                        :needs_manual_review, false
                    )
                """), {
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

        # Summary stats
        if not target_date:
            stats = conn.execute(text("""
                SELECT
                    COUNT(*) as total_alerts,
                    COUNT(DISTINCT date) as days_with_alerts,
                    SUM(CASE WHEN spatial_coherence_level = 'high' THEN 1 ELSE 0 END) as high_coherence,
                    SUM(CASE WHEN spatial_coherence_level = 'medium' THEN 1 ELSE 0 END) as med_coherence,
                    SUM(CASE WHEN spatial_coherence_level = 'low' THEN 1 ELSE 0 END) as low_coherence,
                    SUM(CASE WHEN spatial_coherence_level = 'isolated' THEN 1 ELSE 0 END) as isolated,
                    SUM(CASE WHEN needs_manual_review THEN 1 ELSE 0 END) as needs_review
                FROM daily_alerts
            """)).fetchone()

            logger.info(f"\n✅ Top-K selection complete!")
            logger.info(f"  Total alerts: {stats.total_alerts:,}")
            logger.info(f"  Days with alerts: {stats.days_with_alerts}")
            logger.info(f"  Spatial coherence breakdown:")
            logger.info(f"    🔴 High:     {stats.high_coherence:,} (fire cluster - high priority)")
            logger.info(f"    🟠 Medium:   {stats.med_coherence:,} (spreading fire)")
            logger.info(f"    🟡 Low:      {stats.low_coherence:,} (possibly spreading)")
            logger.info(f"    ⚪ Isolated: {stats.isolated:,} (needs manual review)")
            logger.info(f"  Needs manual review: {stats.needs_review:,}")

            # Show top 5 alerts overall
            top5 = conn.execute(text("""
                SELECT h3_index, date, rank, hybrid_score,
                       spatial_coherence_level, needs_manual_review
                FROM daily_alerts
                ORDER BY hybrid_score DESC
                LIMIT 5
            """)).fetchall()

            logger.info(f"\n🔥 Top 5 Highest Priority Alerts (All Time):")
            for i, alert in enumerate(top5, 1):
                review_flag = " ⚠️ REVIEW" if alert.needs_manual_review else ""
                logger.info(
                    f"  {i}. [{alert.date}] Cell {alert.h3_index[:12]}... "
                    f"hybrid={alert.hybrid_score:.4f} | "
                    f"coherence={alert.spatial_coherence_level}{review_flag}"
                )

    return total_alerts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Select top-K anomalies with spatial coherence')
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD). Default: all dates')
    parser.add_argument('--k', type=int, default=TOP_K, help=f'Number of top alerts per day (default: {TOP_K})')
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    logger.info("=" * 60)
    logger.info(f"🚨 Top-K Alert Selection (k={args.k})")
    logger.info("=" * 60)

    total = select_top_k(target_date, args.k)

    print("\n" + "=" * 60)
    print(f"✅ Created {total:,} alerts in daily_alerts table!")
    print("\nNext step:")
    print("  Build FastAPI: src/wildfire_detection/api/main.py")
    print("=" * 60)
