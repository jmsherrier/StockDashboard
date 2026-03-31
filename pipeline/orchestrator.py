"""
Pipeline Orchestrator.

Runs the three-tier screening pipeline:
  1. Load universe from DB
  2. Tier 1: Fundamental filters (cached data, cheap)
  3. Tier 2: Technical filters (EOD data, moderate)
  4. Tier 3: Intraday filters (live data, expensive)
  5. Score, rank, store results

This is the main entry point for both scheduled runs and manual triggers.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from config.settings import settings
from core.schemas import FilterResult
from filters.base import CompositeFilter, FilterConfig
from filters.fundamental import build_fundamental_filters
from filters.technical import build_technical_filters
from filters.intraday import build_intraday_filters
from storage.repositories import (
    FundamentalRepository,
    ScreenerRepository,
    StockRepository,
)

logger = logging.getLogger(__name__)


# ── Default filter configs ───────────────────────────────────────
# These can be overridden via API or config file.

DEFAULT_FUNDAMENTAL_FILTERS = [
    FilterConfig(name="market_cap", params={"min_cap": 100_000_000}, weight=1.0, required=True),
    FilterConfig(name="volume", params={"min_volume": 200_000}, weight=0.8, required=True),
    FilterConfig(name="price", params={"min_price": 5.0}, weight=0.5, required=True),
    FilterConfig(name="valuation", params={"max_pe": 60, "min_roe": 0.03}, weight=1.5, required=False),
    FilterConfig(name="growth", params={"min_revenue_growth": 0.0, "min_eps_growth": 0.0}, weight=1.0, required=False),
]

DEFAULT_TECHNICAL_FILTERS = [
    FilterConfig(name="trend", params={"max_pct_below_52w_high": 0.30}, weight=2.0, required=False),
    FilterConfig(name="momentum", params={"rsi_min": 35, "rsi_max": 80}, weight=1.5, required=False),
    FilterConfig(name="relative_strength", params={"min_percentile": 50}, weight=1.5, required=False),
]

DEFAULT_INTRADAY_FILTERS = [
    FilterConfig(name="spread", params={"max_spread_pct": 1.0}, weight=1.0, required=False),
    FilterConfig(name="intraday_momentum", params={"min_change_pct": -5}, weight=1.0, required=False),
]


class PipelineResult:
    """Container for a complete pipeline run result."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.timestamp = datetime.utcnow()
        self.universe_size: int = 0
        self.tier1_passed: int = 0
        self.tier2_passed: int = 0
        self.tier3_passed: int = 0
        self.results: list[dict] = []

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "universe_size": self.universe_size,
            "tier1_passed": self.tier1_passed,
            "tier2_passed": self.tier2_passed,
            "tier3_passed": self.tier3_passed,
            "final_count": len(self.results),
        }


