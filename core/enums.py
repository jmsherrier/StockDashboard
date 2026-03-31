"""Common enumerations used across the system."""
from enum import Enum


class Exchange(str, Enum):
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    AMEX = "AMEX"


class Sector(str, Enum):
    TECHNOLOGY = "Technology"
    HEALTHCARE = "Healthcare"
    FINANCIALS = "Financials"
    CONSUMER_CYCLICAL = "Consumer Cyclical"
    CONSUMER_DEFENSIVE = "Consumer Defensive"
    INDUSTRIALS = "Industrials"
    ENERGY = "Energy"
    UTILITIES = "Utilities"
    REAL_ESTATE = "Real Estate"
    BASIC_MATERIALS = "Basic Materials"
    COMMUNICATION = "Communication Services"
    UNKNOWN = "Unknown"


class Interval(str, Enum):
    MIN_1 = "1min"
    MIN_5 = "5min"
    MIN_15 = "15min"
    MIN_30 = "30min"
    HOUR_1 = "1hour"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class FilterTier(str, Enum):
    FUNDAMENTAL = "fundamental"   # Tier 1: static/cached
    TECHNICAL = "technical"       # Tier 2: EOD-based
    INTRADAY = "intraday"         # Tier 3: live data
