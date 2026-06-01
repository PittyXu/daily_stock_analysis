import React, { useCallback, useEffect, useRef, useState } from 'react';
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
  type SourceHealth,
  type StockDataItem,
} from '../api/dataDashboard';
import { cn } from '../utils/cn';

const STATUS_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  className: string;
}> = {
  ok: { icon: CheckCircle2, label: '正常', className: 'text-green-600 dark:text-green-400' },
  degraded: { icon: TriangleAlert, label: '降级', className: 'text-yellow-600 dark:text-yellow-400' },
  failed: { icon: XCircle, label: '失败', className: 'text-red-600 dark:text-red-400' },
  unknown: { icon: HelpCircle, label: '未知', className: 'text-gray-400' },
};

const STOCK_STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  ok: { label: '最新', className: 'text-green-600 dark:text-green-400' },
  stale: { label: '偏旧', className: 'text-yellow-600 dark:text-yellow-400' },
  expired: { label: '过期', className: 'text-red-600 dark:text-red-400' },
  empty: { label: '无数据', className: 'text-gray-400' },
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

  const mountedRef = useRef(true);

  const loadAll = useCallback(async () => {
    try {
      const [src, ast, stk, lg] = await Promise.all([
        getDataSources(),
        getAssets(),
        getStocks(),
        getLogs(),
      ]);
      if (!mountedRef.current) return;
      setSources(src);
      setAssets(ast);
      setStocks(stk);
      setLogs(lg);
      setError(null);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      const msg = e instanceof Error ? e.message : '加载数据失败';
      setError(msg);
    }
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    mountedRef.current = true;
    loadAll();
    return () => { mountedRef.current = false; };
  }, [loadAll]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const doRefreshStock = async (code: string) => {
    setRefreshing(prev => new Set(prev).add(code));
    try {
      await refreshStock(code);
    } catch { /* toast handled by API error interceptor */ }
    setRefreshing(prev => {
      const s = new Set(prev);
      s.delete(code);
      return s;
    });
    await loadAll();
  };

  const doBatchRefresh = async (type: 'daily' | 'news') => {
    setBatchRefreshing(type);
    try {
      const result: BatchRefreshResult =
        type === 'daily' ? await refreshAllDaily() : await refreshAllNews();
      if (result.failed > 0) {
        setError(`${result.failed}/${result.total} 只股票刷新失败`);
      }
    } catch { /* handled by error state */ }
    setBatchRefreshing(null);
    await loadAll();
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-8">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-foreground">数据监控</h1>
        <button type="button" onClick={loadAll} className="btn-ghost btn-sm" title="刷新全部">
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} className="ml-auto">&times;</button>
        </div>
      )}

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
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">
                    {s.provider.replace('Fetcher', '')}
                  </span>
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
                    {s.avgLatencyMs.toFixed(0)}ms 平均 &middot; {s.total24h}次/24h
                  </div>
                )}
                {s.lastErrorMessage && (
                  <div className="mt-1 truncate text-xs text-red-500" title={s.lastErrorMessage}>
                    {s.lastErrorType}: {s.lastErrorMessage.slice(0, 40)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-foreground">
          <Database className="h-5 w-5" /> 本地数据资产
        </h2>

        {assets && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-sm">
            <HardDrive className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">
              DB:{' '}
              <span className="font-medium text-foreground">{assets.dbSizeMb}MB</span>
            </span>
            <span className="text-muted-foreground">
              日线:{' '}
              <span className="font-medium text-foreground">
                {assets.dailyTotal.toLocaleString()}
              </span>
              条
            </span>
            <span className="text-muted-foreground">
              自选股:{' '}
              <span className="font-medium text-foreground">{assets.watchlistCount}</span>只
            </span>
            <span className="text-muted-foreground">
              过期:{' '}
              <span
                className={cn(
                  'font-medium',
                  assets.expiredCount > 0 ? 'text-red-500' : 'text-foreground',
                )}
              >
                {assets.expiredCount}
              </span>
              只
            </span>
          </div>
        )}

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
                  <tr key={s.code} className="transition-colors hover:bg-muted/50">
                    <td className="px-4 py-2.5 font-mono text-foreground">{s.code}</td>
                    <td className="px-4 py-2.5 text-foreground">{s.name || '-'}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">
                      {s.latestDailyDate || '-'}
                    </td>
                    <td className="px-4 py-2.5 text-right text-muted-foreground">
                      {s.dailyCount.toLocaleString()}
                    </td>
                    <td
                      className={cn(
                        'px-4 py-2.5 text-center text-xs font-medium',
                        sc.className,
                      )}
                    >
                      {sc.label}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <button
                        type="button"
                        onClick={() => doRefreshStock(s.code)}
                        disabled={isRefreshing}
                        className="btn-ghost btn-xs inline-flex items-center gap-1"
                      >
                        <RotateCw
                          className={cn('h-3 w-3', isRefreshing && 'animate-spin')}
                        />
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

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => doBatchRefresh('daily')}
            disabled={batchRefreshing !== null}
            className="btn-secondary btn-sm inline-flex items-center gap-1.5"
          >
            <RotateCw
              className={cn(
                'h-3.5 w-3.5',
                batchRefreshing === 'daily' && 'animate-spin',
              )}
            />
            刷新全部日线
          </button>
          <button
            type="button"
            onClick={() => doBatchRefresh('news')}
            disabled={batchRefreshing !== null}
            className="btn-secondary btn-sm inline-flex items-center gap-1.5"
          >
            <RotateCw
              className={cn('h-3.5 w-3.5', batchRefreshing === 'news' && 'animate-spin')}
            />
            刷新全部新闻
          </button>
        </div>

        <div className="mt-4">
          <button
            type="button"
            onClick={() => setLogsExpanded(!logsExpanded)}
            className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <span
              className={cn('inline-block transition-transform', logsExpanded && 'rotate-90')}
            >
              &#9656;
            </span>
            拉取日志 ({logs.length})
          </button>
          {logsExpanded && (
            <div className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-border bg-muted/30">
              <table className="w-full text-xs">
                <tbody className="divide-y divide-border">
                  {logs.map(l => (
                    <tr key={l.id} className="hover:bg-muted/50">
                      <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">
                        {l.createdAt
                          ? new Date(l.createdAt).toLocaleString('zh-CN', {
                              month: '2-digit',
                              day: '2-digit',
                              hour: '2-digit',
                              minute: '2-digit',
                              second: '2-digit',
                            })
                          : '-'}
                      </td>
                      <td className="px-3 py-1.5 font-medium text-foreground">{l.provider}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{l.operation || '-'}</td>
                      <td className="px-3 py-1.5">
                        {l.success ? (
                          <span className="text-green-600 dark:text-green-400">成功</span>
                        ) : (
                          <span className="text-red-500">失败</span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">
                        {l.latencyMs != null ? `${l.latencyMs}ms` : '-'}
                      </td>
                      <td
                        className="max-w-[200px] truncate px-3 py-1.5 text-red-500"
                        title={l.errorMessageSanitized || undefined}
                      >
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
