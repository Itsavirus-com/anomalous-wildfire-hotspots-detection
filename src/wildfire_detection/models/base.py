# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Database models base configuration
"""

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DECIMAL, DateTime, Date, Text
from geoalchemy2 import Geometry
from datetime import datetime

Base = declarative_base()

__all__ = ['Base']
