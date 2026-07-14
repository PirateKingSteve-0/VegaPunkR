"""
VegaPunkR Trading API - Main application entry point.
"""
import logging
import os
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import auth, strategies, positions, trades, performance, risk_events, system, execution, trading, events, admin
from tradier_integration import router as tradier_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --------------- startup ---------------
    from database import default_environment

    # Always make it obvious which database this process (API + engine worker)
    # is pinned to — critical since background trading is not per-request.
    logger.warning(
        "🗄️  Process DB environment: APP_ENV=%s → %s",
        os.getenv("APP_ENV", "dev"), default_environment().value,
    )

    # Live-test: route the human-readable engine log to a dated file too.
    from live_test.logging_setup import is_enabled, install_root_file_handler
    if is_enabled():
        path = install_root_file_handler()
        logger.warning("🧪 LIVE_TEST_LOGGING on — engine log → %s", path)

    from engine.tradier_stream_manager import get_stream_manager
    from engine.tradier_account_stream import get_account_stream_manager
    from engine.stream_driven_worker import get_stream_driven_worker
    from services.email_report_scheduler import get_email_report_scheduler

    stream_mgr = get_stream_manager()
    account_stream = get_account_stream_manager()
    worker = get_stream_driven_worker()
    email_scheduler = get_email_report_scheduler()

    try:
        await stream_mgr.start()
    except Exception as e:
        logger.error(f"Stream manager failed to start (non-fatal): {e}")

    # Order-event stream: pushes fill confirmations so we don't have to poll for them.
    # Non-fatal by design — OrderManager falls back to REST polling if this never
    # connects, which is exactly the behaviour that existed before it.
    try:
        await account_stream.start()
    except Exception as e:
        logger.error(f"Account event stream failed to start (non-fatal): {e}")

    try:
        await worker.start()
    except Exception as e:
        logger.error(f"Stream worker failed to start (non-fatal): {e}")

    try:
        email_scheduler.start()
    except Exception as e:
        logger.error(f"Email report scheduler failed to start (non-fatal): {e}")

    logger.info("VegaPunkR startup complete")
    yield

    # --------------- shutdown ---------------
    try:
        email_scheduler.stop()
    except Exception:
        pass
    try:
        await worker.stop()
    except Exception:
        pass
    try:
        await account_stream.stop()
    except Exception:
        pass
    try:
        await stream_mgr.stop()
    except Exception:
        pass
    logger.info("VegaPunkR shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Trading automation platform with strategy management, risk controls, and Tradier integration",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware (adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/")
def root():
    """Root endpoint - health check."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "online"
    }


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}


# Include routers
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(system.router, prefix=settings.API_V1_PREFIX)
app.include_router(strategies.router, prefix=settings.API_V1_PREFIX)
app.include_router(execution.router, prefix=settings.API_V1_PREFIX)
app.include_router(positions.router, prefix=settings.API_V1_PREFIX)
app.include_router(trades.router, prefix=settings.API_V1_PREFIX)
app.include_router(performance.router, prefix=settings.API_V1_PREFIX)
app.include_router(risk_events.router, prefix=settings.API_V1_PREFIX)
app.include_router(tradier_router.router, prefix=settings.API_V1_PREFIX)
app.include_router(trading.router, prefix=settings.API_V1_PREFIX)
app.include_router(events.router, prefix=settings.API_V1_PREFIX)
app.include_router(admin.router, prefix=settings.API_V1_PREFIX)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
