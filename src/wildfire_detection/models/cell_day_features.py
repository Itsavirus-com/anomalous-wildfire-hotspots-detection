# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Cell-day features for ML
"""

from sqlalchemy import Column, Integer, String, DECIMAL, Date, UniqueConstraint, Index
from .base import Base


class CellDayFeatures(Base):
    """Engineered features for ML input"""
    __tablename__ = 'cell_day_features'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String(32), nullable=False, index=True, default='indonesia')
    h3_index = Column(String(15), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Base features (from aggregates)
    hotspot_count = Column(Integer, nullable=False)
    total_frp = Column(DECIMAL(10, 2))
    max_frp = Column(DECIMAL(8, 2))
    
    # Temporal features
    delta_count_vs_prev_day = Column(Integer)
    ratio_vs_7d_avg = Column(DECIMAL(6, 2))
    
    # Spatial features
    neighbor_activity = Column(Integer)  # Count of active neighbors
    
    __table_args__ = (
        UniqueConstraint('region', 'h3_index', 'date', name='uq_cell_day_features_region'),
        Index('ix_cell_day_feat_region_date', 'region', 'date'),
    )
    
    def __repr__(self):
        return f"<CellDayFeatures(region={self.region}, h3={self.h3_index}, date={self.date})>"
