# -*- coding: utf-8 -*-
"""Data monitor API endpoints — data source health, local assets, manual refresh, logs."""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from api.v1.schemas.data_monitor import (
    AssetOverview,
    BatchRefreshResult,
    LogEntry,
    RefreshResult,
    SourceHealth,
    StockDataItem,
)
from data_provider.base import DataFetcherManager, normalize_stock_code
from src.config import get_config
from src.repositories.provider_log_repo import ProviderLogRepository
from src.storage import DatabaseManager, StockDaily

logger = logging.getLogger(__name__)

router = APIRouter()

ALL_FETCHER_NAMES = [
    "EfinanceFetcher",
    "AkshareFetcher",
    "TushareFetcher",
    "PytdxFetcher",
    "BaostockFetcher",
    "YfinanceFetcher",
    "LongbridgeFetcher",
    "FinnhubFetcher",
    "AlphaVantageFetcher",
]

_refresh_lock = threading.Lock()


def _get_db_path() -> str:
    db = DatabaseManager.get_instance()
    return db._db_url.replace("sqlite:///", "") if db._db_url else ""


def _get_watchlist_codes() -> list:
    config = get_config()
    stocks_str = getattr(config, "STOCK_LIST", "") or os.getenv("STOCK_LIST", "")
    return [c.strip() for c in stocks_str.split(",") if c.strip()]


def _get_session():
    db = DatabaseManager.get_instance()
    return db.get_session()


@router.get("/sources", response_model=list[SourceHealth])
def get_sources() -> list[SourceHealth]:
    log_repo = ProviderLogRepository()
    stats = log_repo.get_provider_stats(hours=24)
    stats_map = {}
    for s in stats:
        key = (s["provider"], s["data_type"])
        if key not in stats_map:
            stats_map[key] = s

    result = []
    for name in ALL_FETCHER_NAMES:
        key = (name, "daily_data")
        s = stats_map.get(key)
        last_error = log_repo.get_last_error(name)

        if not s or s["total"] == 0:
            status = "unknown"
            success_rate = None
        else:
            rate = s["success_count"] / s["total"]
            if rate >= 0.95:
                status = "ok"
            elif rate >= 0.50:
                status = "degraded"
            else:
                status = "failed"
            success_rate = round(rate, 4)

        result.append(
            SourceHealth(
                provider=name,
                data_type="daily_data",
                status=status,
                success_rate=success_rate,
                avg_latency_ms=round(s.get("avg_latency_ms", 0), 1)
                if s and s.get("avg_latency_ms")
                else None,
                total_24h=s["total"] if s else 0,
                success_24h=s["success_count"] if s else 0,
                last_error_type=last_error.get("error_type") if last_error else None,
                last_error_message=last_error.get("error_message_sanitized")
                if last_error
                else None,
                last_error_at=last_error.get("created_at") if last_error else None,
            )
        )

    return result


@router.get("/assets", response_model=AssetOverview)
def get_assets() -> AssetOverview:
    db_path = _get_db_path()
    db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2) if db_path else 0

    session = _get_session()
    try:
        daily_total = session.query(func.count(StockDaily.id)).scalar() or 0
        stock_count = (
            session.query(func.count(func.distinct(StockDaily.code))).scalar() or 0
        )

        watchlist = _get_watchlist_codes()
        watchlist_count = len(watchlist)

        dt_now = date.today()
        stale_cutoff = dt_now - timedelta(days=7)
        expired_count = 0
        for code in watchlist:
            latest = (
                session.query(func.max(StockDaily.date))
                .filter(StockDaily.code == code)
                .scalar()
            )
            if latest is None or latest < stale_cutoff:
                expired_count += 1

        return AssetOverview(
            db_size_mb=db_size_mb,
            daily_total=daily_total,
            stock_count=stock_count,
            watchlist_count=watchlist_count,
            expired_count=expired_count,
        )
    finally:
        session.close()


@router.get("/stocks", response_model=list[StockDataItem])
def get_stocks() -> list[StockDataItem]:
    session = _get_session()
    try:
        watchlist = _get_watchlist_codes()
        dt_now = date.today()
        result = []

        from src.data.stock_mapping import STOCK_NAME_MAP

        for code in watchlist:
            row = (
                session.query(
                    func.max(StockDaily.date).label("latest_date"),
                    func.count(StockDaily.id).label("cnt"),
                    func.max(StockDaily.data_source).label("src"),
                )
                .filter(StockDaily.code == code)
                .first()
            )

            if row and row.latest_date:
                latest_date = row.latest_date
                cnt = row.cnt
                src = row.src
                days_behind = (dt_now - latest_date).days
                if days_behind <= 1:
                    status = "ok"
                elif days_behind <= 7:
                    status = "stale"
                else:
                    status = "expired"
            else:
                latest_date = None
                cnt = 0
                src = None
                status = "empty"

            name = STOCK_NAME_MAP.get(code.upper())

            result.append(
                StockDataItem(
                    code=code,
                    name=name,
                    latest_daily_date=latest_date.isoformat() if latest_date else None,
                    daily_count=cnt or 0,
                    status=status,
                    data_source=src,
                )
            )

        return result
    finally:
        session.close()


@router.post("/refresh/stock/{code}", response_model=RefreshResult)
def refresh_stock(code: str) -> RefreshResult:
    try:
        code = normalize_stock_code(code)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_code", "message": f"无效代码: {code}"},
        )

    with _refresh_lock:
        try:
            manager = DataFetcherManager()
            df, provider_name = manager.get_daily_data(code)
            return RefreshResult(
                code=code,
                status="ok",
                provider=provider_name,
                rows=len(df) if df is not None else 0,
            )
        except Exception as e:
            return RefreshResult(code=code, status="failed", error=str(e))


@router.post("/refresh/all-daily", response_model=BatchRefreshResult)
def refresh_all_daily() -> BatchRefreshResult:
    watchlist = _get_watchlist_codes()
    results = []
    for code in watchlist:
        try:
            res = refresh_stock(code)
            results.append(res)
        except Exception as e:
            results.append(RefreshResult(code=code, status="failed", error=str(e)))

    success = sum(1 for r in results if r.status == "ok")
    return BatchRefreshResult(
        total=len(watchlist),
        success=success,
        failed=len(watchlist) - success,
        results=results,
    )


@router.post("/refresh/all-news", response_model=BatchRefreshResult)
def refresh_all_news() -> BatchRefreshResult:
    watchlist = _get_watchlist_codes()
    results = []

    with _refresh_lock:
        for code in watchlist:
            try:
                from src.agent.tools.search_tools import _handle_search_stock_news
                from src.data.stock_mapping import STOCK_NAME_MAP

                name = STOCK_NAME_MAP.get(code.upper()) or code
                news_result = _handle_search_stock_news(code, name)
                news_count = (
                    len(news_result.get("news_items", []))
                    if isinstance(news_result, dict)
                    else 0
                )
                results.append(
                    RefreshResult(
                        code=code,
                        status="ok",
                        provider="news_search",
                        rows=news_count,
                    )
                )
            except Exception as e:
                results.append(RefreshResult(code=code, status="failed", error=str(e)))

    success = sum(1 for r in results if r.status == "ok")
    return BatchRefreshResult(
        total=len(watchlist),
        success=success,
        failed=len(watchlist) - success,
        results=results,
    )


@router.get("/logs", response_model=list[LogEntry])
def get_logs(limit: int = 20) -> list[LogEntry]:
    log_repo = ProviderLogRepository()
    rows = log_repo.get_recent(limit=limit)
    return [LogEntry(**r) for r in rows]
