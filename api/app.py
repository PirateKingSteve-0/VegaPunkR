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

    # Live-test: route the human-readable engine log to a dated file too.
    # Installed BEFORE the environment banner below so the banner is IN the log
    # file — otherwise the one line that says which database this process is
    # pinned to exists only in the launching terminal's scrollback.
    from live_test.logging_setup import is_enabled, install_root_file_handler
    if is_enabled():
        path = install_root_file_handler()
        logger.warning("🧪 LIVE_TEST_LOGGING on — engine log → %s", path)

    # Always make it obvious which database this process (API + engine worker)
    # is pinned to — critical since background trading is not per-request.
    logger.warning(
        "🗄️  Process DB environment: APP_ENV=%s → %s",
        os.getenv("APP_ENV", "dev"), default_environment().value,
    )

    from engine.tradier_stream_manager import get_stream_manager
    from engine.tradier_account_stream import get_account_stream_manager
    from engine.stream_driven_worker import get_stream_driven_worker
    from services.email_report_scheduler import get_email_report_scheduler

    stream_mgr = get_stream_manager()
    account_stream = get_account_stream_manager()

    # The account event stream is a process-wide singleton with no user, so it
    # cannot route itself. Give it the same client the ORDERS use — routed by the
    # user's live/paper selection — or it opens a socket on whatever TRADIER_ENV
    # says and silently watches the wrong account (TODO F1).
    def _account_stream_client():
        from database import SessionLocals, default_environment
        from models import Strategy, User
        from engine.trading_client_manager import TradingClientManager

        db = SessionLocals[default_environment()]()
        try:
            user_ids = [
                uid for (uid,) in db.query(Strategy.user_id)
                .filter(Strategy.is_active == True)  # noqa: E712
                .distinct().all()
            ]
            if not user_ids:
                return None
            if len(user_ids) > 1:
                # One socket, one account. Tradier's account stream cannot watch
                # several, so say so rather than picking silently.
                logger.warning(
                    "Active strategies span %d users %s — the account stream can "
                    "only watch one account; using user_id=%s.",
                    len(user_ids), user_ids, user_ids[0],
                )
            user = db.query(User).filter(User.id == user_ids[0]).first()
            return TradingClientManager().get_client(user) if user else None
        finally:
            db.close()

    account_stream.set_client_provider(_account_stream_client)
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
    # Same-LAN devices (phone, laptop) load the UI from the machine's hostname
    # or private IP, which makes their Origin something other than localhost.
    # Scoped to private ranges + mDNS .local names on the dev-server port —
    # never a wildcard, and CORS is not the security boundary here anyway (the
    # bearer token is); this only stops the browser refusing its own requests.
    allow_origin_regex=(
        r"http://("
        r"localhost|127\.0\.0\.1|[\w-]+\.local"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"):4200"
    ),
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
    import argparse
    import uvicorn

    # Flags exist because the env-var form is silently wrong when you forget it:
    # APP_ENV unset means `dev` (database.default_environment), and a dev DB whose
    # user is set to live trading places REAL orders against dev strategy params.
    # A flag is visible in shell history and in `ps`; a missing env var is not.
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="VegaPunkR API + trading engine.",
        epilog=(
            "examples:\n"
            "  python app.py                      dev DB, no file logging\n"
            "  python app.py --env prod --log     live run (prod DB + dated logs)\n"
            "  python app.py --env prod --log --no-reload   live run, code frozen\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env", choices=["dev", "test", "prod"], default=None,
        help="database for this process. Default: $APP_ENV, else dev.",
    )
    parser.add_argument(
        "--log", action="store_true",
        help="write dated engine + JSONL logs to logs/livetest-<ET-date>/ "
             "(same as LIVE_TEST_LOGGING=1).",
    )
    parser.add_argument(
        "--no-reload", action="store_true",
        help="disable the auto-reloader. Recommended for live runs: with reload on, "
             "saving any .py file hot-swaps engine code under an open position.",
    )
    parser.add_argument("--port", type=int, default=8000, help="listen port (default 8000).")
    args = parser.parse_args()

    # An explicit flag wins; otherwise whatever the environment already said stands.
    # Set BEFORE uvicorn.run so the reloader's child process inherits it — the child
    # imports app:app without re-running this block, and reads APP_ENV at import.
    if args.env:
        os.environ["APP_ENV"] = args.env
    if args.log:
        os.environ["LIVE_TEST_LOGGING"] = "1"

    _env = os.getenv("APP_ENV", "dev").strip().lower()
    _log = os.getenv("LIVE_TEST_LOGGING", "").lower() in ("1", "true", "yes", "on")
    print(
        f"\n  DB environment : {_env}{'   <-- REAL MONEY DB' if _env == 'prod' else ''}\n"
        f"  File logging   : {'on' if _log else 'off'}\n"
        f"  Auto-reload    : {'off' if args.no_reload else 'on'}\n"
        f"  Port           : {args.port}\n",
        flush=True,
    )

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=args.port,
        reload=not args.no_reload,
        # Only reload on Python source changes. Without a scope, the watcher fires on
        # every file in the tree — docs, TODO.md, .jsonl live-test logs, the diagram
        # hook's context json, __pycache__ — none of which the server cares about, and
        # each one prints "watchfiles.main: N change detected". Watch only the api dir
        # and only .py files.
        reload_dirs=["."],
        reload_includes=["*.py"],
        reload_excludes=["live_test/*", "debug/*", "tests/*", "*.jsonl", "*.log"],
        log_level="info",
    )
