"""Dated, structured JSONL logging for the live test.

The app itself has no file logging — only ``logging.basicConfig(INFO)`` to
stdout (``api/app.py``). For the Monday live run we want durable, timestamped,
cleanly separable records. This module provides:

  * ``get_jsonl_logger(concern)`` — one append-only JSONL file per concern
    (``broker_http`` / ``orders`` / ``stream`` / ``reconcile``), every line
    stamped with UTC + ET time and the concern.
  * ``install_root_file_handler()`` — a human-readable ``engine-*.log`` file
    handler on the root logger.

Everything lands under ``<repo>/logs/livetest-<ET-date>/``. Files within a
single process share one run-stamp so a run's logs sort together.

The in-app instrumentation hooks (broker HTTP, WS payloads, order lifecycle)
should call ``get_jsonl_logger`` only when ``is_enabled()`` so normal runs are
unaffected. The standalone monitor logs unconditionally — running it *is* the
test.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytz

_ET = pytz.timezone("US/Eastern")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
_LOGGERS: dict[str, "JsonlLogger"] = {}
# One stamp per process so all of a run's files sort together.
_RUN_STAMP = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def is_enabled() -> bool:
    """True when LIVE_TEST_LOGGING is set — gates the in-app hooks."""
    return os.getenv("LIVE_TEST_LOGGING", "").lower() in ("1", "true", "yes", "on")


def log_dir() -> Path:
    """`<repo>/logs/livetest-<ET-date>/`, created on demand."""
    et_date = datetime.now(_ET).strftime("%Y-%m-%d")
    d = _REPO_ROOT / "logs" / f"livetest-{et_date}"
    d.mkdir(parents=True, exist_ok=True)
    return d


class JsonlLogger:
    """Append-only JSONL sink for one concern, line-buffered and lock-guarded."""

    def __init__(self, concern: str):
        self.concern = concern
        self.path = log_dir() / f"{concern}-{_RUN_STAMP}.jsonl"
        self._fh = open(self.path, "a", buffering=1)

    def emit(self, record: dict) -> None:
        now = datetime.now(timezone.utc)
        row = {
            "ts_utc": now.isoformat(),
            "ts_et": now.astimezone(_ET).isoformat(),
            "concern": self.concern,
        }
        row.update(record)
        line = json.dumps(row, default=str)
        with _LOCK:
            self._fh.write(line + "\n")

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def get_jsonl_logger(concern: str) -> JsonlLogger:
    with _LOCK:
        if concern not in _LOGGERS:
            _LOGGERS[concern] = JsonlLogger(concern)
        return _LOGGERS[concern]


def install_root_file_handler(level: int = logging.INFO) -> Path:
    """Add a file handler to the root logger (idempotent across reloads)."""
    path = log_dir() / f"engine-{_RUN_STAMP}.log"
    root = logging.getLogger()
    if not any(getattr(h, "_live_test", False) for h in root.handlers):
        fh = logging.FileHandler(path)
        fh.setLevel(level)
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        fh._live_test = True  # type: ignore[attr-defined]
        root.addHandler(fh)
    return path
