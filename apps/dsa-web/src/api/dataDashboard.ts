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
