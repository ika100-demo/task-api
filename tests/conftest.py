"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from task_api.main import app


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)
