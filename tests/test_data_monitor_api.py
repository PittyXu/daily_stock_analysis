# -*- coding: utf-8 -*-
"""Tests for /api/v1/data endpoints."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture
def client():
    temp_dir = tempfile.TemporaryDirectory()
    c = TestClient(create_app(static_dir=Path(temp_dir.name)))
    yield c
    temp_dir.cleanup()


def test_get_sources_returns_list(client):
    resp = client.get("/api/v1/data/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


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
    data = resp.json()
    assert isinstance(data, list)


def test_get_logs_returns_list(client):
    resp = client.get("/api/v1/data/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_refresh_stock_invalid_code_returns_400(client):
    resp = client.post("/api/v1/data/refresh/stock/!!INVALID!!")
    assert resp.status_code == 400
