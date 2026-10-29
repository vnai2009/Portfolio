"""Tests for the valuation service.

The Domain API is faked with ``responses`` — the real HTTP layer is exercised
(timeouts, retries, error mapping) without touching the network.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import responses

from app.services.domain_client import (
    DomainAuthError,
    DomainClient,
    DomainUnavailableError,
    to_money,
)
from app.services.property_service import (
    PROVENANCE_AVM,
    PROVENANCE_ESTIMATE,
    PropertyService,
)

BASE = "https://api.domain.com.au"

SUGGEST_PAYLOAD = [
    {
        "address": "25 King St, Melbourne VIC 3000",
        "id": "12345678",
        "relativeScore": 95,
        "addressComponents": {
            "streetNumber": "25",
            "streetName": "King",
            "streetType": "St",
            "suburb": "Melbourne",
            "postCode": "3000",
            "state": "VIC",
        },
    }
]

PROPERTY_PAYLOAD = {
    "id": "12345678",
    "address": "25 King St, Melbourne VIC 3000",
    "canonicalUrl": "https://www.domain.com.au/property-profile/25-king-st-melbourne-vic-3000-12345678",
    "suburb": "Melbourne",
    "postcode": "3000",
    "state": "VIC",
    "history": {
        "sales": [
            {"date": "2019-04-11", "price": 950000, "type": "auction"},
            {"date": "2022-10-15", "price": 1150000, "type": "auction"},
        ],
        "rentals": [{"date": "2023-01-01", "price": 700}],
    },
}

PRICE_ESTIMATE_PAYLOAD = {
    "date": "2026-10-01",
    "lowerPrice": 1150000,
    "midPrice": 1250000,
    "upperPrice": 1380000,
    "priceConfidence": "high",
    "source": "Domain",
    "history": [],
}

RENTAL_ESTIMATE_PAYLOAD = {
    "weeklyRentEstimate": 900,
    "percentYieldRentEstimate": 3.7,
    "rentalFsd": 900.0,
    "estimateDate": "2026-10-01",
    "propertyType": "apartment",
}


def make_client(**kwargs) -> DomainClient:
    defaults = dict(
        api_key="key_test",
        base_url=BASE,
        timeout=1.0,
        connect_timeout=1.0,
        retries=0,
    )
    defaults.update(kwargs)
    return DomainClient(**defaults)


def register_domain_mocks() -> None:
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json=SUGGEST_PAYLOAD,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678",
        json=PROPERTY_PAYLOAD,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678/priceEstimate",
        json=PRICE_ESTIMATE_PAYLOAD,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678/rentalEstimate",
        json=RENTAL_ESTIMATE_PAYLOAD,
        status=200,
    )


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


@responses.activate
def test_api_success():
    """An AVM response is mapped into a ValuationResult."""
    register_domain_mocks()
    service = PropertyService(client=make_client())

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.current_value == Decimal("1250000.00")
    assert result.provenance_source == PROVENANCE_AVM
    # The *resolved* address, not the raw input.
    assert result.name == "25 King St, Melbourne VIC 3000"
    assert result.last_sold_date == date(2022, 10, 15)
    assert result.current_rent == Decimal("900.00")
    assert result.domain_property_id == "12345678"
    assert result.source_url == PROPERTY_PAYLOAD["canonicalUrl"]


@responses.activate
def test_money_is_decimal_not_float():
    """A price of 1250000.50 must survive the round trip exactly."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json=SUGGEST_PAYLOAD,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678/priceEstimate",
        json={"midPrice": 1250000.50},
        status=200,
    )
    service = PropertyService(client=make_client())

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.current_value == Decimal("1250000.50")
    assert isinstance(result.current_value, Decimal)
    assert result.current_value + Decimal("0.50") == Decimal("1250001.00")


# ---------------------------------------------------------------------------
# The fallback
# ---------------------------------------------------------------------------


@responses.activate
def test_api_failure_falls_back():
    """A 500 from the provider degrades to the estimate."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json={"message": "boom"},
        status=500,
    )
    service = PropertyService(client=make_client(), allow_estimate_fallback=True)

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.current_value == Decimal("1050000.00")
    assert result.provenance_source == PROVENANCE_ESTIMATE


@responses.activate
def test_auth_failure_falls_back():
    """A 401 from the provider degrades to the estimate, not a crash."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json={"title": "Not Authorized"},
        status=401,
    )
    service = PropertyService(client=make_client(), allow_estimate_fallback=True)

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.provenance_source == PROVENANCE_ESTIMATE


