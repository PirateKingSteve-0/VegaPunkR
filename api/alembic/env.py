from logging.config import fileConfig
import os
import sys
from dotenv import load_dotenv

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import models
from models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

def _redact(url: str) -> str:
    """Host and database name only — never print credentials."""
    try:
        from urllib.parse import urlsplit
        p = urlsplit(url)
        return f"{p.hostname or '?'}:{p.port or ''}{p.path or ''}"
    except Exception:
        return "<unparseable>"


# Which database? Mirror `database.py`'s rule — APP_ENV selects
# DATABASE_{DEV,PROD,TEST}_URL — instead of reading DATABASE_URL, which is what
# this did before and which points at DEV regardless of APP_ENV.
#
# 2026-09-06: `APP_ENV=prod alembic upgrade head` silently migrated **dev**,
# twice, printing "Running upgrade ..." both times. It was caught only because
# the new column was verified afterwards rather than trusting alembic's output.
# Same shape as the wrong-database hour recorded in JOURNAL.md on 09-05.
_APP_ENV = (os.getenv('APP_ENV') or 'dev').strip().lower()
_URL_VAR_BY_ENV = {
    'dev': 'DATABASE_DEV_URL',
    'prod': 'DATABASE_PROD_URL',
    'test': 'DATABASE_TEST_URL',
}
_url_var = _URL_VAR_BY_ENV.get(_APP_ENV)
if _url_var is None:
    raise RuntimeError(
        f"APP_ENV={_APP_ENV!r} is not one of {sorted(_URL_VAR_BY_ENV)} — refusing to guess "
        f"which database to migrate."
    )
# DATABASE_URL remains a last-resort fallback so an environment that only sets
# that one keeps working; the explicit per-env variable always wins.
_db_url = os.getenv(_url_var) or os.getenv('DATABASE_URL')
if not _db_url:
    raise RuntimeError(f"No database URL: {_url_var} is unset and DATABASE_URL is empty.")

# Say the target out loud BEFORE running anything. A migration that reports
# success against the wrong database is precisely what this guards against.
print(f"[alembic] APP_ENV={_APP_ENV} -> {_url_var} -> {_redact(_db_url)}")

config.set_main_option('sqlalchemy.url', _db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
