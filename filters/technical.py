"""
Tier 2: Technical Filters.

These run against daily OHLCV data using pandas-ta for indicator
computation. Data is fetched once per day and cached, so the per-stock
cost here is the TA computation, not API calls.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from core.schemas import FilterResult
from filters.base import FilterConfig, StockFilter
from storage.repositories import PriceRepository

logger = logging.getLogger(__name__)

# pandas_ta is optional; fall back to manual calculation if missing
try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False
    logger.warning("pandas_ta not installed. Using manual TA calculations.")


def _compute_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def _compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


class TrendFilter(StockFilter):
    """
    Trend template filter (inspired by Minervini's trend template).
    Checks: price > SMA50 > SMA150 > SMA200, SMA200 rising, within range of 52w high.
    Params: sma_periods (list), max_pct_below_52w_high (float)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = PriceRepository()
        max_below_high = self.config.params.get("max_pct_below_52w_high", 0.25)
        min_above_low = self.config.params.get("min_pct_above_52w_low", 0.30)

        results = []
        for symbol in symbols:
            df = await repo.get_daily_df(symbol, lookback_days=260)  # ~1 year
            if df is None or len(df) < 200:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0,
                    reason="Insufficient price history"
                ))
                continue

            close = df["close"]
            current = close.iloc[-1]

            sma50 = _compute_sma(close, 50).iloc[-1]
            sma150 = _compute_sma(close, 150).iloc[-1]
            sma200 = _compute_sma(close, 200).iloc[-1]
            sma200_prev = _compute_sma(close, 200).iloc[-20]  # 1 month ago

            high_52w = close.rolling(252).max().iloc[-1]
            low_52w = close.rolling(252).min().iloc[-1]

            # Trend template checks
            checks = {
                "price_above_sma50": current > sma50,
                "sma50_above_sma150": sma50 > sma150,
                "sma150_above_sma200": sma150 > sma200,
                "sma200_rising": sma200 > sma200_prev,
                "near_52w_high": (high_52w - current) / high_52w <= max_below_high,
                "above_52w_low": (current - low_52w) / max(low_52w, 0.01) >= min_above_low,
            }

            passed_count = sum(checks.values())
            score = (passed_count / len(checks)) * 100
            passed = passed_count >= 5  # Allow 1 miss out of 6

            results.append(FilterResult(
                symbol=symbol,
                passed=passed,
                score=round(score, 2),
                details={
                    **{k: v for k, v in checks.items()},
                    "price": current, "sma50": sma50, "sma200": sma200,
                    "high_52w": high_52w,
                },
            ))
        return results


class MomentumFilter(StockFilter):
    """
    RSI and MACD-based momentum filter.
    Params: rsi_min (float), rsi_max (float)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = PriceRepository()
        rsi_min = self.config.params.get("rsi_min", 40)
        rsi_max = self.config.params.get("rsi_max", 80)

        results = []
        for symbol in symbols:
            df = await repo.get_daily_df(symbol, lookback_days=100)
            if df is None or len(df) < 30:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0,
                    reason="Insufficient data"
                ))
                continue

            close = df["close"]

            # RSI
            rsi = _compute_rsi(close, 14).iloc[-1]

            # MACD
            ema12 = _compute_ema(close, 12)
            ema26 = _compute_ema(close, 26)
            macd_line = ema12 - ema26
            signal_line = _compute_ema(macd_line, 9)
            macd_hist = macd_line - signal_line
            macd_bullish = macd_hist.iloc[-1] > 0

            # Relative Strength vs SPY would go here in production
            # For now, use price vs SMA as a proxy
            sma20 = _compute_sma(close, 20).iloc[-1]
            above_sma20 = close.iloc[-1] > sma20

            # Scoring
            score = 50
            if rsi_min <= rsi <= rsi_max:
                score += 15
            if macd_bullish:
                score += 20
            if above_sma20:
                score += 15

            passed = (rsi_min <= rsi <= rsi_max) and (macd_bullish or above_sma20)

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=round(min(100, score), 2),
                details={"rsi": round(rsi, 2), "macd_bullish": macd_bullish},
            ))
        return results


class VolumeBreakoutFilter(StockFilter):
    """
    Detects unusual volume patterns.
    Params: volume_ratio_min (float) — ratio of recent vol to avg vol
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = PriceRepository()
        min_ratio = self.config.params.get("volume_ratio_min", 1.5)

        results = []
        for symbol in symbols:
            df = await repo.get_daily_df(symbol, lookback_days=30)
            if df is None or len(df) < 20:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0
                ))
                continue

            vol = df["volume"]
            avg_vol = vol.iloc[:-1].mean()
            recent_vol = vol.iloc[-1]

            if avg_vol == 0:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0
                ))
                continue

            ratio = recent_vol / avg_vol
            passed = ratio >= min_ratio

            score = min(100, 50 + (ratio - 1) * 25)

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=round(max(0, score), 2),
                details={"volume_ratio": round(ratio, 2), "avg_volume": avg_vol},
            ))
        return results


class RelativeStrengthFilter(StockFilter):
    """
    Relative strength ranking within the screened universe.
    Params: min_percentile (float, 0-100)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = PriceRepository()
        min_percentile = self.config.params.get("min_percentile", 70)
        lookback = self.config.params.get("lookback_days", 63)  # ~3 months

        # Calculate returns for all symbols
        returns: dict[str, float] = {}
        for symbol in symbols:
            df = await repo.get_daily_df(symbol, lookback_days=lookback + 10)
            if df is not None and len(df) >= lookback:
                close = df["close"]
                ret = (close.iloc[-1] / close.iloc[-lookback]) - 1
                returns[symbol] = ret

        if not returns:
            return [FilterResult(symbol=s, passed=False, score=0) for s in symbols]

        # Rank
        sorted_symbols = sorted(returns.keys(), key=lambda s: returns[s])
        n = len(sorted_symbols)
        percentiles = {s: (i / n) * 100 for i, s in enumerate(sorted_symbols)}

        results = []
        for symbol in symbols:
            pct = percentiles.get(symbol)
            if pct is None:
                results.append(FilterResult(symbol=symbol, passed=False, score=0))
                continue

            results.append(FilterResult(
                symbol=symbol,
                passed=pct >= min_percentile,
                score=round(pct, 2),
                details={"rs_percentile": round(pct, 2), "return": round(returns.get(symbol, 0), 4)},
            ))
        return results


# ── Filter factory ───────────────────────────────────────────────

TECHNICAL_FILTERS: dict[str, type[StockFilter]] = {
    "trend": TrendFilter,
    "momentum": MomentumFilter,
    "volume_breakout": VolumeBreakoutFilter,
    "relative_strength": RelativeStrengthFilter,
}


def build_technical_filters(configs: list[FilterConfig]) -> list[StockFilter]:
    filters = []
    for cfg in configs:
        cls = TECHNICAL_FILTERS.get(cfg.name)
        if cls:
            filters.append(cls(cfg))
        else:
            logger.warning("Unknown technical filter: %s", cfg.name)
    return filters
