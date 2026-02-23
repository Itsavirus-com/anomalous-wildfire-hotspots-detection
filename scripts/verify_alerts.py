from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    s = conn.execute(text("""
        SELECT COUNT(*) as total,
               COUNT(DISTINCT date) as days,
               SUM(CASE WHEN spatial_coherence_level='high' THEN 1 ELSE 0 END) as high,
               SUM(CASE WHEN spatial_coherence_level='medium' THEN 1 ELSE 0 END) as med,
               SUM(CASE WHEN spatial_coherence_level='isolated' THEN 1 ELSE 0 END) as isolated,
               SUM(CASE WHEN needs_manual_review THEN 1 ELSE 0 END) as review
        FROM daily_alerts
    """)).fetchone()
    print(f'Total alerts:     {s.total}')
    print(f'Days covered:     {s.days}')
    print(f'High coherence:   {s.high}')
    print(f'Medium coherence: {s.med}')
    print(f'Isolated (review):{s.isolated}')
    print(f'Needs review:     {s.review}')

    top5 = conn.execute(text("""
        SELECT h3_index, date, rank, hybrid_score, spatial_coherence_level
        FROM daily_alerts ORDER BY hybrid_score DESC LIMIT 5
    """)).fetchall()
    print()
    print('Top 5 highest priority alerts:')
    for i, a in enumerate(top5, 1):
        print(f'  {i}. [{a.date}] {a.h3_index[:12]}... hybrid={a.hybrid_score} | {a.spatial_coherence_level}')
