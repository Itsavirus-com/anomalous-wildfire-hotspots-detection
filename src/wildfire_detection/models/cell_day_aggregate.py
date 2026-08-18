# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Cell-day aggregates
"""

from sqlalchemy import Column, Integer, String, DECIMAL, Date, UniqueConstraint, Index
from .base import Base


class CellDayAggregate(Base):
    """Daily aggregates per H3 cell"""
    __tablename__ = 'cell_day_aggregates'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String(32), nullable=False, index=True, default='indonesia')
    h3_index = Column(String(15), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Aggregated metrics
    hotspot_count = Column(Integer, nullable=False)
    total_frp = Column(DECIMAL(10, 2))
    max_frp = Column(DECIMAL(8, 2))
    avg_frp = Column(DECIMAL(8, 2))
    min_frp = Column(DECIMAL(8, 2))
    
    # Confidence distribution
    high_confidence_count = Column(Integer, default=0)
    nominal_confidence_count = Column(Integer, default=0)
    low_confidence_count = Column(Integer, default=0)
    
    __table_args__ = (
        UniqueConstraint('region', 'h3_index', 'date', name='uq_cell_day_region'),
        Index('ix_cell_day_agg_region_date', 'region', 'date'),
    )
    
    def __repr__(self):
        return f"<CellDayAggregate(region={self.region}, h3={self.h3_index}, date={self.date}, count={self.hotspot_count})>"
