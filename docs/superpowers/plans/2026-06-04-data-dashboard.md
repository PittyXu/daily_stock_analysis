# 数据监控面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Web 左侧导航新增"数据监控"页面，监控 9 个数据源健康状态、本地数据资产概览、支持手动刷新日线/新闻。

**Architecture:** 后端新增 `/api/v1/data` 路由组 7 个端点，`ProviderRunLog` ORM 模型持久化数据源调用记录（升级现有内存-only 的 `record_provider_run` 为 DB 双写），前端新增 `DataDashboardPage` 组件使用 lazy import 挂载到 `/data` 路由。

**Tech Stack:** Python FastAPI + Pydantic V2 + SQLAlchemy + React + TypeScript + lucide-react

**Spec:** `docs/superpowers/specs/2026-06-04-data-dashboard-design.md`

---

## File Structure

| File | Operation | Responsibility |
|------|-----------|---------------|
| `src/storage.py` | Modify | 新增 `ProviderRunLog` ORM 模型 |
| `src/repositories/provider_log_repo.py` | Create | ProviderRunLog DB 存取层 |
| `src/services/provider_log_service.py` | Create | 修改 `record_provider_run`，增加 DB 双写 |
| `api/v1/schemas/data_monitor.py` | Create | Pydantic 响应模型 |
| `api/v1/endpoints/data_monitor.py` | Create | 7 个 API 端点 |
| `api/v1/router.py` | Modify | 注册 `/api/v1/data` 路由 |
| `apps/dsa-web/src/api/dataDashboard.ts` | Create | 前端 API 模块 |
| `apps/dsa-web/src/pages/DataDashboardPage.tsx` | Create | 数据监控页面 |
| `apps/dsa-web/src/components/layout/SidebarNav.tsx` | Modify | 新增 Database 导航项 |
| `apps/dsa-web/src/App.tsx` | Modify | 注册 `/data` 路由 |
| `tests/test_data_monitor_api.py` | Create | API 集成测试 |

---

### Task 1: 新增 ProviderRunLog ORM 模型

**Files:**
- Modify: `src/storage.py` (在 FundamentalSnapshot 类之后插入)
- Test: `tests/test_data_monitor_api.py`

- [ ] **Step 1: 在 storage.py 新增 ProviderRunLog 模型**

在 `FundamentalSnapshot` 类之后插入：

```python
class ProviderRunLog(Base):
    """数据源调用日志模型
    持久化每次数据源调用的成功/失败/延迟信息
    """
    __tablename__ = 'provider_run_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), nullable=False, index=True)
    data_type = Column(String(32), nullable=False, index=True)
    operation = Column(String(255))
    success = Column(Boolean, nullable=False, default=False, index=True)
    latency_ms = Column(Integer)
    error_type = Column(String(100))
    error_message_sanitized = Column(Text)
    record_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('ix_log_provider_created', 'provider', 'created_at'),
    )

    def __repr__(self):
        return f"<ProviderRunLog(provider={self.provider}, data_type={self.data_type}, success={self.success})>"
```

- [ ] **Step 2: 在 DatabaseManager 中确认 `Base.metadata.create_all` 覆盖**

检查 `DatabaseManager.__init__` 方法末尾（搜索 `create_all`），确认 `Base.metadata.create_all` 会在初始化时自动创建新表。无需额外修改。

Run: `python -c "from src.storage import DatabaseManager, ProviderRunLog; print('Model imported OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/storage.py
git commit -m "feat: add ProviderRunLog ORM model for data source call logging"
```

---

### Task 2: 创建 provider_log_repo 数据访问层

**Files:**
- Create: `src/repositories/provider_log_repo.py`

- [ ] **Step 1: 创建 repository**

