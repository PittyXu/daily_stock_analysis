# 数据监控面板设计文档

**日期**: 2026-06-04
**状态**: 已确认

---

## 1. 概述

### 1.1 背景

当前系统有 9 个数据源 Fetcher（Efinance / Akshare / Tushare / Pytdx / Baostock / Yfinance / Longbridge / Finnhub / AlphaVantage），通过策略模式按优先级自动 failover。但存在以下痛点：

- **实时行情获取经常失败**（数据源渠道不稳定）
- **定时任务也会因数据源问题失败**
- 用户无法感知当前数据源的健康状态
- 其他模块（分析、选股、回测等）获取数据时策略不统一，无法利用已有缓存

### 1.2 目标

在 Web 左侧导航新增 "数据监控" 页面，提供：

1. **数据源健康监控**：展示 9 个 Fetcher 的成功率、延迟、24h 统计、失败原因
2. **本地数据资产概览**：SQLite DB 大小、日线覆盖、自选股最新日期 + 过期检测
3. **手动触发数据刷新**：支持单股/批量日线、新闻数据的按需拉取
4. **统一缓存策略**：日线数据本地有最新就复用以减少 API 调用

### 1.3 排除范围

- 大盘复盘监控
- 实时行情手动刷新（按需获取，5 分钟缓存复用即可）
- 基本面数据拉取
- 新闻源（Tavily/Bocha/Brave 等）的健康监控

---

## 2. 后端 API 设计

### 2.1 新增路由

在 `api/v1/endpoints/` 下新增 `data_monitor.py`，挂载到 `/api/v1/data`：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/data/sources` | 获取数据源健康状态 |
| GET | `/api/v1/data/assets` | 获取本地数据资产概览 |
| GET | `/api/v1/data/stocks` | 获取自选股数据明细列表 |
| POST | `/api/v1/data/refresh/stock/{code}` | 刷新单只股票日线数据 |
| POST | `/api/v1/data/refresh/all-daily` | 批量刷新全部自选股日线 |
| POST | `/api/v1/data/refresh/all-news` | 批量刷新全部自选股新闻 |
| GET | `/api/v1/data/logs` | 获取最近的拉取日志 |

### 2.2 数据持久化

新增 `provider_run_log` 表（SQLite），字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| provider | TEXT | 数据源名称 |
| data_type | TEXT | daily_data / realtime_quote / news |
| operation | TEXT | get_daily_data / get_realtime_quote |
| success | BOOLEAN | 是否成功 |
| latency_ms | INTEGER | 耗时(毫秒) |
| error_type | TEXT | 错误类型 |
| error_message_sanitized | TEXT | 脱敏错误信息 |
| record_count | INTEGER | 返回数据条数 |
| created_at | DATETIME | 创建时间 |

### 2.3 各端点实现逻辑

**GET /api/v1/data/sources**：
- 查询 `provider_run_log` 最近 24h 记录
- 按 provider + data_type 聚合统计（总次数、成功次数、平均延迟、最近错误）
- 返回 9 个 Fetcher 卡片数据，每个包含 `status: ok/degraded/failed/unknown`
- 若某 provider 30 天内无任何记录，状态为 `unknown`

**GET /api/v1/data/assets**：
- 返回 DB 文件大小 (`os.path.getsize`)
- 从 `stock_daily` 表统计：日线总条数、唯一股票数、自选股数
- 从 `stock_daily` 按 code 分组取 max(date)，判断是否过期（最近交易日无数据）

**GET /api/v1/data/stocks**：
- 遍历自选股列表，返回每只股票的：
  - code、name
  - latest_daily_date（日线最新日期）
  - daily_count（日线条数）
  - status：`ok`(今日/最近交易日有数据) / `stale`(N 天前) / `expired`(超过7天) / `empty`(无数据)

**POST /api/v1/data/refresh/stock/{code}**：
- 对指定股票触发日线数据拉取（复用 DataFetcherManager）
- 成功/失败结果计入 `provider_run_log`

**POST /api/v1/data/refresh/all-daily**：
- 遍历自选股，逐个拉取日线（带并发锁，避免重复触发）
- 返回 `{total, success, failed, results: [{code, status, provider, rows}]}`

**POST /api/v1/data/refresh/all-news**：
- 遍历自选股，逐个拉取新闻
- 返回 `{total, success, failed, results: [{code, status, provider}]}`

**GET /api/v1/data/logs**：
- 返回 `provider_run_log` 最近 20 条记录，按 created_at DESC

### 2.4 缓存策略

- 日线数据：`DataFetcherManager.get_daily_data()` 中判断 SQLite 已有最新交易日数据时跳过 API 调用
- 实时行情：前端/后端共享 5 分钟缓存窗口（不做额外端点，按需获取）

---

## 3. 前端设计

### 3.1 路由

`/data` → `DataDashboardPage.tsx`

### 3.2 导航

`SidebarNav.tsx` `NAV_ITEMS` 数组新增：

```ts
{ key: 'data', label: '数据', to: '/data', icon: Database }
```

### 3.3 页面布局

```
┌──────────────────────────────────────────────┐
│  📊 数据监控                                  │
│                                              │
│  ┌── 数据源健康 ──────────────────────────┐  │
│  │ [Efinance] [Akshare] [Tushare] ...     │  │
│  │   🟢 98%    🟡 85%    ⚪ -     ...     │  │
│  │   120ms   450ms     未使用             │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌── 本地数据资产 ────────────────────────┐  │
│  │ DB大小: 45MB | 日线: 128,000条 |         │  │
│  │ 自选股: 15只 | 过期: 2只                 │  │
│  │                                          │  │
│  │ 代码     名称    最新日线  条数  状态  操作 │  │
│  │ 600519  贵州茅台  06-04   365  🟢  刷新   │  │
│  │ hk00700 腾讯     06-03   200  🟡  刷新   │  │
│  │ AAPL    苹果     05-28    50  🔴  刷新   │  │
│  │ ...                                      │  │
│  │                                          │  │
│  │ [刷新全部日线] [刷新全部新闻]              │  │
│  │                                          │  │
│  │ ▼ 拉取日志                               │  │
│  │   06-04 12:03 Efinance 600519 成功 120ms │  │
│  │   06-04 12:03 Akshare  hk00700 失败 超时 │  │
│  └──────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

