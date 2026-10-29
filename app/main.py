"""Application factory, lifespan and health checks.

``uvicorn app.main:app --reload``

This is the front door: it wires the routers, mounts CORS, gates the OpenAPI
docs behind ``WEALTHY_DEBUG``, and owns the lifespan — so the database
schema is created *inside* the lifespan, never at import time.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.config import settings
from app.database import Base, engine
from app.routers import auth, portfolio

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown.

    ``create_all()`` is a dev-only convenience, behind an explicit flag.
    Alembic owns the schema everywhere else.
    """
    if settings.auto_create_tables:
        logger.warning(
            "WEALTHY_AUTO_CREATE_TABLES is on — creating tables directly. "
            "This can never ALTER an existing schema; use Alembic in production."
        )
        Base.metadata.create_all(bind=engine)
    else:
        logger.info("Schema is managed by Alembic; not touching it at startup.")

    if not settings.has_domain_credentials:
        logger.warning(
            "No WEALTHY_DOMAIN_API_KEY configured — valuations will be served as "
            "algorithmic estimates and labelled as such."
        )
    else:
        logger.info("Domain.com.au credentials loaded.")

    yield

    engine.dispose()
    logger.info("Connection pool disposed.")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Track residential property held personally, inside superannuation, "
            "or through a company entity."
        ),
        lifespan=lifespan,
        # The OpenAPI spec is an attack-surface map. Only expose it in dev.
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth.router)
    app.include_router(portfolio.router)

    # -- pages ------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def serve_index():
        """The WealthNexus frontend."""
        if INDEX_HTML.is_file():
            return FileResponse(INDEX_HTML)
        return JSONResponse(
            {
                "service": settings.app_name,
                "version": settings.app_version,
                "docs": "/docs" if settings.debug else "disabled (WEALTHY_DEBUG=false)",
            },
        )

    # -- health -----------------------------------------------------------

    @app.get("/health/live", tags=["Health"])
    def health_live():
        """Liveness — the process is up. Touches no dependency."""
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
        }

    @app.get("/health/ready", tags=["Health"])
    def health_ready(response: Response):
        """Readiness — the database genuinely answers ``SELECT 1``."""
        database = "connected"
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
            database = f"unavailable: {exc.__class__.__name__}"
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {
            "status": "ok" if database == "connected" else "degraded",
            "database": database,
            "valuation_provider": (
                "domain.com.au" if settings.has_domain_credentials else "not configured"
            ),
        }

    return app


app = create_app()