```python
# -*- coding: utf-8 -*-
"""Provider run log repository."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select

from src.storage import DatabaseManager, ProviderRunLog

logger = logging.getLogger(__name__)


class ProviderLogRepository:

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    @contextmanager
    def _session(self):
        session = self.db.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def insert(self, log_data: Dict[str, Any]) -> None:
        row = ProviderRunLog(**log_data)
        with self._session() as s:
            s.add(row)

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._session() as s:
            rows = (
                s.query(ProviderRunLog)
                .order_by(desc(ProviderRunLog.created_at))
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "provider": r.provider,
                    "data_type": r.data_type,
                    "operation": r.operation,
                    "success": r.success,
                    "latency_ms": r.latency_ms,
                    "error_type": r.error_type,
                    "error_message_sanitized": r.error_message_sanitized,
                    "record_count": r.record_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    def get_provider_stats(self, hours: int = 24) -> List[Dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._session() as s:
            rows = (
                s.query(
                    ProviderRunLog.provider,
                    ProviderRunLog.data_type,
                    func.count().label("total"),
                    func.sum(ProviderRunLog.success.cast(Integer)).label("success_count"),
                    func.avg(ProviderRunLog.latency_ms).label("avg_latency_ms"),
                    func.max(ProviderRunLog.created_at).label("last_run"),
                )
                .filter(ProviderRunLog.created_at >= cutoff)
                .group_by(ProviderRunLog.provider, ProviderRunLog.data_type)
                .all()
            )
            return [
                {
                    "provider": row.provider,
                    "data_type": row.data_type,
                    "total": row.total,
                    "success_count": row.success_count or 0,
                    "avg_latency_ms": round(row.avg_latency_ms, 1) if row.avg_latency_ms else None,
                    "last_run": row.last_run.isoformat() if row.last_run else None,
                }
                for row in rows
            ]

    def get_last_error(self, provider: str) -> Optional[Dict[str, Any]]:
        with self._session() as s:
            row = (
                s.query(ProviderRunLog)
                .filter(
                    ProviderRunLog.provider == provider,
                    ProviderRunLog.success == False,
                )
                .order_by(desc(ProviderRunLog.created_at))
                .first()
            )
            if not row:
                return None
            return {
                "error_type": row.error_type,
                "error_message_sanitized": row.error_message_sanitized,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
```

- [ ] **Step 2: 验证导入**

```bash
python -c "from src.repositories.provider_log_repo import ProviderLogRepository; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/repositories/provider_log_repo.py
git commit -m "feat: add ProviderLogRepository for provider run log persistence"
```

---

### Task 3: 升级 record_provider_run 支持 DB 双写

**Files:**
- Modify: `src/services/run_diagnostics.py` (修改 `record_provider_run` 函数尾部)
- Test: `tests/test_data_monitor_api.py`

**Background:** `record_provider_run` 当前只在 ContextVar 中记录 `ProviderRun` dataclass。需在函数末尾追加 DB 写入逻辑，使用 try/except 包裹，持久化失败不抛异常（不阻塞主流程）。

- [ ] **Step 1: 找到 record_provider_run 函数**

```bash
grep -n "def record_provider_run" src/services/run_diagnostics.py
```

假设在 line 540 附近。

- [ ] **Step 2: 在函数末尾追加 DB 双写逻辑**

在 `_CURRENT_CONTEXT` append 逻辑之后，函数 return 之前插入：

```python
    # DB 双写（fail-open：持久化失败不抛异常）
    try:
        from src.repositories.provider_log_repo import ProviderLogRepository
        ProviderLogRepository().insert({
            "provider": run.provider,
            "data_type": run.data_type,
            "operation": run.operation,
            "success": run.success,
            "latency_ms": run.latency_ms,
            "error_type": run.error_type,
            "error_message_sanitized": run.error_message_sanitized,
            "record_count": run.record_count,
            "created_at": datetime.fromisoformat(run.created_at) if run.created_at else datetime.now(),
        })
    except Exception:
        pass
```

- [ ] **Step 3: 验证导入不破坏现有功能**

```bash
python -c "from data_provider.base import DataFetcherManager; print('import OK')"
python -m py_compile src/services/run_diagnostics.py
```

- [ ] **Step 4: Commit**

```bash
git add src/services/run_diagnostics.py
git commit -m "feat: add DB persistence to record_provider_run (dual-write, fail-open)"
```

---

### Task 4: 创建 data_monitor Pydantic Schemas

**Files:**
- Create: `api/v1/schemas/data_monitor.py`

- [ ] **Step 1: 创建 Schema 文件**

