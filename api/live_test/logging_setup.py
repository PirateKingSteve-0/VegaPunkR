"""Dated, structured JSONL logging for the live test.

The app itself has no file logging — only ``logging.basicConfig(INFO)`` to
stdout (``api/app.py``). For the Monday live run we want durable, timestamped,
cleanly separable records. This module provides:

  * ``get_jsonl_logger(concern)`` — one append-only JSONL file per concern
    (``broker_http`` / ``orders`` / ``stream`` / ``reconcile``), every line
    stamped with UTC + ET time and the concern.
  * ``install_root_file_handler()`` — a human-readable ``engine-*.log`` file
    handler on the root logger.

Everything lands under ``<repo>/logs/livetest-<ET-date>/``, where the date is the
ET date of the *record*, not of process start: every file rolls over to the new
day's folder at ET midnight (same file name, so ``engine-<stamp>.log`` and
``stream-<stamp>.jsonl`` still pair up inside each day's folder). Before
2026-09-29 a file stayed in the folder of the day it was opened, so a process
running across midnight wrote later days into the first day's folder (41 files
as of 2026-09-28; e.g. 09-22 lives in livetest-2026-09-21/). Readers of older
logs must go by the ``ts_et`` inside each record, not by the folder name.
Files within a single process share one run-stamp so a run's logs sort together.

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


def _now() -> datetime:
    """Current UTC time. A seam so tests can move the clock across ET midnight."""
    return datetime.now(timezone.utc)


def _et_date(now: datetime) -> str:
    return now.astimezone(_ET).strftime("%Y-%m-%d")


def log_dir(et_date: str | None = None) -> Path:
    """`<repo>/logs/livetest-<ET-date>/`, created on demand (default: today, ET)."""
    d = _REPO_ROOT / "logs" / f"livetest-{et_date or _et_date(_now())}"
    d.mkdir(parents=True, exist_ok=True)
    return d


class JsonlLogger:
    """Append-only JSONL sink for one concern, line-buffered and lock-guarded."""

    def __init__(self, concern: str):
        self.concern = concern
        self._date = _et_date(_now())
        self.path = log_dir(self._date) / f"{concern}-{_RUN_STAMP}.jsonl"
        self._fh = open(self.path, "a", buffering=1)

    def _roll_if_new_day(self, et_date: str) -> None:
        """Caller holds _LOCK. Reopen under the new day's folder at ET midnight."""
        if et_date == self._date:
            return
        self.close()
        self._date = et_date
        self.path = log_dir(et_date) / f"{self.concern}-{_RUN_STAMP}.jsonl"
        self._fh = open(self.path, "a", buffering=1)

    def emit(self, record: dict) -> None:
        now = _now()
        row = {
            "ts_utc": now.isoformat(),
            "ts_et": now.astimezone(_ET).isoformat(),
            "concern": self.concern,
        }
        row.update(record)
        line = json.dumps(row, default=str)
        with _LOCK:
            self._roll_if_new_day(_et_date(now))
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


class _EtDailyFileHandler(logging.FileHandler):
    """FileHandler that moves to the new livetest-<ET-date>/ folder at ET midnight.

    The check runs inside emit(), which logging.Handler.handle() already calls
    under the handler's own lock, so a roll-over cannot interleave with a write.
    """

    def __init__(self, name: str):
        self._file_name = name
        self._date = _et_date(_now())
        super().__init__(log_dir(self._date) / name)

    def emit(self, record: logging.LogRecord) -> None:
        et_date = _et_date(_now())
        if et_date != self._date:
            self._date = et_date
            if self.stream:
                self.stream.close()
                self.stream = None  # type: ignore[assignment]
            self.baseFilename = str(log_dir(et_date) / self._file_name)
        super().emit(record)  # reopens baseFilename lazily when stream is None


def install_root_file_handler(level: int = logging.INFO) -> Path:
    """Add a file handler to the root logger (idempotent across reloads)."""
    path = log_dir() / f"engine-{_RUN_STAMP}.log"
    root = logging.getLogger()
    if not any(getattr(h, "_live_test", False) for h in root.handlers):
        fh = _EtDailyFileHandler(f"engine-{_RUN_STAMP}.log")
        fh.setLevel(level)
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        fh._live_test = True  # type: ignore[attr-defined]
        root.addHandler(fh)
    return path
