"""Shared pytest fixtures.

The database is swapped via ``app.dependency_overrides[get_db]`` — the routes
themselves are never modified for tests.

We use a real PostgreSQL database (not SQLite) because the money columns are
``NUMERIC`` and the date columns are real ``DATE``: SQLite would happily
accept a float where PostgreSQL refuses it, and the tests would pass against
a schema the app never actually uses.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import generate_token, hash_token
from app.database import Base, get_db
from app.main import app
from app.models import UserModel

TEST_DATABASE_URL = os.environ.get(
    "WEALTHY_TEST_DATABASE_URL",
    "postgresql+psycopg://wealthnexus:wealthnexus_dev@localhost:5432/wealthnexus_test",
)


@pytest.fixture(scope="session")
def engine():
    """A real Postgres engine bound to the test database."""
    test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, future=True)
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def db(engine) -> Session:
    """A session bound to the test database, with the tables emptied first.

    Each test starts from a known-empty state. This is deliberate: a route
    that commits (as the create endpoint does) would otherwise commit the
    outer rollback-transaction, and a route that rolls back (as the
    duplicate path does) would tear it down mid-test. Truncating is boring
    and completely deterministic.
    """
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE properties, users RESTART IDENTITY CASCADE"))

    session = Session(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    """A TestClient whose database is the transactional test session."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def user_factory(db):
    """Create users and return ``(user, raw_token)`` pairs."""

    def _make(email: str = "owner@example.com", display_name: str = "Owner"):
        raw_token = generate_token()
        user = UserModel(
            email=email,
            display_name=display_name,
            token_hash=hash_token(raw_token),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user, raw_token

    return _make


@pytest.fixture
def auth_headers(user_factory):
    """Auth headers for the first owner."""
    _, token = user_factory()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_auth_headers(user_factory):
    """Auth headers for a *second*, unrelated owner."""
    _, token = user_factory(email="intruder@example.com", display_name="Intruder")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def use_service():
    """Override the valuation service for the duration of one test.

    The route itself is never modified — only the dependency it resolves.
    """
    from app.routers.portfolio import get_property_service

    def _apply(service):
        app.dependency_overrides[get_property_service] = lambda: service
        return service

    yield _apply
    app.dependency_overrides.pop(get_property_service, None)


@pytest.fixture
def fake_service(use_service):
    """A service that always returns the same canned Domain valuation."""

    class _FakeService:
        def __init__(self, result=None, error=None):
            self.result = result
            self.error = error

        def get_valuation(self, query, purchase_price):
            if self.error is not None:
                raise self.error
            if self.result is None:
                return None
            # Echo the query as the resolved name, the way a real provider
            # resolves each address it is given.
            return replace(self.result, name=query)

    def _make(result=None, error=None):
        return use_service(_FakeService(result=result, error=error))

    return _make


@pytest.fixture
def avm_result():
    """A canned valuation as Domain would have produced it."""
    from datetime import date
    from decimal import Decimal

    from app.services.property_service import PROVENANCE_AVM, ValuationResult

    return ValuationResult(
        name="25 King St, Melbourne VIC 3000",
        current_value=Decimal("1250000.00"),
        provenance_source=PROVENANCE_AVM,
        last_sold_date=date(2022, 10, 15),
        current_rent=Decimal("900.00"),
        source_url="https://www.domain.com.au/property-profile/25-king-st-melbourne-vic-3000-12345678",
        domain_property_id="12345678",
    )