```python
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
    last_error_message: Optional[str] = Field(None, description="最近一次错误信息(脱敏)")
    last_error_at: Optional[str] = Field(None, description="最近一次错误时间")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "provider": "EfinanceFetcher",
            "status": "ok",
            "success_rate": 0.98,
            "avg_latency_ms": 120.5,
            "total_24h": 50,
            "success_24h": 49,
        }
    })


class AssetOverview(BaseModel):
    db_size_mb: float = Field(..., description="SQLite DB 文件大小(MB)")
    daily_total: int = Field(..., description="日线数据总条数")
    stock_count: int = Field(..., description="唯一股票数")
    watchlist_count: int = Field(..., description="自选股数")
    expired_count: int = Field(..., description="过期股票数(>7天无更新)")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "db_size_mb": 45.2,
            "daily_total": 128000,
            "stock_count": 50,
            "watchlist_count": 15,
            "expired_count": 2,
        }
    })


class StockDataItem(BaseModel):
    code: str = Field(..., description="股票代码")
    name: Optional[str] = Field(None, description="股票名称")
    latest_daily_date: Optional[str] = Field(None, description="最新日线日期")
    daily_count: int = Field(0, description="日线条数")
    status: str = Field(..., description="ok / stale / expired / empty")
    data_source: Optional[str] = Field(None, description="数据来源")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "code": "600519",
            "name": "贵州茅台",
            "latest_daily_date": "2026-06-04",
            "daily_count": 365,
            "status": "ok",
            "data_source": "EfinanceFetcher",
        }
    })


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
```

- [ ] **Step 2: 验证 Schema**

```bash
python -c "from api.v1.schemas.data_monitor import SourceHealth, AssetOverview, StockDataItem; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add api/v1/schemas/data_monitor.py
git commit -m "feat: add data monitor API schemas"
```

---

### Task 5: 创建 data_monitor API 端点

**Files:**
- Create: `api/v1/endpoints/data_monitor.py`

- [ ] **Step 1: 创建端点文件 (7 个端点)**

```python
# -*- coding: utf-8 -*-
"""Data monitor API endpoints — 数据源健康/本地资产/手动刷新/日志."""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, func

from api.v1.schemas.data_monitor import (
    AssetOverview,
    BatchRefreshResult,
    LogEntry,
    RefreshResult,
    SourceHealth,
    StockDataItem,
)
from data_provider.base import DataFetcherManager, normalize_stock_code
from data_provider import (
    EfinanceFetcher, AkshareFetcher, TushareFetcher, PytdxFetcher,
    BaostockFetcher, YfinanceFetcher, LongbridgeFetcher,
    FinnhubFetcher, AlphaVantageFetcher,
)
from src.config import get_config
from src.repositories.provider_log_repo import ProviderLogRepository
from src.storage import DatabaseManager, StockDaily, NewsIntel, Base

logger = logging.getLogger(__name__)

router = APIRouter()

ALL_FETCHER_NAMES = [
    "EfinanceFetcher", "AkshareFetcher", "TushareFetcher", "PytdxFetcher",
    "BaostockFetcher", "YfinanceFetcher", "LongbridgeFetcher",
    "FinnhubFetcher", "AlphaVantageFetcher",
]

_refresh_lock = threading.Lock()


def _get_db_path() -> str:
    return DatabaseManager.get_instance().engine.url.database or ""


def _get_watchlist_codes() -> list:
    config = get_config()
    stocks_str = getattr(config, "STOCK_LIST", "") or os.getenv("STOCK_LIST", "")
    return [c.strip() for c in stocks_str.split(",") if c.strip()]


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
    dt_now = date.today()
    stale_cutoff = dt_now - timedelta(days=7)

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
            elif rate >= 0.5:
                status = "degraded"
            else:
                status = "failed"
            success_rate = round(rate, 4)

        result.append(SourceHealth(
            provider=name,
            data_type="daily_data",
            status=status,
            success_rate=success_rate,
            avg_latency_ms=round(s.get("avg_latency_ms", 0), 1) if s and s.get("avg_latency_ms") else None,
            total_24h=s["total"] if s else 0,
            success_24h=s["success_count"] if s else 0,
            last_error_type=last_error.get("error_type") if last_error else None,
            last_error_message=last_error.get("error_message_sanitized") if last_error else None,
            last_error_at=last_error.get("created_at") if last_error else None,
        ))

    return result


@router.get("/assets", response_model=AssetOverview)
def get_assets() -> AssetOverview:
    db_path = _get_db_path()
    db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2) if db_path else 0

    db = DatabaseManager.get_instance()
    session = db.get_session()
    try:
        daily_total = session.query(func.count(StockDaily.id)).scalar() or 0
        stock_count = session.query(func.count(func.distinct(StockDaily.code))).scalar() or 0

        watchlist = _get_watchlist_codes()
        watchlist_count = len(watchlist)

        dt_now = date.today()
        stale_cutoff = dt_now - timedelta(days=7)
        expired_count = 0
        if watchlist:
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
    db = DatabaseManager.get_instance()
    session = db.get_session()
    try:
        watchlist = _get_watchlist_codes()
        dt_now = date.today()
        result = []

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

            from src.data.stock_mapping import STOCK_NAME_MAP
            name = STOCK_NAME_MAP.get(code.upper())

            result.append(StockDataItem(
                code=code,
                name=name,
                latest_daily_date=latest_date.isoformat() if latest_date else None,
                daily_count=cnt or 0,
                status=status,
                data_source=src,
            ))

        return result
    finally:
        session.close()


@router.post("/refresh/stock/{code}", response_model=RefreshResult)
def refresh_stock(code: str) -> RefreshResult:
    try:
        code = normalize_stock_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "invalid_code", "message": f"无效代码: {code}"})

    with _refresh_lock:
        try:
            manager = DataFetcherManager.get_instance()
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
    config = get_config()
    watchlist = _get_watchlist_codes()
    results = []

    with _refresh_lock:
        for code in watchlist:
            try:
                manager = DataFetcherManager.get_instance()
                news = manager.get_news_context(code)
                if isinstance(news, dict):
                    news_count = len(news.get("items", []))
                else:
                    news_count = 0
                results.append(RefreshResult(code=code, status="ok", provider="news_pipeline", rows=news_count))
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
```

