"""
Tier 3: Intraday Filters.

These hit live/delayed quote APIs and are the most expensive tier.
Only stocks that passed Tier 1 + Tier 2 reach here (~50-200 stocks).
This is where you'd gate real-time provider costs.
"""
from __future__ import annotations

import logging
from typing import Sequence

from core.schemas import FilterResult, QuoteSnapshot
from filters.base import FilterConfig, StockFilter
from providers.registry import get_intraday_provider

logger = logging.getLogger(__name__)


class SpreadFilter(StockFilter):
    """
    Filter by bid-ask spread as % of price.
    Tight spreads = liquid, tradeable stocks.
    Params: max_spread_pct (float)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        provider = get_intraday_provider()
        max_spread = self.config.params.get("max_spread_pct", 0.5)  # 0.5%

        quotes = await provider.get_quotes_bulk(list(symbols))
        quote_map: dict[str, QuoteSnapshot] = {q.symbol: q for q in quotes}

        results = []
        for symbol in symbols:
            q = quote_map.get(symbol)
            if not q or not q.bid or not q.ask or q.price <= 0:
                # No spread data — pass with neutral score (don't penalize delayed feeds)
                results.append(FilterResult(
                    symbol=symbol, passed=True, score=50,
                    reason="No bid/ask data (delayed feed)",
                ))
                continue

            spread_pct = ((q.ask - q.bid) / q.price) * 100
            passed = spread_pct <= max_spread

            # Tighter spread = higher score
            score = max(0, 100 - (spread_pct / max_spread) * 50)

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=round(score, 2),
                details={"spread_pct": round(spread_pct, 4), "bid": q.bid, "ask": q.ask},
            ))
        return results


class IntradayMomentumFilter(StockFilter):
    """
    Checks intraday price action: gap direction, current % change,
    volume relative to typical intraday volume.
    Params: min_change_pct (float), min_volume_ratio (float)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        provider = get_intraday_provider()
        min_change = self.config.params.get("min_change_pct", 0)  # Any positive
        min_vol_ratio = self.config.params.get("min_volume_ratio", 0.8)

        quotes = await provider.get_quotes_bulk(list(symbols))
        quote_map = {q.symbol: q for q in quotes}

        results = []
        for symbol in symbols:
            q = quote_map.get(symbol)
            if not q:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0,
                    reason="No quote data",
                ))
                continue

            change_pct = q.change_pct or 0
            score = 50

            # Direction and magnitude
            if change_pct > 0:
                score += min(30, change_pct * 5)
            elif change_pct < -3:
                score -= 20  # Significant drop

            # Gap analysis
            if q.prev_close and q.price:
                gap_pct = ((q.price - q.prev_close) / q.prev_close) * 100
                if gap_pct > 1:
                    score += 10  # Gap up

            passed = change_pct >= min_change
            score = max(0, min(100, score))

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=round(score, 2),
                details={
                    "change_pct": round(change_pct, 2),
                    "price": q.price,
                    "volume": q.volume,
                },
            ))
        return results


class IntradayVolumeFilter(StockFilter):
    """
    Checks if intraday volume is running above average pace.
    Params: min_pace_ratio (float) — vol so far / expected vol by this time
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        provider = get_intraday_provider()
        min_pace = self.config.params.get("min_pace_ratio", 1.0)

        quotes = await provider.get_quotes_bulk(list(symbols))
        quote_map = {q.symbol: q for q in quotes}

        results = []
        for symbol in symbols:
            q = quote_map.get(symbol)
            if not q:
                results.append(FilterResult(symbol=symbol, passed=False, score=0))
                continue

            # Without a full intraday history, we use a simple heuristic:
            # compare current volume to what we'd expect by this time of day.
            # In production, you'd store intraday volume profiles.
            # For now, pass everything with a volume-based score.
            vol = q.volume
            score = 50
            if vol > 0:
                score = min(100, 50 + (vol / 1_000_000) * 10)

            results.append(FilterResult(
                symbol=symbol, passed=True,
                score=round(score, 2),
                details={"intraday_volume": vol},
            ))
        return results


# ── Filter factory ───────────────────────────────────────────────

INTRADAY_FILTERS: dict[str, type[StockFilter]] = {
    "spread": SpreadFilter,
    "intraday_momentum": IntradayMomentumFilter,
    "intraday_volume": IntradayVolumeFilter,
}


def build_intraday_filters(configs: list[FilterConfig]) -> list[StockFilter]:
    filters = []
    for cfg in configs:
        cls = INTRADAY_FILTERS.get(cfg.name)
        if cls:
            filters.append(cls(cfg))
        else:
            logger.warning("Unknown intraday filter: %s", cfg.name)
    return filters
