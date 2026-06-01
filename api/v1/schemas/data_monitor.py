# -*- coding: utf-8 -*-
"""Data monitor API schemas."""

from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field


class SourceHealth(BaseModel):
    provider: str = Field(..., description="数据源名称")
    data_type: str = Field("daily_data", description="数据类型")
    status: str = Field(..., description="ok / degraded / failed / unknown")
    success_rate: Optional[float] = Field(None, description="成功率 (0-1)")
    avg_latency_ms: Optional[float] = Field(None, description="平均延迟(毫秒)")
    total_24h: Optional[int] = Field(None, description="24h 总请求数")
    success_24h: Optional[int] = Field(None, description="24h 成功数")
    last_error_type: Optional[str] = Field(None, description="最近一次错误类型")
    last_error_message: Optional[str] = Field(
        None, description="最近一次错误信息(脱敏)"
    )
    last_error_at: Optional[str] = Field(None, description="最近一次错误时间")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider": "EfinanceFetcher",
                "status": "ok",
                "success_rate": 0.98,
                "avg_latency_ms": 120.5,
                "total_24h": 50,
                "success_24h": 49,
            }
        }
    )


class AssetOverview(BaseModel):
    db_size_mb: float = Field(..., description="SQLite DB 文件大小(MB)")
    daily_total: int = Field(..., description="日线数据总条数")
    stock_count: int = Field(..., description="唯一股票数")
    watchlist_count: int = Field(..., description="自选股数")
    expired_count: int = Field(..., description="过期股票数(>7天无更新)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "db_size_mb": 45.2,
                "daily_total": 128000,
                "stock_count": 50,
                "watchlist_count": 15,
                "expired_count": 2,
            }
        }
    )


class StockDataItem(BaseModel):
    code: str = Field(..., description="股票代码")
    name: Optional[str] = Field(None, description="股票名称")
    latest_daily_date: Optional[str] = Field(None, description="最新日线日期")
    daily_count: int = Field(0, description="日线条数")
    status: str = Field(..., description="ok / stale / expired / empty")
    data_source: Optional[str] = Field(None, description="数据来源")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "600519",
                "name": "贵州茅台",
                "latest_daily_date": "2026-06-04",
                "daily_count": 365,
                "status": "ok",
                "data_source": "EfinanceFetcher",
            }
        }
    )


class RefreshResult(BaseModel):
    code: str
    status: str = Field(..., description="ok / failed")
    provider: Optional[str] = None
    rows: Optional[int] = None
    error: Optional[str] = None


class BatchRefreshResult(BaseModel):
    total: int
    success: int
    failed: int
    results: List[RefreshResult] = []


class LogEntry(BaseModel):
    id: int
    provider: str
    data_type: Optional[str] = None
    operation: Optional[str] = None
    success: bool
    latency_ms: Optional[int] = None
    error_type: Optional[str] = None
    error_message_sanitized: Optional[str] = None
    created_at: Optional[str] = None