- [ ] **Step 2: 验证路由可用**

```bash
python -c "
try:
    from api.v1.endpoints.data_monitor import router
    print(f'OK, {len(router.routes)} routes registered')
except ImportError as e:
    print(f'FAIL: {e}')
"
```

Expected: `OK, 7 routes registered`

- [ ] **Step 3: Commit**

```bash
git add api/v1/endpoints/data_monitor.py
git commit -m "feat: add /api/v1/data endpoints for health/assets/stocks/refresh/logs"
```

---

### Task 6: 注册 /api/v1/data 路由

**Files:**
- Modify: `api/v1/router.py`

- [ ] **Step 1: 在 router.py 中注册新路由**

在 `api/v1/router.py` 的 import 和 include_router 中新增：

```python
# import 行新增（在 from api.v1.endpoints import ... 行末尾添加 data_monitor）
from api.v1.endpoints import alerts, analysis, auth, history, stocks, backtest, system_config, agent, usage, portfolio, alphasift, health, data_monitor

# include_router 新增（在 health.router 之后）
router.include_router(
    data_monitor.router,
    prefix="/data",
    tags=["DataMonitor"]
)
```

- [ ] **Step 2: 验证路由注册**

```bash
python -c "
from api.v1.router import router
paths = [r.path for r in router.routes]
for p in sorted(paths):
    print(p)
" | grep /api/v1/data
```

Expected: 看到 `/api/v1/data/sources`, `/api/v1/data/assets` 等路径

- [ ] **Step 3: Commit**

```bash
git add api/v1/router.py
git commit -m "feat: register /api/v1/data router group"
```

---

### Task 7: 创建前端 API 模块

**Files:**
- Create: `apps/dsa-web/src/api/dataDashboard.ts`

- [ ] **Step 1: 检查现有 API 模块模式（已在上文探索中确认）**

现有 API 模块使用 `apiClient` (axios instance from `api/index.ts`) + `toCamelCase` 转换。

- [ ] **Step 2: 创建 dataDashboard.ts**

