"""Ravelry API client.

The client sits behind the PatternProvider interface so the basic read-only
auth used for the MVP can be swapped for OAuth later (when users link their
own Ravelry accounts) without touching the API layer.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PatternSummary(BaseModel):
    """Search-result metadata only — never pattern content, per Ravelry API terms."""

    id: int
    name: str
    designer: str | None = None
    permalink: str | None = None
    ravelry_url: str | None = None
    photo_url: str | None = None
    free: bool | None = None


class PatternSearchResult(BaseModel):
    query: str
    patterns: list[PatternSummary]
    total: int | None = None


class RavelryError(Exception):
    """Base error for Ravelry API failures."""


class RavelryUnavailableError(RavelryError):
    """Ravelry could not be reached or returned a server error."""


class RavelryRateLimitError(RavelryError):
    """Ravelry returned a 429 rate-limit response."""


class RavelryAuthError(RavelryError):
    """Credentials missing or rejected by Ravelry."""


class PatternProvider(ABC):
    """Interface boundary for pattern search providers (swappable auth/backends)."""

    @abstractmethod
    async def search_patterns(self, query: str, page_size: int = 20) -> PatternSearchResult: ...


class RavelryClient(PatternProvider):
    """Ravelry pattern provider using basic read-only auth."""

    def __init__(self, username: str, password: str, base_url: str = "https://api.ravelry.com") -> None:
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")

    async def search_patterns(self, query: str, page_size: int = 20) -> PatternSearchResult:
        if not self._username or not self._password:
            raise RavelryAuthError(
                "Ravelry credentials are not configured. "
                "Set RAVELRY_USERNAME and RAVELRY_PASSWORD in .env."
            )

        url = f"{self._base_url}/patterns/search.json"
        params = {"query": query, "page_size": page_size}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url, params=params, auth=(self._username, self._password)
                )
        except httpx.HTTPError as exc:
            logger.error("Ravelry request failed: %s", exc)
            raise RavelryUnavailableError("Could not reach the Ravelry API.") from exc

        if response.status_code == 401:
            raise RavelryAuthError("Ravelry rejected the configured credentials.")
        if response.status_code == 429:
            raise RavelryRateLimitError("Ravelry rate limit exceeded. Try again shortly.")
        if response.status_code >= 500:
            raise RavelryUnavailableError(f"Ravelry returned a server error ({response.status_code}).")
        if response.status_code != 200:
            raise RavelryError(f"Unexpected Ravelry response ({response.status_code}).")

        return self.parse_search_response(query, response.json())

    @staticmethod
    def parse_search_response(query: str, payload: dict[str, Any]) -> PatternSearchResult:
        patterns = []
        for raw in payload.get("patterns", []):
            permalink = raw.get("permalink")
            first_photo = raw.get("first_photo") or {}
            patterns.append(
                PatternSummary(
                    id=raw["id"],
                    name=raw.get("name", "Untitled"),
                    designer=(raw.get("designer") or {}).get("name"),
                    permalink=permalink,
                    ravelry_url=f"https://www.ravelry.com/patterns/library/{permalink}" if permalink else None,
                    photo_url=first_photo.get("small_url") or first_photo.get("square_url"),
                    free=raw.get("free"),
                )
            )

        total = (payload.get("paginator") or {}).get("results")
        return PatternSearchResult(query=query, patterns=patterns, total=total)
