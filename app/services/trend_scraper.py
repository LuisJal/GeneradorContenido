"""Service for discovering trending topics from Google Trends and Reddit."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import feedparser
import httpx
from sqlalchemy.orm import Session

from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def scrape_google_trends(
    niche: str,
    language: str = "es",
    geo: str = "ES",
) -> List[str]:
    """Fetch trending topics from Google Trends RSS feed and filter by niche.

    Args:
        niche: The niche/keyword to filter trends by relevance.
        language: Language code for the trends (default: ``"es"``).
        geo: Geographic region code (default: ``"ES"``).

    Returns:
        A list of up to 10 trending topic strings relevant to the niche.
    """
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    logger.info("Fetching Google Trends RSS feed for geo=%s niche=%s", geo, niche)

    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.error("Failed to parse Google Trends RSS feed: %s", exc)
        return []

    if not feed.entries:
        logger.warning("No entries found in Google Trends feed for geo=%s", geo)
        return []

    niche_lower = niche.lower()
    niche_keywords = [kw.strip() for kw in niche_lower.split() if kw.strip()]

    topics: List[str] = []
    for entry in feed.entries:
        title: str = entry.get("title", "")
        if not title:
            continue

        title_lower = title.lower()
        is_relevant = any(kw in title_lower for kw in niche_keywords)

        if is_relevant:
            topics.append(title.strip())

        if len(topics) >= 10:
            break

    # If strict filtering yields too few results, include unfiltered entries as
    # a fallback so the caller always has something to work with.
    if len(topics) < 3:
        logger.debug(
            "Only %d niche-matched topics found; padding with general trends",
            len(topics),
        )
        seen = set(t.lower() for t in topics)
        for entry in feed.entries:
            title = entry.get("title", "")
            if not title or title.lower() in seen:
                continue
            topics.append(title.strip())
            seen.add(title.lower())
            if len(topics) >= 10:
                break

    logger.info("Google Trends returned %d topics for niche=%s", len(topics), niche)
    return topics


def scrape_reddit(subreddit: str, limit: int = 10) -> List[str]:
    """Fetch hot post titles from a Reddit subreddit via the JSON API.

    Args:
        subreddit: The subreddit name (without the ``r/`` prefix).
        limit: Maximum number of posts to retrieve (default: ``10``).

    Returns:
        A list of post title strings.
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    headers = {
        "User-Agent": "GeneradorContenido/1.0 (trend-scraper; compatible)",
    }

    logger.info("Fetching Reddit hot posts from r/%s (limit=%d)", subreddit, limit)

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Reddit API returned HTTP %s for r/%s: %s",
            exc.response.status_code,
            subreddit,
            exc,
        )
        return []
    except httpx.RequestError as exc:
        logger.error("Network error fetching Reddit r/%s: %s", subreddit, exc)
        return []

    try:
        data = response.json()
    except Exception as exc:
        logger.error("Failed to decode Reddit JSON response: %s", exc)
        return []

    posts = data.get("data", {}).get("children", [])
    topics: List[str] = []
    for post in posts:
        title: Optional[str] = post.get("data", {}).get("title")
        if title and title.strip():
            topics.append(title.strip())

    logger.info("Reddit r/%s returned %d topics", subreddit, len(topics))
    return topics


def get_trending_topics(bot: Any) -> List[str]:
    """Combine trending topics from all configured sources for a bot.

    The bot instance is expected to expose:
    * ``bot.niche`` -- the content niche (e.g. ``"fitness"``).
    * ``bot.language`` -- language code (e.g. ``"es"``).
    * ``bot.trend_sources`` -- a dict such as::

          {
              "google_trends_geo": "ES",
              "subreddits": ["fitness", "gym"]
          }

    Args:
        bot: A Bot model instance with the attributes described above.

    Returns:
        A deduplicated list of trending topic strings.
    """
    logger.info("Gathering trending topics for bot niche=%s", bot.niche)

    trend_sources: Dict[str, Any] = bot.trend_sources or {}
    geo: str = trend_sources.get("google_trends_geo", "ES")
    subreddits: List[str] = trend_sources.get("subreddits", [])

    all_topics: List[str] = []

    # --- Google Trends ---
    google_topics = scrape_google_trends(
        niche=bot.niche,
        language=getattr(bot, "language", "es"),
        geo=geo,
    )
    all_topics.extend(google_topics)

    # --- Reddit ---
    for subreddit in subreddits:
        reddit_topics = scrape_reddit(subreddit=subreddit)
        all_topics.extend(reddit_topics)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_topics: List[str] = []
    for topic in all_topics:
        normalised = topic.lower().strip()
        if normalised not in seen:
            seen.add(normalised)
            unique_topics.append(topic)

    logger.info(
        "Total unique trending topics for bot niche=%s: %d",
        bot.niche,
        len(unique_topics),
    )
    return unique_topics


def select_unused_topic(
    bot: Any,
    db: Session,
    topics: List[str],
) -> str:
    """Pick the first topic that the bot has not previously used.

    Checks existing ``ContentItem`` records linked to the bot and returns the
    first topic from *topics* whose value has not been stored as
    ``trend_topic`` before.  If every topic has already been used the function
    cycles back to the first entry so the caller always receives a usable
    value.

    Args:
        bot: A Bot model instance (must expose ``bot.id``).
        db: An active SQLAlchemy database session.
        topics: Candidate trending topic strings to choose from.

    Returns:
        A single topic string.  Returns ``""`` only when *topics* is empty.
    """
    if not topics:
        logger.warning("select_unused_topic called with an empty topics list")
        return ""

    try:
        from app.models.content import ContentItem

        used_topics_query = (
            db.query(ContentItem.trend_topic)
            .filter(
                ContentItem.bot_id == bot.id,
                ContentItem.trend_topic.isnot(None),
            )
            .all()
        )
        used_topics: set[str] = {
            row[0].lower().strip() for row in used_topics_query if row[0]
        }
    except Exception as exc:
        logger.error("Error querying used topics from database: %s", exc)
        used_topics = set()

    for topic in topics:
        if topic.lower().strip() not in used_topics:
            logger.info("Selected unused topic: %s", topic)
            return topic

    # All topics have been used -- cycle back to the first one.
    logger.info(
        "All %d topics already used for bot id=%s; cycling to first topic",
        len(topics),
        bot.id,
    )
    return topics[0]
