"""Tests for the portfolio HTTP layer.

The database is swapped via ``app.dependency_overrides[get_db]`` and the
valuation service via ``app.dependency_overrides[get_property_service]`` —
the routes themselves are never modified for tests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.property_service import (
    PROVENANCE_AVM,
    PROVENANCE_ESTIMATE,
    ProviderUnavailableError,
    ValuationResult,
)

PROPERTY_PAYLOAD = {
    "query": "25 King St, Melbourne VIC 3000",
    "purchase_price": 1000000,
    "entity_type": "personal",
}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_list_requires_a_token(client):
    """No token, no data."""
    response = client.get("/api/portfolio/properties")
    assert response.status_code == 401


def test_create_requires_a_token(client):
    response = client.post("/api/portfolio/properties", json=PROPERTY_PAYLOAD)
    assert response.status_code == 401


def test_an_invalid_token_is_rejected(client):
    response = client.get(
        "/api/portfolio/properties", headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401


def test_a_wrong_scheme_is_rejected(client):
    response = client.get(
        "/api/portfolio/properties", headers={"Authorization": "Basic dXNlcjpwdw=="}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Creating a property
# ---------------------------------------------------------------------------


def test_create_property(client, auth_headers, fake_service, avm_result):
    """A valuation comes back as a 201 with the resolved address."""
    fake_service(result=avm_result)

    response = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "25 King St, Melbourne VIC 3000"
    assert body["current_value"] == "1250000.00"
    assert body["purchase_price"] == "1000000.00"
    assert body["current_rent"] == "900.00"
    assert body["last_sold_date"] == "2022-10-15"
    assert body["provenance_source"] == PROVENANCE_AVM
    assert body["entity_type"] == "personal"
    assert body["id"] > 0


def test_money_survives_as_decimal(client, auth_headers, fake_service, avm_result):
    """Portfolios are totalled, so money cannot drift."""
    fake_service(result=avm_result)

    response = client.post(
        "/api/portfolio/properties",
        json={**PROPERTY_PAYLOAD, "purchase_price": 1000000.55},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["purchase_price"] == "1000000.55"


def test_response_model_filters_internal_columns(
    client, auth_headers, fake_service, avm_result
):
    """Internal columns never appear in the JSON."""
    fake_service(result=avm_result)

    response = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    )
    body = response.json()

    assert "owner_id" not in body
    assert "domain_property_id" not in body
    assert "created_at" not in body
    assert "updated_at" not in body
    assert "token_hash" not in body
    # …and only the declared fields are present.
    assert set(body.keys()) == {
        "id",
        "name",
        "entity_type",
        "purchase_price",
        "current_value",
        "last_sold_date",
        "current_rent",
        "provenance_source",
        "source_url",
    }


def test_duplicate_property_is_a_conflict(client, auth_headers, fake_service, avm_result):
    """The unique constraint on (owner_id, name) backs the 409."""
    fake_service(result=avm_result)

    first = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    )
    second = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_invalid_body_is_unprocessable(client, auth_headers):
    """A negative price is refused before it reaches the database."""
    response = client.post(
        "/api/portfolio/properties",
        json={**PROPERTY_PAYLOAD, "purchase_price": -1},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_invalid_entity_type_is_unprocessable(client, auth_headers):
    response = client.post(
        "/api/portfolio/properties",
        json={**PROPERTY_PAYLOAD, "entity_type": "trust"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_query_must_be_at_least_three_characters(client, auth_headers):
    response = client.post(
        "/api/portfolio/properties",
        json={**PROPERTY_PAYLOAD, "query": "ab"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_provider_down_with_strict_mode_is_a_bad_gateway(
    client, auth_headers, fake_service
):
    """No fallback means no invented number — the client gets a 502."""
    fake_service(error=ProviderUnavailableError("Domain API unreachable"))

    response = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    )

    assert response.status_code == 502


def test_provider_down_falls_back_and_says_so(client, auth_headers, fake_service):
    """With fallback on, the response is honest about being an estimate."""
    estimate = ValuationResult(
        name="25 King St, Melbourne VIC 3000",
        current_value=Decimal("1050000.00"),
        provenance_source=PROVENANCE_ESTIMATE,
    )
    fake_service(result=estimate)

    response = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    )

    assert response.status_code == 201
    assert response.json()["provenance_source"] == PROVENANCE_ESTIMATE
    assert response.json()["current_value"] == "1050000.00"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_list_properties(client, auth_headers, fake_service, avm_result):
    fake_service(result=avm_result)

    client.post("/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers)
    response = client.get("/api/portfolio/properties", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_is_paginated(client, auth_headers, fake_service, avm_result):
    """The list endpoint is paginated — never unbounded."""
    fake_service(result=avm_result)
    for index in range(3):
        client.post(
            "/api/portfolio/properties",
            json={**PROPERTY_PAYLOAD, "query": f"25 King St #{index}"},
            headers=auth_headers,
        )

    response = client.get("/api/portfolio/properties?limit=2", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_one_property(client, auth_headers, fake_service, avm_result):
    fake_service(result=avm_result)
    created = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    ).json()

    response = client.get(
        f"/api/portfolio/properties/{created['id']}", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_missing_property_is_not_found(client, auth_headers):
    response = client.get("/api/portfolio/properties/999999", headers=auth_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Owner isolation — the important one
# ---------------------------------------------------------------------------


def test_owner_isolation_on_read(client, auth_headers, other_auth_headers, fake_service, avm_result):
    """User B cannot read User A's property."""
    fake_service(result=avm_result)
    created = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    ).json()

    response = client.get(
        f"/api/portfolio/properties/{created['id']}", headers=other_auth_headers
    )

    assert response.status_code == 404


