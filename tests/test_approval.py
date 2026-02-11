"""Tests for in-dashboard approval routes."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models.bot import Bot
from app.models.content import ContentItem, ContentStatus


@pytest.fixture
def client():
    return TestClient(app)


def _get_db():
    from app.database import get_db
    db_gen = app.dependency_overrides[get_db]()
    return next(db_gen)


def _create_bot_and_content(db, status=ContentStatus.PENDING_APPROVAL.value):
    bot = Bot(name="ApprovalBot", slug="approvalbot", niche="tech")
    db.add(bot)
    db.commit()

    item = ContentItem(
        bot_id=bot.id,
        status=status,
        approval_status="pending",
        trend_topic="AI tips",
        description_instagram="IG desc",
        description_youtube="YT desc",
        description_tiktok="TT desc",
        video_file_path="/tmp/video.mp4",
    )
    db.add(item)
    db.commit()
    return bot, item


def test_approve_updates_descriptions_and_publishes(client):
    """POST approve should update descriptions and trigger publishing."""
    db = _get_db()
    bot, item = _create_bot_and_content(db)

    with patch("app.services.pipeline_orchestrator.resume_after_approval", new_callable=AsyncMock) as mock_pub:
        resp = client.post(
            f"/bots/{bot.slug}/content/{item.id}/approve",
            data={
                "description_instagram": "Updated IG",
                "description_youtube": "Updated YT",
                "description_tiktok": "Updated TT",
            },
        )

    assert resp.status_code == 200
    assert "aprobado" in resp.text.lower()
    mock_pub.assert_called_once()

    db.refresh(item)
    assert item.approval_status == "approved"
    assert item.description_instagram == "Updated IG"
    assert item.description_youtube == "Updated YT"


def test_reject_updates_status(client):
    """POST reject should mark content as rejected."""
    db = _get_db()
    bot, item = _create_bot_and_content(db)

    resp = client.post(f"/bots/{bot.slug}/content/{item.id}/reject")

    assert resp.status_code == 200
    assert "rechazado" in resp.text.lower()

    db.refresh(item)
    assert item.approval_status == "rejected"
    assert item.status == ContentStatus.REJECTED.value


def test_approve_404_nonexistent_content(client):
    """POST approve for nonexistent content returns 404."""
    db = _get_db()
    bot = Bot(name="Bot404", slug="bot404", niche="test")
    db.add(bot)
    db.commit()

    resp = client.post(f"/bots/{bot.slug}/content/99999/approve")
    assert resp.status_code == 404


def test_reject_404_nonexistent_bot(client):
    """POST reject for nonexistent bot returns 404."""
    resp = client.post("/bots/nonexistent/content/1/reject")
    assert resp.status_code == 404