```typescript
import apiClient from './index';
import { toCamelCase } from './utils';

export interface SourceHealth {
  provider: string;
  dataType: string;
  status: 'ok' | 'degraded' | 'failed' | 'unknown';
  successRate: number | null;
  avgLatencyMs: number | null;
  total24h: number;
  success24h: number;
  lastErrorType: string | null;
  lastErrorMessage: string | null;
  lastErrorAt: string | null;
}

export interface AssetOverview {
  dbSizeMb: number;
  dailyTotal: number;
  stockCount: number;
  watchlistCount: number;
  expiredCount: number;
}

export interface StockDataItem {
  code: string;
  name: string | null;
  latestDailyDate: string | null;
  dailyCount: number;
  status: 'ok' | 'stale' | 'expired' | 'empty';
  dataSource: string | null;
}

export interface RefreshResult {
  code: string;
  status: 'ok' | 'failed';
  provider: string | null;
  rows: number | null;
  error: string | null;
}

export interface BatchRefreshResult {
  total: number;
  success: number;
  failed: number;
  results: RefreshResult[];
}

export interface LogEntry {
  id: number;
  provider: string;
  dataType: string | null;
  operation: string | null;
  success: boolean;
  latencyMs: number | null;
  errorType: string | null;
  errorMessageSanitized: string | null;
  createdAt: string | null;
}

export async function getDataSources(): Promise<SourceHealth[]> {
  const res = await apiClient.get('/api/v1/data/sources');
  return toCamelCase<SourceHealth[]>(res.data);
}

export async function getAssets(): Promise<AssetOverview> {
  const res = await apiClient.get('/api/v1/data/assets');
  return toCamelCase<AssetOverview>(res.data);
}

export async function getStocks(): Promise<StockDataItem[]> {
  const res = await apiClient.get('/api/v1/data/stocks');
  return toCamelCase<StockDataItem[]>(res.data);
}

export async function refreshStock(code: string): Promise<RefreshResult> {
  const res = await apiClient.post(`/api/v1/data/refresh/stock/${code}`);
  return toCamelCase<RefreshResult>(res.data);
}

export async function refreshAllDaily(): Promise<BatchRefreshResult> {
  const res = await apiClient.post('/api/v1/data/refresh/all-daily');
  return toCamelCase<BatchRefreshResult>(res.data);
}

export async function refreshAllNews(): Promise<BatchRefreshResult> {
  const res = await apiClient.post('/api/v1/data/refresh/all-news');
  return toCamelCase<BatchRefreshResult>(res.data);
}

export async function getLogs(): Promise<LogEntry[]> {
  const res = await apiClient.get('/api/v1/data/logs');
  return toCamelCase<LogEntry[]>(res.data);
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/dsa-web/src/api/dataDashboard.ts
git commit -m "feat: add frontend data dashboard API module"
```

---

### Task 8: 新增 SidebarNav 导航项

**Files:**
- Modify: `apps/dsa-web/src/components/layout/SidebarNav.tsx`

- [ ] **Step 1: 添加 Database 图标 import 和 NAV_ITEMS 项**

在 `lucide-react` import 行末尾添加 `Database`：

```tsx
// 修改 line 2:
import { BarChart3, Bell, BriefcaseBusiness, Database, Home, LogOut, MessageSquareQuote, Search, Settings2 } from 'lucide-react';
```

在 NAV_ITEMS 数组末尾（settings 之后）添加：

```tsx
{ key: 'data', label: '数据', to: '/data', icon: Database },
```

修改后 NAV_ITEMS 为：
```tsx
const NAV_ITEMS: NavItem[] = [
  { key: 'home', label: '首页', to: '/', icon: Home, exact: true },
  { key: 'chat', label: '问股', to: '/chat', icon: MessageSquareQuote, badge: 'completion' },
  { key: 'screening', label: '选股', to: '/screening', icon: Search },
  { key: 'portfolio', label: '持仓', to: '/portfolio', icon: BriefcaseBusiness },
  { key: 'backtest', label: '回测', to: '/backtest', icon: BarChart3 },
  { key: 'alerts', label: '告警', to: '/alerts', icon: Bell },
  { key: 'settings', label: '设置', to: '/settings', icon: Settings2 },
  { key: 'data', label: '数据', to: '/data', icon: Database },
];
```

- [ ] **Step 2: 验证前端 lint**