def test_owner_isolation_on_list(client, auth_headers, other_auth_headers, fake_service, avm_result):
    """User B's list does not contain User A's rows."""
    fake_service(result=avm_result)
    client.post("/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers)

    response = client.get("/api/portfolio/properties", headers=other_auth_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_owner_isolation_on_delete(client, auth_headers, other_auth_headers, fake_service, avm_result):
    """User B cannot delete User A's property."""
    fake_service(result=avm_result)
    created = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    ).json()

    response = client.delete(
        f"/api/portfolio/properties/{created['id']}", headers=other_auth_headers
    )

    assert response.status_code == 404
    # …and it still exists for its real owner.
    still_there = client.get(
        f"/api/portfolio/properties/{created['id']}", headers=auth_headers
    )
    assert still_there.status_code == 200


def test_two_owners_can_hold_the_same_address(
    client, auth_headers, other_auth_headers, fake_service, avm_result
):
    """The unique constraint is per-owner, not global."""
    fake_service(result=avm_result)

    mine = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    )
    theirs = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=other_auth_headers
    )

    assert mine.status_code == 201
    assert theirs.status_code == 201


# ---------------------------------------------------------------------------
# Deleting and transferring
# ---------------------------------------------------------------------------


def test_delete_property(client, auth_headers, fake_service, avm_result):
    fake_service(result=avm_result)
    created = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    ).json()

    response = client.delete(
        f"/api/portfolio/properties/{created['id']}", headers=auth_headers
    )

    assert response.status_code == 204
    assert response.content == b""


def test_delete_missing_property_is_not_found(client, auth_headers):
    response = client.delete("/api/portfolio/properties/999999", headers=auth_headers)
    assert response.status_code == 404


def test_transfer_entity_type(client, auth_headers, fake_service, avm_result):
    """A property can move between personal, super and company."""
    fake_service(result=avm_result)
    created = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    ).json()

    response = client.post(
        f"/api/portfolio/properties/{created['id']}/transfer",
        json={"target_entity": "super"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["entity_type"] == "super"


def test_transfer_to_an_invalid_entity_type_is_unprocessable(
    client, auth_headers, fake_service, avm_result
):
    fake_service(result=avm_result)
    created = client.post(
        "/api/portfolio/properties", json=PROPERTY_PAYLOAD, headers=auth_headers
    ).json()

    response = client.post(
        f"/api/portfolio/properties/{created['id']}/transfer",
        json={"target_entity": "trust"},
        headers=auth_headers,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Health and docs
# ---------------------------------------------------------------------------


def test_liveness_touches_no_dependency(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_the_database(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "connected"
