"""Tests for the trend scraper service."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.trend_scraper import (
    get_trending_topics,
    scrape_google_trends,
    scrape_reddit,
    select_unused_topic,
)


# ------------------------------------------------------------------
# scrape_google_trends
# ------------------------------------------------------------------


class TestGoogleTrends:
    def test_returns_matching_topics(self):
        """Should return topics matching niche keywords."""
        fake_entries = [
            {"title": "Fitness workout tips 2025"},
            {"title": "Elections news today"},
            {"title": "New fitness tracker released"},
            {"title": "Weather forecast"},
        ]
        fake_feed = MagicMock()
        fake_feed.entries = fake_entries

        with patch("app.services.trend_scraper.feedparser.parse", return_value=fake_feed):
            topics = scrape_google_trends("fitness")

        # Should match "fitness" entries + pad with general ones
        assert any("fitness" in t.lower() for t in topics)

    def test_fallback_on_few_matches(self):
        """When fewer than 3 niche matches, pads with general trends."""
        fake_entries = [
            {"title": "Only one tech match"},
            {"title": "Sports news"},
            {"title": "Movie releases"},
            {"title": "Concert tickets"},
        ]
        fake_feed = MagicMock()
        fake_feed.entries = fake_entries

        with patch("app.services.trend_scraper.feedparser.parse", return_value=fake_feed):
            topics = scrape_google_trends("tech")

        # Should have the niche match + padded general entries
        assert len(topics) >= 3

    def test_empty_feed(self):
        fake_feed = MagicMock()
        fake_feed.entries = []

        with patch("app.services.trend_scraper.feedparser.parse", return_value=fake_feed):
            topics = scrape_google_trends("fitness")

        assert topics == []

    def test_parse_error(self):
        with patch("app.services.trend_scraper.feedparser.parse", side_effect=Exception("boom")):
            topics = scrape_google_trends("fitness")

        assert topics == []


# ------------------------------------------------------------------
# scrape_reddit
# ------------------------------------------------------------------


class TestReddit:
    def test_returns_post_titles(self):
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "data": {
                "children": [
                    {"data": {"title": "Post 1"}},
                    {"data": {"title": "Post 2"}},
                    {"data": {"title": ""}},  # empty, should be skipped
                ]
            }
        }
        fake_response.raise_for_status = MagicMock()

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get.return_value = fake_response
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_reddit("fitness")

        assert topics == ["Post 1", "Post 2"]

    def test_http_error(self):
        import httpx

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_instance.get.return_value = mock_response
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "rate limit", request=MagicMock(), response=mock_response
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_reddit("fitness")

        assert topics == []

    def test_network_error(self):
        import httpx

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get.side_effect = httpx.RequestError("timeout")
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_reddit("fitness")

        assert topics == []


# ------------------------------------------------------------------
# get_trending_topics
# ------------------------------------------------------------------


class TestGetTrendingTopics:
    def test_combines_sources(self):
        bot = MagicMock()
        bot.niche = "tech"
        bot.language = "es"
        bot.trend_sources = {
            "google_trends_geo": "ES",
            "subreddits": ["technology"],
        }

        with patch("app.services.trend_scraper.scrape_google_trends", return_value=["AI news"]):
            with patch("app.services.trend_scraper.scrape_reddit", return_value=["Robot news"]):
                topics = get_trending_topics(bot)

        assert "AI news" in topics
        assert "Robot news" in topics

    def test_deduplication(self):
        bot = MagicMock()
        bot.niche = "tech"
        bot.language = "es"
        bot.trend_sources = {"subreddits": ["tech"]}

        with patch("app.services.trend_scraper.scrape_google_trends", return_value=["AI News"]):
            with patch("app.services.trend_scraper.scrape_reddit", return_value=["ai news"]):
                topics = get_trending_topics(bot)

        # "AI News" and "ai news" are duplicates (case insensitive)
        assert len(topics) == 1
        assert topics[0] == "AI News"  # first one wins

    def test_no_sources(self):
        bot = MagicMock()
        bot.niche = "tech"
        bot.language = "es"
        bot.trend_sources = None

        with patch("app.services.trend_scraper.scrape_google_trends", return_value=[]):
            topics = get_trending_topics(bot)

        assert topics == []


# ------------------------------------------------------------------
# select_unused_topic
# ------------------------------------------------------------------


class TestSelectUnusedTopic:
    def test_picks_unused(self):
        """Should skip topics already used by the bot."""
        bot = MagicMock()
        bot.id = 1
        db = MagicMock()

        # Simulate DB returning one used topic
        db.query.return_value.filter.return_value.all.return_value = [
            ("AI News",),
        ]

        result = select_unused_topic(bot, db, ["AI News", "Robot Trends", "Space"])
        assert result == "Robot Trends"

    def test_cycles_when_all_used(self):
        """When all topics are used, returns the first one."""
        bot = MagicMock()
        bot.id = 1
        db = MagicMock()

        db.query.return_value.filter.return_value.all.return_value = [
            ("Topic A",),
            ("Topic B",),
        ]

        result = select_unused_topic(bot, db, ["Topic A", "Topic B"])
        assert result == "Topic A"

    def test_empty_topics(self):
        bot = MagicMock()
        bot.id = 1
        db = MagicMock()

        result = select_unused_topic(bot, db, [])
        assert result == ""

    def test_db_error_fallback(self):
        """On DB error, still returns a topic (no filtering)."""
        bot = MagicMock()
        bot.id = 1
        db = MagicMock()
        db.query.side_effect = Exception("DB error")

        result = select_unused_topic(bot, db, ["Topic A", "Topic B"])
        assert result == "Topic A"
