"""Service for discovering trending topics from multiple news sources.

Supported sources: Google Trends RSS, Reddit, custom RSS feeds,
Football-Data.org (match results/fixtures), and GNews (news articles).
"""

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


def scrape_rss_feeds(feed_urls: List[str], limit: int = 10) -> List[str]:
    """Fetch recent article titles from a list of RSS feed URLs.

    Args:
        feed_urls: RSS feed URLs to parse (e.g. Marca, AS sport feeds).
        limit: Maximum number of articles to extract per feed (default: ``10``).

    Returns:
        Combined list of article title strings from all feeds.
    """
    logger.info("Fetching RSS feeds from %d sources", len(feed_urls))

    all_titles: List[str] = []

    for url in feed_urls:
        try:
            feed = feedparser.parse(url)

            if not feed.entries:
                logger.warning("No entries found in RSS feed: %s", url)
                continue

            for entry in feed.entries[:limit]:
                title: str = entry.get("title", "")
                if title and title.strip():
                    all_titles.append(title.strip())

        except Exception as exc:
            logger.error("Failed to parse RSS feed %s: %s", url, exc)
            continue

    logger.info("RSS feeds returned %d total articles", len(all_titles))
    return all_titles


def scrape_football_data(
    team_id: int = 86,
    api_key: Optional[str] = None,
    limit: int = 5,
) -> List[str]:
    """Fetch recent and upcoming match info from Football-Data.org API.

    Args:
        team_id: Football-Data.org team ID (``86`` = Real Madrid).
        api_key: API key for Football-Data.org (free tier: 10 req/min).
            If ``None``, returns an empty list.
        limit: Maximum number of matches to fetch (default: ``5``).

    Returns:
        Topic strings such as ``"Real Madrid 3-1 Barcelona (La Liga, Jornada 15)"``
        or ``"Próximo partido: Real Madrid vs Atlético (Saturday 20:00)"``.
    """
    if not api_key:
        logger.warning("Football-Data.org API key not configured; skipping")
        return []

    url = f"https://api.football-data.org/v4/teams/{team_id}/matches"
    params = {"status": "FINISHED,SCHEDULED", "limit": limit}
    headers = {"X-Auth-Token": api_key}

    logger.info("Fetching Football-Data.org matches for team_id=%d", team_id)

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Football-Data.org API returned HTTP %s: %s",
            exc.response.status_code,
            exc,
        )
        return []
    except httpx.RequestError as exc:
        logger.error("Network error fetching Football-Data.org: %s", exc)
        return []

    try:
        data = response.json()
    except Exception as exc:
        logger.error("Failed to decode Football-Data.org JSON: %s", exc)
        return []

    matches = data.get("matches", [])
    topics: List[str] = []

    for match in matches:
        status = match.get("status")
        home = match.get("homeTeam", {}).get("name", "")
        away = match.get("awayTeam", {}).get("name", "")
        competition = match.get("competition", {}).get("name", "")
        matchday = match.get("matchday")

        if status == "FINISHED":
            score = match.get("score", {}).get("fullTime", {})
            home_goals = score.get("home")
            away_goals = score.get("away")
            if home_goals is not None and away_goals is not None:
                topic = f"{home} {home_goals}-{away_goals} {away}"
                if competition and matchday:
                    topic += f" ({competition}, Jornada {matchday})"
                topics.append(topic)

        elif status == "SCHEDULED":
            utc_date = match.get("utcDate", "")
            if utc_date:
                try:
                    from datetime import datetime, timezone

                    dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
                    day_name = dt.strftime("%A")
                    time_str = dt.strftime("%H:%M")
                    topic = (
                        f"Próximo partido: {home} vs {away} ({day_name} {time_str})"
                    )
                except Exception:
                    topic = f"Próximo partido: {home} vs {away}"
            else:
                topic = f"Próximo partido: {home} vs {away}"
            topics.append(topic)

    logger.info("Football-Data.org returned %d match topics", len(topics))
    return topics


def scrape_gnews(
    query: str = "real madrid",
    api_key: Optional[str] = None,
    language: str = "es",
    limit: int = 10,
) -> List[str]:
    """Fetch news article titles from the GNews API.

    Args:
        query: Search query (default: ``"real madrid"``).
        api_key: GNews API key (free tier: 100 req/day).
            If ``None``, returns an empty list.
        language: Language code (default: ``"es"``).
        limit: Maximum articles to fetch (default: ``10``).

    Returns:
        A list of article title strings.
    """
    if not api_key:
        logger.warning("GNews API key not configured; skipping")
        return []

    url = "https://gnews.io/api/v4/search"
    params = {
        "q": query,
        "lang": language,
        "max": limit,
        "token": api_key,
    }

    logger.info("Fetching GNews articles for query='%s' lang=%s", query, language)

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 403:
            logger.warning("GNews daily quota exceeded (free tier: 100 req/day)")
        else:
            logger.error("GNews API returned HTTP %s: %s", status_code, exc)
        return []
    except httpx.RequestError as exc:
        logger.error("Network error fetching GNews: %s", exc)
        return []

    try:
        data = response.json()
    except Exception as exc:
        logger.error("Failed to decode GNews JSON: %s", exc)
        return []

    articles = data.get("articles", [])
    topics: List[str] = []

    for article in articles:
        title: Optional[str] = article.get("title")
        if title and title.strip():
            topics.append(title.strip())

    logger.info("GNews returned %d article titles", len(topics))
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

    # --- RSS Feeds ---
    rss_feeds: List[str] = trend_sources.get("rss_feeds", [])
    if rss_feeds:
        rss_topics = scrape_rss_feeds(feed_urls=rss_feeds)
        all_topics.extend(rss_topics)

    # --- Football-Data.org ---
    football_config: dict = trend_sources.get("football_data", {})
    if football_config.get("enabled", False):
        from app.database import sync_engine
        from app.services.settings_manager import get_setting

        team_id = football_config.get("team_id", 86)
        with Session(sync_engine) as sess:
            fd_api_key = get_setting(sess, "football_data_api_key")
        if fd_api_key:
            football_topics = scrape_football_data(
                team_id=team_id, api_key=fd_api_key
            )
            all_topics.extend(football_topics)

    # --- GNews ---
    gnews_config: dict = trend_sources.get("gnews", {})
    if gnews_config.get("enabled", False):
        from app.database import sync_engine
        from app.services.settings_manager import get_setting

        gnews_query = gnews_config.get("query", bot.niche)
        with Session(sync_engine) as sess:
            gn_api_key = get_setting(sess, "gnews_api_key")
        if gn_api_key:
            gnews_topics = scrape_gnews(
                query=gnews_query,
                api_key=gn_api_key,
                language=getattr(bot, "language", "es"),
            )
            all_topics.extend(gnews_topics)

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
