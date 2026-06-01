# -*- coding: utf-8 -*-
"""Provider run log repository.

Provides DB access helpers for provider_run_log table.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import case, desc, func

from src.storage import DatabaseManager, ProviderRunLog

logger = logging.getLogger(__name__)


class ProviderLogRepository:
    """DB access layer for provider_run_log."""

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
                    func.sum(case((ProviderRunLog.success == True, 1), else_=0)).label(
                        "success_count"
                    ),
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
                    "avg_latency_ms": round(row.avg_latency_ms, 1)
                    if row.avg_latency_ms
                    else None,
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
