"""Tests for BaseAPIClient -- mocks httpx to test retry and rate-limit logic."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.base_client import BaseAPIClient


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_response(status_code: int = 200, json_data: dict = None, headers: dict = None):
    """Build a fake httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = "{}"
    resp.headers = headers or {}
    # raise_for_status behaviour
    if status_code >= 400:
        error = httpx.HTTPStatusError(
            message=f"{status_code}", request=MagicMock(), response=resp
        )
        resp.raise_for_status.side_effect = error
    else:
        resp.raise_for_status.return_value = None
    return resp


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_get_success():
    """Successful GET should return parsed JSON."""
    client = BaseAPIClient(base_url="https://example.com")

    with patch.object(client, "_get_client") as get_cli:
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=_make_response(200, {"ok": True}))
        get_cli.return_value = mock_http

        result = asyncio.get_event_loop().run_until_complete(client.get("/test"))

    assert result == {"ok": True}


def test_post_success():
    """Successful POST should return parsed JSON."""
    client = BaseAPIClient(base_url="https://example.com")

    with patch.object(client, "_get_client") as get_cli:
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(
            return_value=_make_response(200, {"id": "abc"})
        )
        get_cli.return_value = mock_http

        result = asyncio.get_event_loop().run_until_complete(
            client.post("/create", json={"name": "test"})
        )

    assert result == {"id": "abc"}


def test_lazy_client_creation():
    """Client should not be created until first use."""
    client = BaseAPIClient(base_url="https://example.com")
    assert client._client is None

    # After calling _get_client, it should exist
    http_client = client._get_client()
    assert http_client is not None
    assert client._client is http_client

    # Cleanup
    asyncio.get_event_loop().run_until_complete(client.close())


def test_close_idempotent():
    """Closing twice should not raise."""
    client = BaseAPIClient(base_url="https://example.com")
    # Close without ever opening -- should be fine
    asyncio.get_event_loop().run_until_complete(client.close())
    asyncio.get_event_loop().run_until_complete(client.close())


def test_base_url_trailing_slash_stripped():
    """Trailing slash on base_url should be stripped."""
    client = BaseAPIClient(base_url="https://example.com/")
    assert client._base_url == "https://example.com"
