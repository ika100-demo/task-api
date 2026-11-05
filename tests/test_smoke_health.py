"""Smoke test (spec 091): `SMOKE_BASE_URL=https://<host> devbox run smoke` runs it.

It reaches the service only through its URL, never in-process. Without SMOKE_BASE_URL it is
skipped.
"""

from __future__ import annotations

import json
import urllib.request

import pytest


@pytest.mark.smoke
def test_health_answers_at_the_base_url(smoke_base_url: str) -> None:
    with urllib.request.urlopen(smoke_base_url + "/health", timeout=10) as response:
        assert response.status == 200
        assert json.load(response) == {"status": "ok"}
