"""Low-level client for the Domain.com.au developer API.

Base URL:  https://api.domain.com.au
Auth:      ``x-api-key: key_...`` header (or ``Authorization: Bearer`` for
           OAuth access tokens — see ``WEALTHY_DOMAIN_AUTH_MODE``).

Every call has an explicit timeout, a bounded retry policy and a fallback.
Nothing here blocks the event loop by accident: the callers are ``def``, not
``async def``, so FastAPI runs them in a threadpool.

Endpoints used (verified against Domain's published OpenAPI 3.0.4 spec):

* ``GET /v1/properties/_suggest``            → resolve an address to a property id
* ``GET /v1/properties/{id}``                → resolved address, sale history
* ``GET /v1/properties/{id}/priceEstimate``  → AVM value (mid / low / high)
* ``GET /v1/properties/{id}/rentalEstimate`` → weekly rent estimate
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

MONEY = Decimal("0.01")


class DomainError(Exception):
    """Base class for every Domain API failure."""


class DomainUnavailableError(DomainError):
    """The provider could not be reached, timed out, or returned 5xx."""


class DomainAuthError(DomainError):
    """The API key is missing, rejected, or lacks the required scope (401/403)."""


class DomainNotFoundError(DomainError):
    """Domain has no record matching the request (404)."""


def to_money(value: Any) -> Decimal | None:
    """Coerce a provider number into an exact 2dp ``Decimal``.

    ``float`` → ``Decimal`` must go through ``str``; converting the binary
    representation directly would import its rounding error.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (ArithmeticError, ValueError):
        logger.warning("Could not coerce %r into a Decimal", value)
        return None


class DomainClient:
    """A thin, synchronous wrapper over the Domain.com.au REST API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.domain.com.au",
        timeout: float = 10.0,
        connect_timeout: float = 3.05,
        retries: int = 2,
        backoff_factor: float = 0.5,
        auth_mode: str = "api_key",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout, timeout)
        self.auth_mode = auth_mode

        self._session = requests.Session()
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # -- plumbing ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.auth_mode == "bearer":
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["x-api-key"] = self.api_key
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.get(
                url, params=params, headers=self._headers(), timeout=self.timeout
            )
        except requests.exceptions.Timeout as exc:
            raise DomainUnavailableError(f"Domain API timed out: {url}") from exc
        except requests.exceptions.RequestException as exc:
            raise DomainUnavailableError(f"Domain API unreachable: {url} ({exc})") from exc

        if response.status_code in (401, 403):
            raise DomainAuthError(
                f"Domain API rejected the credentials ({response.status_code}) for {path}. "
                "Check WEALTHY_DOMAIN_API_KEY and the API package granted to the project."
            )
        if response.status_code == 404:
            raise DomainNotFoundError(f"Domain API has no record for {path}.")
        if response.status_code >= 500:
            raise DomainUnavailableError(
                f"Domain API returned {response.status_code} for {path}."
            )
        if response.status_code >= 400:
            raise DomainError(
                f"Domain API returned {response.status_code} for {path}: "
                f"{response.text[:200]}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise DomainError(f"Domain API returned a non-JSON body for {path}.") from exc

    # -- endpoints --------------------------------------------------------

    def suggest_addresses(self, terms: str, page_size: int = 5) -> list[dict[str, Any]]:
        """Resolve free-text address terms into Domain property candidates.

        Returns the raw ``_suggest`` array; the caller picks the best match.
        """
        payload = self._get(
            "/v1/properties/_suggest",
            params={"terms": terms, "pageSize": page_size, "channel": "Residential"},
        )
        if not isinstance(payload, list):
            raise DomainError("Unexpected shape from /v1/properties/_suggest.")
        return payload

    def get_property(self, property_id: str) -> dict[str, Any]:
        """Full property record: resolved address, sale history, attributes."""
        payload = self._get(f"/v1/properties/{property_id}")
        if not isinstance(payload, dict):
            raise DomainError(f"Unexpected shape from /v1/properties/{property_id}.")
        return payload

    def get_price_estimate(self, property_id: str) -> dict[str, Any]:
        """The AVM: mid/lower/upper price, confidence and estimate date."""
        payload = self._get(f"/v1/properties/{property_id}/priceEstimate")
        if not isinstance(payload, dict):
            raise DomainError(
                f"Unexpected shape from /v1/properties/{property_id}/priceEstimate."
            )
        return payload

    def get_rental_estimate(self, property_id: str) -> dict[str, Any]:
        """The weekly rent estimate."""
        payload = self._get(f"/v1/properties/{property_id}/rentalEstimate")
        if not isinstance(payload, dict):
            raise DomainError(
                f"Unexpected shape from /v1/properties/{property_id}/rentalEstimate."
            )
        return payload
