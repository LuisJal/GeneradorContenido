"""Tests for the trend scraper service."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.trend_scraper import (
    get_trending_topics,
    scrape_football_data,
    scrape_gnews,
    scrape_google_trends,
    scrape_reddit,
    scrape_rss_feeds,
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


# ------------------------------------------------------------------
# scrape_rss_feeds
# ------------------------------------------------------------------


class TestRSSFeeds:
    def test_returns_article_titles(self):
        """Should parse RSS feed entries and extract titles."""
        fake_feed = MagicMock()
        fake_feed.entries = [
            {"title": "Mbappé marca un hat-trick"},
            {"title": "Ancelotti elogia a Bellingham"},
            {"title": ""},  # empty → skip
        ]

        with patch("app.services.trend_scraper.feedparser.parse", return_value=fake_feed):
            topics = scrape_rss_feeds(["https://marca.com/rss"])

        assert topics == ["Mbappé marca un hat-trick", "Ancelotti elogia a Bellingham"]

    def test_multiple_feeds(self):
        """Should combine titles from multiple RSS feeds."""
        feed_marca = MagicMock()
        feed_marca.entries = [{"title": "Noticia de Marca"}]

        feed_as = MagicMock()
        feed_as.entries = [{"title": "Noticia de AS"}]

        def parse_side_effect(url):
            if "marca" in url:
                return feed_marca
            return feed_as

        with patch(
            "app.services.trend_scraper.feedparser.parse",
            side_effect=parse_side_effect,
        ):
            topics = scrape_rss_feeds(
                ["https://marca.com/rss", "https://as.com/rss"]
            )

        assert len(topics) == 2
        assert "Noticia de Marca" in topics
        assert "Noticia de AS" in topics

    def test_parse_error_continues(self):
        """On parse error, should log and return empty list."""
        with patch(
            "app.services.trend_scraper.feedparser.parse",
            side_effect=Exception("boom"),
        ):
            topics = scrape_rss_feeds(["https://bad-feed.com"])

        assert topics == []

    def test_empty_feed(self):
        """Should handle feeds with zero entries."""
        fake_feed = MagicMock()
        fake_feed.entries = []

        with patch("app.services.trend_scraper.feedparser.parse", return_value=fake_feed):
            topics = scrape_rss_feeds(["https://empty-feed.com"])

        assert topics == []

    def test_respects_limit(self):
        """Should respect the per-feed limit parameter."""
        fake_feed = MagicMock()
        fake_feed.entries = [{"title": f"Article {i}"} for i in range(20)]

        with patch("app.services.trend_scraper.feedparser.parse", return_value=fake_feed):
            topics = scrape_rss_feeds(["https://marca.com/rss"], limit=5)

        assert len(topics) == 5


# ------------------------------------------------------------------
# scrape_football_data
# ------------------------------------------------------------------


class TestFootballData:
    def test_formats_finished_and_scheduled(self):
        """Should format finished matches with scores and scheduled with date."""
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "matches": [
                {
                    "status": "FINISHED",
                    "homeTeam": {"name": "Real Madrid"},
                    "awayTeam": {"name": "Barcelona"},
                    "score": {"fullTime": {"home": 3, "away": 1}},
                    "competition": {"name": "La Liga"},
                    "matchday": 15,
                },
                {
                    "status": "SCHEDULED",
                    "homeTeam": {"name": "Real Madrid"},
                    "awayTeam": {"name": "Atlético"},
                    "utcDate": "2025-02-15T20:00:00Z",
                },
            ]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get.return_value = fake_response
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_football_data(team_id=86, api_key="test-key")

        assert len(topics) == 2
        assert "Real Madrid 3-1 Barcelona" in topics[0]
        assert "La Liga" in topics[0]
        assert "Jornada 15" in topics[0]
        assert "Próximo partido: Real Madrid vs Atlético" in topics[1]

    def test_missing_api_key(self):
        """Should return empty list when no API key is provided."""
        topics = scrape_football_data(team_id=86, api_key=None)
        assert topics == []

    def test_http_error(self):
        """Should handle HTTP errors gracefully."""
        import httpx

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Unauthorized", request=MagicMock(), response=mock_response
            )
            mock_instance.get.return_value = mock_response
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_football_data(team_id=86, api_key="bad-key")

        assert topics == []

    def test_network_error(self):
        """Should handle network timeouts."""
        import httpx

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get.side_effect = httpx.RequestError("timeout")
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_football_data(team_id=86, api_key="test-key")

        assert topics == []


# ------------------------------------------------------------------
# scrape_gnews
# ------------------------------------------------------------------


class TestGNews:
    def test_returns_article_titles(self):
        """Should extract article titles from GNews response."""
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "articles": [
                {"title": "Mbappé anota un hat-trick"},
                {"title": "Real Madrid gana 3-1"},
                {"title": ""},  # empty → skip
            ]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get.return_value = fake_response
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_gnews(query="real madrid", api_key="test-key")

        assert len(topics) == 2
        assert "Mbappé anota un hat-trick" in topics
        assert "Real Madrid gana 3-1" in topics

    def test_missing_api_key(self):
        """Should return empty list when no API key is provided."""
        topics = scrape_gnews(query="real madrid", api_key=None)
        assert topics == []

    def test_quota_exceeded_403(self):
        """Should handle 403 (daily quota exceeded) gracefully."""
        import httpx

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Forbidden", request=MagicMock(), response=mock_response
            )
            mock_instance.get.return_value = mock_response
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_gnews(query="real madrid", api_key="test-key")

        assert topics == []

    def test_http_error(self):
        """Should handle generic HTTP errors."""
        import httpx

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error", request=MagicMock(), response=mock_response
            )
            mock_instance.get.return_value = mock_response
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_gnews(query="real madrid", api_key="test-key")

        assert topics == []

    def test_network_error(self):
        """Should handle network errors."""
        import httpx

        with patch("app.services.trend_scraper.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get.side_effect = httpx.RequestError("timeout")
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_instance

            topics = scrape_gnews(query="real madrid", api_key="test-key")

        assert topics == []


# ------------------------------------------------------------------
# get_trending_topics -- all sources combined
# ------------------------------------------------------------------


class TestGetTrendingTopicsAllSources:
    def test_combines_all_five_sources(self):
        """Should combine Google Trends + Reddit + RSS + Football-Data + GNews."""
        bot = MagicMock()
        bot.niche = "real-madrid"
        bot.language = "es"
        bot.trend_sources = {
            "google_trends_geo": "ES",
            "subreddits": ["realmadrid"],
            "rss_feeds": ["https://marca.com/rss"],
            "football_data": {"enabled": True, "team_id": 86},
            "gnews": {"enabled": True, "query": "real madrid"},
        }

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch(
            "app.services.trend_scraper.scrape_google_trends",
            return_value=["Google Trend"],
        ), patch(
            "app.services.trend_scraper.scrape_reddit",
            return_value=["Reddit Post"],
        ), patch(
            "app.services.trend_scraper.scrape_rss_feeds",
            return_value=["RSS Article"],
        ), patch(
            "app.services.trend_scraper.scrape_football_data",
            return_value=["Match Result"],
        ), patch(
            "app.services.trend_scraper.scrape_gnews",
            return_value=["GNews Headline"],
        ), patch(
            "app.database.sync_engine", create=True,
        ), patch(
            "app.services.settings_manager.get_setting",
            return_value="fake-key",
        ), patch(
            "sqlalchemy.orm.Session",
            return_value=mock_session,
        ):
            topics = get_trending_topics(bot)

        assert len(topics) == 5
        assert "Google Trend" in topics
        assert "Reddit Post" in topics
        assert "RSS Article" in topics
        assert "Match Result" in topics
        assert "GNews Headline" in topics

    def test_works_without_optional_sources(self):
        """Should work when football_data/gnews are not enabled."""
        bot = MagicMock()
        bot.niche = "real-madrid"
        bot.language = "es"
        bot.trend_sources = {
            "google_trends_geo": "ES",
            "subreddits": ["realmadrid"],
            "rss_feeds": ["https://marca.com/rss"],
        }

        with patch(
            "app.services.trend_scraper.scrape_google_trends",
            return_value=["Trend"],
        ), patch(
            "app.services.trend_scraper.scrape_reddit",
            return_value=["Post"],
        ), patch(
            "app.services.trend_scraper.scrape_rss_feeds",
            return_value=["Article"],
        ):
            topics = get_trending_topics(bot)

        assert len(topics) == 3
        assert "Trend" in topics
        assert "Post" in topics
        assert "Article" in topics