async def run_pipeline(
    fundamental_configs: Optional[list[FilterConfig]] = None,
    technical_configs: Optional[list[FilterConfig]] = None,
    intraday_configs: Optional[list[FilterConfig]] = None,
    skip_intraday: bool = False,
) -> PipelineResult:
    """
    Execute the full screening pipeline.

    Args:
        fundamental_configs: Override default fundamental filters
        technical_configs: Override default technical filters
        intraday_configs: Override default intraday filters
        skip_intraday: If True, skip Tier 3 (useful for after-hours runs)

    Returns:
        PipelineResult with ranked stocks
    """
    run_id = str(uuid.uuid4())
    result = PipelineResult(run_id)
    logger.info("Pipeline run %s starting", run_id)

    stock_repo = StockRepository()
    screener_repo = ScreenerRepository()

    # ── Step 1: Load universe ────────────────────────────────────
    all_symbols = await stock_repo.get_active_symbols(
        min_market_cap=settings.min_market_cap,
    )
    result.universe_size = len(all_symbols)
    logger.info("Universe: %d symbols", result.universe_size)

    if not all_symbols:
        logger.warning("Empty universe. Run seed_universe.py first.")
        return result

    # ── Step 2: Tier 1 — Fundamental Filters ─────────────────────
    fund_configs = fundamental_configs or DEFAULT_FUNDAMENTAL_FILTERS
    fund_filters = build_fundamental_filters(fund_configs)
    tier1 = CompositeFilter(fund_filters)
    tier1_results = await tier1.apply(all_symbols)

    tier1_passed = [r for r in tier1_results if r.passed]
    tier1_scores = {r.symbol: r.score for r in tier1_results}
    result.tier1_passed = len(tier1_passed)
    logger.info(
        "Tier 1 (Fundamental): %d/%d passed",
        result.tier1_passed, result.universe_size,
    )

    if not tier1_passed:
        logger.warning("No stocks passed fundamental filters")
        return result

    # Cap the number passed to Tier 2
    tier1_symbols = sorted(
        [r.symbol for r in tier1_passed],
        key=lambda s: tier1_scores.get(s, 0),
        reverse=True,
    )[:settings.max_stocks_tier2]

    # ── Step 3: Tier 2 — Technical Filters ───────────────────────
    tech_configs = technical_configs or DEFAULT_TECHNICAL_FILTERS
    tech_filters = build_technical_filters(tech_configs)
    tier2 = CompositeFilter(tech_filters)
    tier2_results = await tier2.apply(tier1_symbols)

    tier2_passed = [r for r in tier2_results if r.passed]
    tier2_scores = {r.symbol: r.score for r in tier2_results}
    result.tier2_passed = len(tier2_passed)
    logger.info(
        "Tier 2 (Technical): %d/%d passed",
        result.tier2_passed, len(tier1_symbols),
    )

    # Cap for Tier 3
    tier2_symbols = sorted(
        [r.symbol for r in tier2_passed],
        key=lambda s: tier2_scores.get(s, 0),
        reverse=True,
    )[:settings.max_stocks_tier3]

    # ── Step 4: Tier 3 — Intraday Filters (optional) ────────────
    tier3_scores: dict[str, float] = {}
    if not skip_intraday and tier2_symbols:
        intra_configs = intraday_configs or DEFAULT_INTRADAY_FILTERS
        intra_filters = build_intraday_filters(intra_configs)
        tier3 = CompositeFilter(intra_filters)
        tier3_results = await tier3.apply(tier2_symbols)

        tier3_passed = [r for r in tier3_results if r.passed]
        tier3_scores = {r.symbol: r.score for r in tier3_results}
        result.tier3_passed = len(tier3_passed)
        final_symbols = [r.symbol for r in tier3_passed]
        logger.info(
            "Tier 3 (Intraday): %d/%d passed",
            result.tier3_passed, len(tier2_symbols),
        )
    else:
        final_symbols = tier2_symbols
        result.tier3_passed = len(final_symbols)

    # ── Step 5: Composite scoring and storage ────────────────────
    stock_details = await stock_repo.get_stock_details(final_symbols)

    for symbol in final_symbols:
        fund_score = tier1_scores.get(symbol, 0)
        tech_score = tier2_scores.get(symbol, 0)
        intra_score = tier3_scores.get(symbol, 50)

        # Weighted composite: technical > fundamental > intraday
        composite = (
            fund_score * 0.25 +
            tech_score * 0.50 +
            intra_score * 0.25
        )

        details = stock_details.get(symbol, {})
        row = {
            "run_id": run_id,
            "run_timestamp": result.timestamp,
            "symbol": symbol,
            "passed_fundamental": True,
            "passed_technical": True,
            "passed_intraday": symbol in tier3_scores,
            "fundamental_score": round(fund_score, 2),
            "technical_score": round(tech_score, 2),
            "intraday_score": round(intra_score, 2),
            "composite_score": round(composite, 2),
            "market_cap_at_scan": details.get("market_cap"),
        }
        result.results.append(row)

    # Sort by composite score
    result.results.sort(key=lambda r: r.get("composite_score", 0), reverse=True)

    # Store in database
    if result.results:
        count = await screener_repo.store_results(result.results)
        logger.info("Stored %d screener results for run %s", count, run_id)

    logger.info("Pipeline run %s complete: %s", run_id, json.dumps(result.summary()))
    return result


# ── CLI entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def main():
        from storage.database import init_db
        await init_db()
        result = await run_pipeline(skip_intraday=True)
        print("\n=== Pipeline Result ===")
        print(json.dumps(result.summary(), indent=2))
        if result.results:
            print(f"\nTop 10 stocks:")
            for r in result.results[:10]:
                print(f"  {r['symbol']:8s}  composite={r['composite_score']:.1f}  "
                      f"fund={r['fundamental_score']:.1f}  tech={r['technical_score']:.1f}")

    asyncio.run(main())
