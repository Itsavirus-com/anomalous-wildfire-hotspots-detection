# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Cell-day anomaly scores
"""

from sqlalchemy import Column, Integer, String, DECIMAL, Date, Boolean, DateTime, UniqueConstraint, Index
from datetime import datetime
from .base import Base


class CellDayScores(Base):
    """Anomaly scores from ML model"""
    __tablename__ = 'cell_day_scores'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String(32), nullable=False, index=True, default='indonesia')
    h3_index = Column(String(15), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # ML scores
    anomaly_score = Column(DECIMAL(10, 6), nullable=False)  # Isolation Forest score
    is_anomaly = Column(Boolean, default=False)
    model_version = Column(String(20), nullable=False)
    scored_at = Column(DateTime, default=datetime.now)

    # Spatial coherence
    spatial_coherence_score = Column(Integer)
    spatial_coherence_level = Column(String(20))  # high, medium, low, isolated

    __table_args__ = (
        UniqueConstraint('region', 'h3_index', 'date', name='uq_cell_day_score_region'),
        Index('ix_cell_day_scores_region_date', 'region', 'date'),
    )
    
    def __repr__(self):
        return f"<CellDayScores(region={self.region}, h3={self.h3_index}, date={self.date}, score={self.anomaly_score})>"
