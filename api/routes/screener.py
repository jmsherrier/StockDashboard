"""
Screener API endpoints.

- POST /run: trigger a screening run
- GET /results/{run_id}: get results for a run
- GET /latest: get latest run results
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from core.schemas import ScreenerResultResponse, ScreenerRunResponse
from pipeline.orchestrator import run_pipeline
from storage.repositories import ScreenerRepository, StockRepository

router = APIRouter()


@router.post("/run", response_model=dict)
async def trigger_run(skip_intraday: bool = True):
    """Trigger a new screening run. Returns the run summary."""
    result = await run_pipeline(skip_intraday=skip_intraday)
    return result.summary()


@router.get("/latest", response_model=ScreenerRunResponse)
async def get_latest_results(
    min_score: float = Query(0, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
):
    """Get results from the most recent screening run."""
    repo = ScreenerRepository()
    stock_repo = StockRepository()

    run_id = await repo.get_latest_run()
    if not run_id:
        raise HTTPException(status_code=404, detail="No screening runs found")

    results = await repo.get_run_results(run_id, min_score=min_score, limit=limit)
    if not results:
        raise HTTPException(status_code=404, detail="No results for this run")

    # Enrich with stock details
    symbols = [r["symbol"] for r in results]
    details = await stock_repo.get_stock_details(symbols)

    response_results = []
    for r in results:
        d = details.get(r["symbol"], {})
        tiers = []
        if r.get("passed_fundamental"):
            tiers.append("fundamental")
        if r.get("passed_technical"):
            tiers.append("technical")
        if r.get("passed_intraday"):
            tiers.append("intraday")

        response_results.append(ScreenerResultResponse(
            symbol=r["symbol"],
            name=d.get("name"),
            exchange=d.get("exchange"),
            sector=d.get("sector"),
            composite_score=r.get("composite_score"),
            fundamental_score=r.get("fundamental_score"),
            technical_score=r.get("technical_score"),
            intraday_score=r.get("intraday_score"),
            price=r.get("price_at_scan"),
            volume=r.get("volume_at_scan"),
            market_cap=r.get("market_cap_at_scan"),
            passed_tiers=tiers,
        ))

    return ScreenerRunResponse(
        run_id=run_id,
        timestamp=results[0]["run_timestamp"],
        total_universe=0,  # Would need to store this in run metadata
        passed_fundamental=sum(1 for r in results if r.get("passed_fundamental")),
        passed_technical=sum(1 for r in results if r.get("passed_technical")),
        passed_intraday=sum(1 for r in results if r.get("passed_intraday")),
        results=response_results,
    )


@router.get("/results/{run_id}", response_model=list[ScreenerResultResponse])
async def get_run_results(
    run_id: str,
    min_score: float = Query(0, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
):
    """Get results for a specific screening run."""
    repo = ScreenerRepository()
    results = await repo.get_run_results(run_id, min_score=min_score, limit=limit)
    if not results:
        raise HTTPException(status_code=404, detail="Run not found")

    stock_repo = StockRepository()
    symbols = [r["symbol"] for r in results]
    details = await stock_repo.get_stock_details(symbols)

    return [
        ScreenerResultResponse(
            symbol=r["symbol"],
            name=details.get(r["symbol"], {}).get("name"),
            exchange=details.get(r["symbol"], {}).get("exchange"),
            sector=details.get(r["symbol"], {}).get("sector"),
            composite_score=r.get("composite_score"),
            fundamental_score=r.get("fundamental_score"),
            technical_score=r.get("technical_score"),
            intraday_score=r.get("intraday_score"),
            passed_tiers=[
                t for t, passed in [
                    ("fundamental", r.get("passed_fundamental")),
                    ("technical", r.get("passed_technical")),
                    ("intraday", r.get("passed_intraday")),
                ] if passed
            ],
        )
        for r in results
    ]
