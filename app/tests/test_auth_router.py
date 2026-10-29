"""Tests for token issuance.

Two modes, and the difference between them is the difference between an
open public endpoint and a closed one:

* **Open** — no bootstrap admin. Any email mints a token with no password.
* **Closed** — a bootstrap admin is configured. Only that email may mint a
  token, and only by presenting the shared secret.

The settings object is swapped on the router module, so the routes are
never modified for tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

SECRET = "s3cret-bootstrap-value"
ADMIN_EMAIL = "admin@example.com"


class _OpenSettings:
    """No bootstrap admin configured — the development behaviour."""

    has_bootstrap_admin = False
    bootstrap_admin_email = None
    bootstrap_admin_secret_value = None
    allow_self_service_tokens = True
    debug = True


class _ClosedSettings:
    """A bootstrap admin is configured — closed mode."""

    has_bootstrap_admin = True
    bootstrap_admin_email = ADMIN_EMAIL
    bootstrap_admin_secret_value = SECRET
    allow_self_service_tokens = False
    debug = False


@pytest.fixture
def open_mode(monkeypatch):
    monkeypatch.setattr("app.routers.auth.settings", _OpenSettings())


@pytest.fixture
def closed_mode(monkeypatch):
    monkeypatch.setattr("app.routers.auth.settings", _ClosedSettings())


# ---------------------------------------------------------------------------
# Open mode (development)
# ---------------------------------------------------------------------------


def test_open_mode_issues_a_token_for_any_email(client, open_mode):
    response = client.post("/auth/token", json={"email": "someone@example.com"})
    assert response.status_code == 201
    assert response.json()["access_token"].startswith("wpx_")


def test_open_mode_needs_no_password(client, open_mode):
    response = client.post("/auth/token", json={"email": "someone@example.com"})
    assert response.status_code == 201


def test_an_issued_token_identifies_its_owner(client, open_mode):
    token = client.post(
        "/auth/token", json={"email": "someone@example.com"}
    ).json()["access_token"]
    response = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "someone@example.com"


# ---------------------------------------------------------------------------
# Closed mode (production)
# ---------------------------------------------------------------------------


def test_closed_mode_issues_a_token_to_the_admin_with_the_secret(client, closed_mode):
    response = client.post(
        "/auth/token", json={"email": ADMIN_EMAIL, "password": SECRET}
    )
    assert response.status_code == 201
    assert response.json()["access_token"].startswith("wpx_")


def test_closed_mode_rejects_a_wrong_secret(client, closed_mode):
    response = client.post(
        "/auth/token", json={"email": ADMIN_EMAIL, "password": "not-the-secret"}
    )
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]


def test_closed_mode_rejects_a_missing_secret(client, closed_mode):
    response = client.post("/auth/token", json={"email": ADMIN_EMAIL})
    assert response.status_code == 401


def test_closed_mode_rejects_an_empty_secret(client, closed_mode):
    response = client.post(
        "/auth/token", json={"email": ADMIN_EMAIL, "password": ""}
    )
    assert response.status_code == 401


def test_closed_mode_refuses_every_other_email(client, closed_mode):
    """The whole point: no token for anyone but the administrator."""
    response = client.post(
        "/auth/token", json={"email": "attacker@example.com", "password": SECRET}
    )
    assert response.status_code == 403
    assert "bootstrap administrator" in response.json()["detail"]


def test_closed_mode_does_not_accept_the_secret_for_another_email(client, closed_mode):
    """Knowing the secret must not let you claim a different identity."""
    response = client.post(
        "/auth/token", json={"email": "someone@example.com", "password": SECRET}
    )
    assert response.status_code == 403


def test_closed_mode_admin_token_identifies_its_owner(client, closed_mode):
    token = client.post(
        "/auth/token", json={"email": ADMIN_EMAIL, "password": SECRET}
    ).json()["access_token"]
    response = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == ADMIN_EMAIL


# ---------------------------------------------------------------------------
# The secret must never leak
# ---------------------------------------------------------------------------


def test_the_secret_is_never_echoed_back(client, closed_mode):
    response = client.post(
        "/auth/token", json={"email": ADMIN_EMAIL, "password": SECRET}
    )
    assert response.status_code == 201
    assert SECRET not in response.text


def test_the_secret_is_never_stored(client, closed_mode, db):
    client.post("/auth/token", json={"email": ADMIN_EMAIL, "password": SECRET})
    row = db.execute(
        text("SELECT token_hash FROM users WHERE email = :e"),
        {"e": ADMIN_EMAIL},
    ).one()
    assert SECRET not in row.token_hash