```bash
cd apps/dsa-web && npx tsc --noEmit --pretty 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/dsa-web/src/components/layout/SidebarNav.tsx
git commit -m "feat: add Database nav item to sidebar"
```

---

### Task 9: 注册 /data 前端路由

**Files:**
- Modify: `apps/dsa-web/src/App.tsx`

- [ ] **Step 1: 添加 lazy import 和 Route**

在 `App.tsx` 的 lazy imports 区域新增：

```tsx
const DataDashboardPage = lazy(() => import('./pages/DataDashboardPage'));
```

在 `<Routes>` 内部 (`<Shell>` children) 的 Route 列表中新增：

```tsx
<Route path="/data" element={<DataDashboardPage />} />
```

插入位置：在 `<Route path="/settings" ... />` 之后。

- [ ] **Step 2: Commit**

```bash
git add apps/dsa-web/src/App.tsx
git commit -m "feat: register /data route for DataDashboardPage"
```

---

### Task 10: 创建 DataDashboardPage 前端页面

**Files:**
- Create: `apps/dsa-web/src/pages/DataDashboardPage.tsx`

- [ ] **Step 1: 参考现有页面模式**

现有页面如 `PortfolioPage.tsx` 使用函数组件 + useState + useEffect fetch 模式。复制并发模式：页面挂载时 `useEffect` fetch 数据。

- [ ] **Step 2: 创建 DataDashboardPage.tsx**

