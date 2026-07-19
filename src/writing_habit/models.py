"""Small data carriers shared across the modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PlanBlock:
    day: str            # ISO date
    start_time: str     # HH:MM
    end_time: str       # HH:MM
    project_code: str
    category: str       # generative | editing | support


@dataclass
class Session:
    day: str            # ISO date
    actual_min: int
    project_code: str
    category: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    source: str = "csv"
    source_ref: Optional[str] = None
    note: Optional[str] = None
