# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Daily alerts (Top-K anomalies)
"""

from sqlalchemy import Column, Integer, String, DECIMAL, Date, Text, Boolean
from .base import Base

class DailyAlerts(Base):
    """Top-K ranked anomalies for daily alerts"""
    __tablename__ = 'daily_alerts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    h3_index = Column(String(15), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    rank = Column(Integer, nullable=False)  # 1 = most anomalous
    
    # Scores
    anomaly_score = Column(DECIMAL(10, 6))
    hybrid_score = Column(DECIMAL(10, 6))  # ML + spatial coherence
    
    # Spatial coherence
    spatial_coherence_level = Column(String(20))
    coherence_reasons = Column(Text)  # JSON array of reasons
    needs_manual_review = Column(Boolean, default=False)
    
    # Alert status
    alert_sent = Column(Boolean, default=False)
    alert_sent_at = Column(Date)
    
    def __repr__(self):
        return f"<DailyAlerts(h3={self.h3_index}, date={self.date}, rank={self.rank})>"