```tsx
import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Database,
  HardDrive,
  HelpCircle,
  RefreshCw,
  RotateCw,
  TriangleAlert,
  XCircle,
} from 'lucide-react';
import {
  getAssets,
  getDataSources,
  getLogs,
  getStocks,
  refreshAllDaily,
  refreshAllNews,
  refreshStock,
  type AssetOverview,
  type BatchRefreshResult,
  type LogEntry,
  type RefreshResult,
  type SourceHealth,
  type StockDataItem,
} from '../api/dataDashboard';
import { cn } from '../utils/cn';

const STATUS_CONFIG: Record<string, { icon: React.ComponentType<{ className?: string }>; label: string; className: string }> = {
  ok:       { icon: CheckCircle2,  label: '正常', className: 'text-green-600 dark:text-green-400' },
  degraded: { icon: TriangleAlert, label: '降级', className: 'text-yellow-600 dark:text-yellow-400' },
  failed:   { icon: XCircle,       label: '失败', className: 'text-red-600 dark:text-red-400' },
  unknown:  { icon: HelpCircle,    label: '未知', className: 'text-gray-400' },
};

const STOCK_STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  ok:      { label: '最新', className: 'text-green-600 dark:text-green-400' },
  stale:   { label: '偏旧', className: 'text-yellow-600 dark:text-yellow-400' },
  expired: { label: '过期', className: 'text-red-600 dark:text-red-400' },
  empty:   { label: '无数据', className: 'text-gray-400' },
};

export default function DataDashboardPage() {
  const [sources, setSources] = useState<SourceHealth[]>([]);
  const [assets, setAssets] = useState<AssetOverview | null>(null);
  const [stocks, setStocks] = useState<StockDataItem[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logsExpanded, setLogsExpanded] = useState(false);
  const [refreshing, setRefreshing] = useState<Set<string>>(new Set());
  const [batchRefreshing, setBatchRefreshing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [src, ast, stk, lg] = await Promise.all([
        getDataSources(),
        getAssets(),
        getStocks(),
        getLogs(),
      ]);
      setSources(src);
      setAssets(ast);
      setStocks(stk);
      setLogs(lg);
    } catch (e: any) {
      setError(e?.response?.data?.message || '加载数据失败');
    }
  }, []);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const doRefreshStock = async (code: string) => {
    setRefreshing(prev => new Set(prev).add(code));
    try {
      await refreshStock(code);
    } catch { /* toast handled by API error interceptor */ }
    setRefreshing(prev => { const s = new Set(prev); s.delete(code); return s; });
    await loadAll();
  };

  const doBatchRefresh = async (type: 'daily' | 'news') => {
    setBatchRefreshing(type);
    try {
      const result: BatchRefreshResult = type === 'daily' ? await refreshAllDaily() : await refreshAllNews();
      if (result.failed > 0) {
        setError(`${result.failed}/${result.total} 只股票刷新失败`);
      }
    } catch { /* handled by interceptor */ }
    setBatchRefreshing(null);
    await loadAll();
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-foreground">数据监控</h1>
        <button onClick={loadAll} className="btn-ghost btn-sm" title="刷新全部">
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto">&times;</button>
        </div>
      )}

      {/* Section 1: Provider Health Cards */}
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-foreground">
          <Activity className="h-5 w-5" /> 数据源健康
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {sources.map(s => {
            const cfg = STATUS_CONFIG[s.status] || STATUS_CONFIG.unknown;
            const Icon = cfg.icon;
            return (
              <div key={s.provider} className="rounded-xl border border-border bg-card p-4 shadow-sm">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-muted-foreground">{s.provider.replace('Fetcher', '')}</span>
                  <Icon className={cn('h-4 w-4', cfg.className)} />
                </div>
                <div className="flex items-baseline gap-1.5">
                  <span className="text-xl font-bold text-foreground">
                    {s.successRate != null ? `${(s.successRate * 100).toFixed(0)}%` : '-'}
                  </span>
                  <span className="text-xs text-muted-foreground">{cfg.label}</span>
                </div>
                {s.avgLatencyMs != null && (
                  <div className="mt-1.5 text-xs text-muted-foreground">
                    {s.avgLatencyMs.toFixed(0)}ms 平均 · {s.total24h}次/24h
                  </div>
                )}
                {s.lastErrorMessage && (
                  <div className="mt-1 text-xs text-red-500 truncate" title={s.lastErrorMessage}>
                    {s.lastErrorType}: {s.lastErrorMessage.slice(0, 40)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Section 2: Local Assets + Stock Table + Refresh */}
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-foreground">
          <Database className="h-5 w-5" /> 本地数据资产
        </h2>

        {/* DB Overview Bar */}
        {assets && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-sm">
            <HardDrive className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">DB: <span className="font-medium text-foreground">{assets.dbSizeMb}MB</span></span>
            <span className="text-muted-foreground">日线: <span className="font-medium text-foreground">{assets.dailyTotal.toLocaleString()}</span>条</span>
            <span className="text-muted-foreground">自选股: <span className="font-medium text-foreground">{assets.watchlistCount}</span>只</span>
            <span className="text-muted-foreground">过期: <span className={cn('font-medium', assets.expiredCount > 0 ? 'text-red-500' : 'text-foreground')}>{assets.expiredCount}</span>只</span>
          </div>
        )}

        {/* Stock Data Table */}
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">代码</th>
                <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">名称</th>
                <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">最新日线</th>
                <th className="px-4 py-2.5 text-right font-medium text-muted-foreground">条数</th>
                <th className="px-4 py-2.5 text-center font-medium text-muted-foreground">状态</th>
                <th className="px-4 py-2.5 text-center font-medium text-muted-foreground">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {stocks.map(s => {
                const sc = STOCK_STATUS_CONFIG[s.status] || STOCK_STATUS_CONFIG.empty;
                const isRefreshing = refreshing.has(s.code);
                return (
                  <tr key={s.code} className="hover:bg-muted/50 transition-colors">
                    <td className="px-4 py-2.5 font-mono text-foreground">{s.code}</td>
                    <td className="px-4 py-2.5 text-foreground">{s.name || '-'}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">{s.latestDailyDate || '-'}</td>
                    <td className="px-4 py-2.5 text-right text-muted-foreground">{s.dailyCount.toLocaleString()}</td>
                    <td className={cn('px-4 py-2.5 text-center text-xs font-medium', sc.className)}>{sc.label}</td>
                    <td className="px-4 py-2.5 text-center">
                      <button
                        onClick={() => doRefreshStock(s.code)}
                        disabled={isRefreshing}
                        className="btn-ghost btn-xs inline-flex items-center gap-1"
                      >
                        <RotateCw className={cn('h-3 w-3', isRefreshing && 'animate-spin')} />
                        刷新
                      </button>
                    </td>
                  </tr>
                );
              })}
              {stocks.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    暂无自选股数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Batch Refresh Buttons */}
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => doBatchRefresh('daily')}
            disabled={batchRefreshing !== null}
            className="btn-secondary btn-sm inline-flex items-center gap-1.5"
          >
            <RotateCw className={cn('h-3.5 w-3.5', batchRefreshing === 'daily' && 'animate-spin')} />
            刷新全部日线
          </button>
          <button
            onClick={() => doBatchRefresh('news')}
            disabled={batchRefreshing !== null}
            className="btn-secondary btn-sm inline-flex items-center gap-1.5"
          >
            <RotateCw className={cn('h-3.5 w-3.5', batchRefreshing === 'news' && 'animate-spin')} />
            刷新全部新闻
          </button>
        </div>

        {/* Refresh Log Panel (collapsible) */}
        <div className="mt-4">
          <button
            onClick={() => setLogsExpanded(!logsExpanded)}
            className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <span className={cn('inline-block transition-transform', logsExpanded && 'rotate-90')}>&#9656;</span>
            拉取日志 ({logs.length})
          </button>
          {logsExpanded && (
            <div className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-border bg-muted/30">
              <table className="w-full text-xs">
                <tbody className="divide-y divide-border">
                  {logs.map(l => (
                    <tr key={l.id} className="hover:bg-muted/50">
                      <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">
                        {l.createdAt ? new Date(l.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-'}
                      </td>
                      <td className="px-3 py-1.5 font-medium text-foreground">{l.provider}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{l.operation || '-'}</td>
                      <td className="px-3 py-1.5">
                        {l.success
                          ? <span className="text-green-600 dark:text-green-400">成功</span>
                          : <span className="text-red-500">失败</span>}
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{l.latencyMs != null ? `${l.latencyMs}ms` : '-'}</td>
                      <td className="px-3 py-1.5 text-red-500 truncate max-w-[200px]" title={l.errorMessageSanitized || undefined}>
                        {l.errorType || '-'}
                      </td>
                    </tr>
                  ))}
                  {logs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-4 text-center text-muted-foreground">
                        暂无日志
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: 验证 TypeScript 编译**

```bash
cd apps/dsa-web && npx tsc --noEmit --pretty 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add apps/dsa-web/src/pages/DataDashboardPage.tsx
git commit -m "feat: add DataDashboardPage with provider health, stock table, refresh controls"
```

---

### Task 11: 集成测试 & 手动验证

**Files:**
- Create: `tests/test_data_monitor_api.py`

- [ ] **Step 1: 创建 API 集成测试（离线）**

```python
# -*- coding: utf-8 -*-
"""Tests for /api/v1/data endpoints (offline/no-server)."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from server import create_app


@pytest.fixture
def client():
    """Create FastAPI test client with overridden DataFetcherManager."""
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_get_sources_returns_list(client):
    resp = client.get("/api/v1/data/sources")
    # May return empty if no provider logs (dark launch), but must be valid JSON list
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_assets_returns_data(client):
    resp = client.get("/api/v1/data/assets")
    assert resp.status_code == 200
    data = resp.json()
    assert "dbSizeMb" in data
    assert "dailyTotal" in data
    assert "watchlistCount" in data


def test_get_stocks_returns_list(client):
    resp = client.get("/api/v1/data/stocks")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_logs_returns_list(client):
    resp = client.get("/api/v1/data/logs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_refresh_stock_invalid_code_returns_400(client):
    resp = client.post("/api/v1/data/refresh/stock/!!INVALID!!")
    assert resp.status_code == 400
```

- [ ] **Step 2: 运行测试**

```bash
python -m pytest tests/test_data_monitor_api.py -v
```

Expected: 5 PASS (offline tests, no network required)

- [ ] **Step 3: Commit**

```bash
git add tests/test_data_monitor_api.py
git commit -m "test: add data monitor API integration tests"
```

---

### Task 12: 前端构建验证

- [ ] **Step 1: 运行前端构建**

```bash
cd apps/dsa-web && npm run build
```

Expected: BUILD SUCCESS, no errors.

- [ ] **Step 2: 如有构建错误，修复后重复**

- [ ] **Step 3: Commit (if fixes needed)**

```bash
git add -A && git commit -m "fix: build errors for data dashboard frontend"
```