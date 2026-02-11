"""Base HTTP client with retry logic for all external API integrations."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.utils.logging_config import get_logger

logger = get_logger("integrations.base_client")


def _is_retryable(exc: BaseException) -> bool:
    """Return True for exceptions that should trigger a retry."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


class BaseAPIClient:
    """Async HTTP client with automatic retries and rate-limit awareness.

    All API integration clients should inherit from this class to get
    consistent timeout, retry, and logging behaviour.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = headers or {}
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the underlying ``httpx.AsyncClient``."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
                headers=self._headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client if it is open."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request with retries
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=32),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Send an HTTP request with automatic retries and logging.

        Parameters
        ----------
        method:
            HTTP verb (``GET``, ``POST``, ``PUT``, ``DELETE``, ...).
        path:
            URL path relative to ``base_url`` (e.g. ``/v1/videos``).
        **kwargs:
            Forwarded to ``httpx.AsyncClient.request`` (``json``, ``params``,
            ``data``, ``headers``, ``files``, etc.).

        Returns
        -------
        dict
            Parsed JSON body of the response.

        Raises
        ------
        httpx.HTTPStatusError
            On 4xx/5xx responses (5xx will be retried first).
        httpx.TimeoutException
            When the request times out after exhausting retries.
        """
        client = self._get_client()

        logger.info("HTTP %s %s%s", method.upper(), self._base_url, path)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Request kwargs: %s", kwargs)

        response = await client.request(method, path, **kwargs)

        logger.info(
            "HTTP %s %s%s -> %s",
            method.upper(),
            self._base_url,
            path,
            response.status_code,
        )

        # ------ Rate-limit awareness ------
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 5
            logger.warning(
                "Rate-limited (429). Waiting %s seconds before retry.", wait_seconds
            )
            await asyncio.sleep(wait_seconds)
            # Raise so tenacity triggers the retry
            response.raise_for_status()

        # ------ Raise on server errors so tenacity can retry ------
        response.raise_for_status()

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Response body: %.500s", response.text)

        return response.json()

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    async def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return await self._request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return await self._request("DELETE", path, **kwargs)