### 3.4 组件树

```
DataDashboardPage
├── ProviderHealthCards
│   └── SourceHealthCard × 9
├── LocalAssetPanel
│   ├── DbOverviewBar
│   ├── StockDataTable
│   │   └── StockDataRow × N
│   └── RefreshLogPanel (可折叠)
```

### 3.5 API 模块

新增 `apps/dsa-web/src/api/dataDashboard.ts`，export 函数：

```ts
getDataSources(): Promise<SourceHealth[]>
getAssets(): Promise<AssetOverview>
getStocks(): Promise<StockDataItem[]>
refreshStock(code: string): Promise<RefreshResult>
refreshAllDaily(): Promise<BatchRefreshResult>
refreshAllNews(): Promise<BatchRefreshResult>
getLogs(): Promise<LogEntry[]>
```

### 3.6 状态管理

页面内用 `useState` 管理，不引入 Zustand store（数据监控为独立页面，无需跨组件共享）。

### 3.7 错误处理

- `provider_run_log` 表不存在时自动创建（ORM `Base.metadata.create_all`）
- 某 Fetcher 30 天内完全无记录显示 `unknown` 状态
- refresh 接口超时 toast 提示
- DB 文件损坏时禁用刷新按钮
- 并发 refresh 加锁避免重复触发

---

## 4. 文件变更汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `api/v1/endpoints/data_monitor.py` | 新增 | 数据监控 API |
| `api/v1/schemas/data_monitor.py` | 新增 | 数据监控 Schema |
| `api/v1/router.py` | 修改 | 注册 `/api/v1/data` 路由 |
| `src/storage.py` | 修改 | 新增 `ProviderRunLog` ORM 模型 |
| `data_provider/base.py` | 修改 | `record_provider_run` 同步写 DB |
| `apps/dsa-web/src/pages/DataDashboardPage.tsx` | 新增 | 数据监控页面 |
| `apps/dsa-web/src/api/dataDashboard.ts` | 新增 | 前端 API 模块 |
| `apps/dsa-web/src/components/layout/SidebarNav.tsx` | 修改 | 新增 "数据" 导航项 |
| `apps/dsa-web/src/App.tsx` | 修改 | 注册 `/data` 路由 |
| `data_provider/__init__.py` | 不改 | 无需变动 |