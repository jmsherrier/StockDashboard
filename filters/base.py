"""
Abstract filter interface.

Each filter tier implements this. Filters are composable — you can
chain multiple filters within a tier, and the pipeline runs tiers
in sequence (cheap → expensive).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

from core.schemas import FilterResult


@dataclass
class FilterConfig:
    """
    Dynamic filter configuration. This gets passed from the API or
    config files, allowing users to customize screening criteria
    without changing code.
    """
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0  # Weight in composite score
    required: bool = True  # Must pass to continue to next tier


class StockFilter(ABC):
    """Base class for all filters."""

    def __init__(self, config: FilterConfig):
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @abstractmethod
    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        """
        Apply this filter to a list of symbols.
        Returns a FilterResult for each symbol (passed or not).
        """
        ...


class CompositeFilter:
    """
    Combines multiple filters within a tier.
    A stock passes if all required filters pass.
    Score is the weighted average of individual scores.
    """

    def __init__(self, filters: list[StockFilter]):
        self.filters = filters

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        if not self.filters:
            # No filters = everything passes
            return [
                FilterResult(symbol=s, passed=True, score=50.0) for s in symbols
            ]

        # Run all filters
        all_results: dict[str, list[FilterResult]] = {s: [] for s in symbols}
        for filt in self.filters:
            results = await filt.apply(symbols)
            for r in results:
                if r.symbol in all_results:
                    all_results[r.symbol].append(r)

        # Combine results
        combined = []
        for symbol in symbols:
            results = all_results.get(symbol, [])
            if not results:
                combined.append(FilterResult(symbol=symbol, passed=False, score=0))
                continue

            # Check required filters
            required_passed = all(
                r.passed for r, f in zip(results, self.filters) if f.config.required
            )

            # Weighted score
            total_weight = sum(f.config.weight for f in self.filters)
            if total_weight > 0:
                weighted_score = sum(
                    r.score * f.config.weight
                    for r, f in zip(results, self.filters)
                ) / total_weight
            else:
                weighted_score = 0

            # Merge detail dicts
            merged_details = {}
            for r in results:
                merged_details.update(r.details)

            combined.append(FilterResult(
                symbol=symbol,
                passed=required_passed,
                score=round(weighted_score, 2),
                details=merged_details,
            ))

        return combined