def test_estimate_is_honest():
    """The fallback's provenance_source says it is *not* an AVM."""
    service = PropertyService(client=None)

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.provenance_source == PROVENANCE_ESTIMATE
    assert "NOT an AVM" in result.provenance_source
    assert "Domain.com.au AVM" not in result.provenance_source


@responses.activate
def test_strict_provider_raises_instead_of_degrading():
    """With fallback off, a provider failure is an error — never a fake number."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json={"message": "boom"},
        status=500,
    )
    service = PropertyService(client=make_client(), allow_estimate_fallback=False)

    with pytest.raises(DomainUnavailableError):
        service.fetch_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))


# ---------------------------------------------------------------------------
# Address resolution
# ---------------------------------------------------------------------------


def test_property_id_extracted_from_listing_url():
    """A Domain listing URL carries the property id already."""
    url = "https://www.domain.com.au/property-profile/25-king-st-melbourne-vic-3000-12345678"
    assert PropertyService._property_id_from_url(url) == "12345678"
    assert PropertyService._property_id_from_url("25 King St, Melbourne VIC 3000") is None


@responses.activate
def test_listing_url_skips_the_suggest_endpoint():
    """When the query is a listing URL, we go straight to the property."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678/priceEstimate",
        json=PRICE_ESTIMATE_PAYLOAD,
        status=200,
    )
    service = PropertyService(client=make_client())
    url = "https://www.domain.com.au/property-profile/25-king-st-melbourne-vic-3000-12345678"

    result = service.get_valuation(url, Decimal("1000000.00"))

    assert result.domain_property_id == "12345678"
    assert not any("/_suggest" in call.request.url for call in responses.calls)


@responses.activate
def test_unknown_address_falls_back():
    """Domain has no record for the address — fall back honestly."""
    responses.add(responses.GET, f"{BASE}/v1/properties/_suggest", json=[], status=200)
    service = PropertyService(client=make_client(), allow_estimate_fallback=True)

    result = service.get_valuation("Nowhere at all", Decimal("1000000.00"))

    assert result.provenance_source == PROVENANCE_ESTIMATE


# ---------------------------------------------------------------------------
# Partial failures — the AVM is load-bearing, the rest is enrichment
# ---------------------------------------------------------------------------


@responses.activate
def test_missing_rent_estimate_does_not_fail_the_valuation():
    """Rent is enrichment. Without it we still have a real AVM."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json=SUGGEST_PAYLOAD,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678/priceEstimate",
        json=PRICE_ESTIMATE_PAYLOAD,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678/rentalEstimate",
        json={"title": "Forbidden"},
        status=403,
    )
    service = PropertyService(client=make_client())

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.provenance_source == PROVENANCE_AVM
    assert result.current_value == Decimal("1250000.00")
    assert result.current_rent is None


@responses.activate
def test_price_estimate_without_a_usable_price_falls_back():
    """An AVM with no price in it is not a valuation."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json=SUGGEST_PAYLOAD,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/12345678/priceEstimate",
        json={"midPrice": None, "lowerPrice": None, "upperPrice": None},
        status=200,
    )
    service = PropertyService(client=make_client(), allow_estimate_fallback=True)

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.provenance_source == PROVENANCE_ESTIMATE


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


@responses.activate
def test_transient_500_is_retried():
    """A 500 is retried before it is given up on."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json={"message": "temporary"},
        status=500,
    )
    register_domain_mocks()
    service = PropertyService(client=make_client(retries=2, backoff_factor=0.0))

    result = service.get_valuation("25 King St, Melbourne VIC 3000", Decimal("1000000.00"))

    assert result.provenance_source == PROVENANCE_AVM
    assert len(responses.calls) == 5  # suggest (x2), property, price, rent


# ---------------------------------------------------------------------------
# The client's error mapping
# ---------------------------------------------------------------------------


def test_to_money_handles_none_and_garbage():
    assert to_money(None) is None
    assert to_money("") is None
    assert to_money("not a number") is None
    assert to_money(100) == Decimal("100.00")


@responses.activate
def test_client_raises_auth_error_on_401():
    responses.add(responses.GET, f"{BASE}/v1/properties/_suggest", json={}, status=401)
    client = make_client()

    with pytest.raises(DomainAuthError):
        client.suggest_addresses("25 King St")


@responses.activate
def test_client_sends_the_api_key_header():
    """Domain authenticates with the x-api-key header."""
    responses.add(
        responses.GET,
        f"{BASE}/v1/properties/_suggest",
        json=SUGGEST_PAYLOAD,
        status=200,
    )
    client = make_client()

    client.suggest_addresses("25 King St")

    assert responses.calls[0].request.headers["x-api-key"] == "key_test"
