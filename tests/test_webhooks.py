"""Tests for the Telegram webhook endpoint -- uses TestClient with in-memory DB."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models.content import ContentItem, ContentStatus


@pytest.fixture
def client():
    return TestClient(app)


def _make_callback_payload(action: str, content_id: int) -> dict:
    """Build a minimal Telegram Update with callback_query."""
    return {
        "update_id": 123456,
        "callback_query": {
            "id": "cb-1",
            "data": f"{action}:{content_id}",
            "from": {
                "id": 111,
                "username": "testuser",
                "first_name": "Test",
            },
            "message": {
                "message_id": 50,
                "chat": {"id": 12345, "type": "private"},
            },
        },
    }


# ------------------------------------------------------------------
# Basic webhook tests
# ------------------------------------------------------------------


def test_webhook_no_callback_query(client):
    """Update without callback_query should return ok."""
    response = client.post(
        "/webhooks/telegram",
        json={"update_id": 1, "message": {"text": "hello"}},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_webhook_invalid_json(client):
    """Invalid JSON should return 400."""
    response = client.post(
        "/webhooks/telegram",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


def test_webhook_missing_content_id(client):
    """Callback with non-numeric content_id should return ok (no crash)."""
    payload = {
        "callback_query": {
            "id": "cb-1",
            "data": "approve:invalid",
            "from": {"id": 1, "username": "u"},
            "message": {"message_id": 1, "chat": {"id": 1}},
        }
    }
    response = client.post("/webhooks/telegram", json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_webhook_content_not_found(client):
    """Callback for non-existent content should return ok (gracefully handled)."""
    payload = _make_callback_payload("approve", 99999)
    response = client.post("/webhooks/telegram", json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is True


# ------------------------------------------------------------------
# Approve / reject flow (requires a real content item in the DB)
# ------------------------------------------------------------------


def _create_content_item(db_session, bot_id: int = None) -> ContentItem:
    """Insert a minimal ContentItem into the test DB."""
    from app.models.bot import Bot

    # Create a bot if we don't have one
    if bot_id is None:
        bot = Bot(
            name="WebhookTestBot",
            slug="webhooktestbot",
            niche="tech",
        )
        db_session.add(bot)
        db_session.flush()
        bot_id = bot.id

    item = ContentItem(
        bot_id=bot_id,
        status=ContentStatus.PENDING_APPROVAL.value,
        trend_topic="test topic",
    )
    db_session.add(item)
    db_session.commit()
    return item


def test_webhook_approve_updates_status(client):
    """Approve callback should set status to 'approved'."""
    from app.database import get_db

    # Get a DB session from the test override
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)

    item = _create_content_item(db)
    content_id = item.id

    mock_tg = AsyncMock()
    mock_tg.update_message = AsyncMock()
    mock_tg.send_notification = AsyncMock()

    with patch("app.routers.webhooks._get_telegram_client", return_value=mock_tg):
        payload = _make_callback_payload("approve", content_id)
        response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True

    # Verify DB was updated
    db.refresh(item)
    assert item.approval_status == "approved"
    assert item.status == ContentStatus.APPROVED.value
    assert item.approved_by == "testuser"


def test_webhook_reject_updates_status(client):
    """Reject callback should set status to 'rejected'."""
    from app.database import get_db

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)

    item = _create_content_item(db)
    content_id = item.id

    mock_tg = AsyncMock()
    mock_tg.update_message = AsyncMock()
    mock_tg.send_notification = AsyncMock()

    with patch("app.routers.webhooks._get_telegram_client", return_value=mock_tg):
        payload = _make_callback_payload("reject", content_id)
        response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200

    db.refresh(item)
    assert item.approval_status == "rejected"
    assert item.status == ContentStatus.REJECTED.value
