"""Turn an address (or listing URL) into a valuation.

Three functions, one job each:

* ``fetch_valuation``   — talk to Domain.com.au
* ``estimate_valuation`` — the fallback, and it says so
* ``get_valuation``     — try the provider, degrade honestly if it is down

The provenance string records **what actually produced the number**. A fallback
that impersonates a real provider is worse than no fallback, because it is
silently wrong and it looks authoritative.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.domain_client import (
    DomainAuthError,
    DomainClient,
    DomainError,
    DomainNotFoundError,
    DomainUnavailableError,
    to_money,
)

logger = logging.getLogger(__name__)

PROVENANCE_AVM = "Domain.com.au AVM"
PROVENANCE_ESTIMATE = "algorithmic estimate (5% uplift — NOT an AVM)"

#: The share by which the fallback inflates the purchase price.
FALLBACK_UPLIFT = Decimal("0.05")

#: ``https://www.domain.com.au/property-profile/<slug>-12345678``
_DOMAIN_URL_ID = re.compile(r"property-profile/.*?-(\d+)\s*$")


class ProviderUnavailableError(Exception):
    """The valuation provider could not produce a number and fallback is off."""


@dataclass(frozen=True)
class ValuationResult:
    """The outcome of a valuation, and where it came from."""

    name: str
    current_value: Decimal
    provenance_source: str
    last_sold_date: date | None = None
    current_rent: Decimal | None = None
    source_url: str | None = None
    domain_property_id: str | None = None


class PropertyService:
    """Valuation orchestration. Blocking by design — call from a ``def`` route."""

    def __init__(
        self,
        client: DomainClient | None = None,
        allow_estimate_fallback: bool = True,
    ) -> None:
        self._client = client
        self.allow_estimate_fallback = allow_estimate_fallback

    # -- public API -------------------------------------------------------

    def get_valuation(self, query: str, purchase_price: Decimal) -> ValuationResult:
        """Provider first, honest fallback second."""
        if self._client is None:
            logger.warning(
                "No Domain API credentials configured — serving an algorithmic estimate."
            )
            return self.estimate_valuation(query, purchase_price)

        try:
            return self.fetch_valuation(query, purchase_price)
        except DomainError as exc:
            # Covers unreachable, rejected credentials, unknown address and a
            # malformed provider payload alike. Any of them means we do not
            # have a number we can attribute — so we must not invent one.
            if not self.allow_estimate_fallback:
                raise ProviderUnavailableError(str(exc)) from exc
            logger.warning("Domain valuation failed (%s) — falling back to an estimate.", exc)
            return self.estimate_valuation(query, purchase_price)

    def fetch_valuation(self, query: str, purchase_price: Decimal) -> ValuationResult:
        """Resolve the address on Domain and read its AVM, rent and sale history."""
        if self._client is None:
            raise DomainUnavailableError("No Domain API credentials configured.")

        client = self._client
        property_id = self._resolve_property_id(client, query)

        # The price estimate is the one call we cannot do without.
        estimate = client.get_price_estimate(property_id)
        current_value = to_money(estimate.get("midPrice"))
        if current_value is None:
            current_value = to_money(estimate.get("upperPrice")) or to_money(
                estimate.get("lowerPrice")
            )
        if current_value is None:
            raise DomainError(
                f"Domain returned a price estimate for {property_id} with no usable price."
            )

        # The remaining calls enrich the response but are not load-bearing.
        details: dict[str, Any] = {}
        try:
            details = client.get_property(property_id)
        except DomainError as exc:
            logger.info("Property details unavailable for %s: %s", property_id, exc)

        rent: Decimal | None = None
        try:
            rental = client.get_rental_estimate(property_id)
            rent = to_money(rental.get("weeklyRentEstimate"))
        except DomainError as exc:
            logger.info("Rental estimate unavailable for %s: %s", property_id, exc)

        name = self._resolved_name(details, query)
        last_sold = self._last_sold_date(details)
        source_url = self._source_url(details, name)

        return ValuationResult(
            name=name,
            current_value=current_value,
            provenance_source=PROVENANCE_AVM,
            last_sold_date=last_sold,
            current_rent=rent,
            source_url=source_url,
            domain_property_id=property_id,
        )

    def estimate_valuation(self, query: str, purchase_price: Decimal) -> ValuationResult:
        """The fallback. It is a guess, and it says so."""
        current_value = (purchase_price * (Decimal("1") + FALLBACK_UPLIFT)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return ValuationResult(
            name=query.strip(),
            current_value=current_value,
            provenance_source=PROVENANCE_ESTIMATE,
            last_sold_date=None,
            current_rent=None,
            source_url=None,
            domain_property_id=None,
        )

    # -- helpers ----------------------------------------------------------

    def _resolve_property_id(self, client: DomainClient, query: str) -> str:
        """Find the Domain property id for ``query``.

        A Domain listing URL carries the id already; otherwise we ask Domain's
        address suggestion endpoint and take its best match.
        """
        from_url = self._property_id_from_url(query)
        if from_url:
            return from_url

        candidates = client.suggest_addresses(query)
        if not candidates:
            raise DomainNotFoundError(f"No Domain address matches {query!r}.")

        best = max(candidates, key=lambda c: c.get("relativeScore") or 0)
        property_id = best.get("id")
        if not property_id:
            raise DomainNotFoundError(f"Domain suggested no usable id for {query!r}.")
        return str(property_id)

    @staticmethod
    def _property_id_from_url(query: str) -> str | None:
        match = _DOMAIN_URL_ID.search(query.strip())
        return match.group(1) if match else None

    @staticmethod
    def _resolved_name(details: dict[str, Any], fallback: str) -> str:
        """The address Domain resolved — not the raw user input."""
        address = details.get("address")
        if isinstance(address, str) and address.strip():
            return address.strip()
        return fallback.strip()

    @staticmethod
    def _last_sold_date(details: dict[str, Any]) -> date | None:
        """The most recent sale date from Domain's sale history."""
        history = details.get("history")
        if not isinstance(history, dict):
            return None
        sales = history.get("sales")
        if not isinstance(sales, list):
            return None

        dates: list[date] = []
        for sale in sales:
            if not isinstance(sale, dict):
                continue
            raw = sale.get("date")
            if not isinstance(raw, str):
                continue
            try:
                dates.append(datetime.strptime(raw[:10], "%Y-%m-%d").date())
            except ValueError:
                continue
        return max(dates) if dates else None

    @staticmethod
    def _source_url(details: dict[str, Any], name: str) -> str:
        canonical = details.get("canonicalUrl")
        if isinstance(canonical, str) and canonical.strip():
            return canonical.strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return f"https://www.domain.com.au/property-profile/{slug}"
