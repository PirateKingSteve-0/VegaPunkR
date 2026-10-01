"""Live-test log files must follow the ET date of each record, not process start.

Until 2026-09-29 every file stayed in the livetest-<ET-date>/ folder of the day it
was opened, so a process running across midnight wrote later sessions into the
first day's folder (2026-09-28's session landed in livetest-2026-09-27/). This
pins the fix in live_test/logging_setup.py:

  A. A JSONL logger opened before ET midnight writes the next record into the new
     day's folder, under the same file name.
  B. The engine .log file handler does the same.
  C. The boundary is ET midnight, not UTC midnight: 20:30 ET (00:30 UTC) is still
     the old day.

No network, no DB: the clock is injected through logging_setup._now and the repo
root is a temporary directory.
"""
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))

import live_test.logging_setup as ls

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


clock = {"now": datetime(2026, 9, 28, 23, 59, 0, tzinfo=timezone.utc)}  # 19:59 ET, 09-28
ls._now = lambda: clock["now"]

with tempfile.TemporaryDirectory() as tmp:
    ls._REPO_ROOT = Path(tmp)
    ls._LOGGERS.clear()

    # --- A. JSONL -----------------------------------------------------------
    log = ls.get_jsonl_logger("stream")
    log.emit({"n": 1})
    clock["now"] = datetime(2026, 9, 29, 0, 30, tzinfo=timezone.utc)   # 20:30 ET, still 09-28
    log.emit({"n": 2})
    clock["now"] = datetime(2026, 9, 29, 4, 1, tzinfo=timezone.utc)    # 00:01 ET, 09-29
    log.emit({"n": 3})
    log.close()

    name = f"stream-{ls._RUN_STAMP}.jsonl"
    day1 = Path(tmp) / "logs" / "livetest-2026-09-28" / name
    day2 = Path(tmp) / "logs" / "livetest-2026-09-29" / name
    check("A: 09-28 file has the two 09-28 ET records", day1.exists() and len(day1.read_text().splitlines()), 2)
    check("A: 09-29 file exists after ET midnight", day2.exists(), True)
    check("A: 09-29 file has only the 09-29 record", day2.exists() and len(day2.read_text().splitlines()), 1)
    check("C: UTC midnight alone does not roll", '"n": 2' in day1.read_text(), True)

    # --- B. engine .log -----------------------------------------------------
    clock["now"] = datetime(2026, 9, 29, 23, 0, tzinfo=timezone.utc)   # 19:00 ET, 09-29
    h = ls._EtDailyFileHandler("engine-test.log")
    lg = logging.getLogger("rollover-test")
    lg.propagate = False
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    lg.info("before midnight")
    clock["now"] = datetime(2026, 9, 30, 4, 5, tzinfo=timezone.utc)    # 00:05 ET, 09-30
    lg.info("after midnight")
    h.close()
    lg.removeHandler(h)

    e1 = Path(tmp) / "logs" / "livetest-2026-09-29" / "engine-test.log"
    e2 = Path(tmp) / "logs" / "livetest-2026-09-30" / "engine-test.log"
    check("B: 09-29 engine log has only its line", e1.exists() and e1.read_text().count("midnight"), 1)
    check("B: 09-30 engine log created", e2.exists(), True)
    check("B: 09-30 engine log has the after-midnight line", e2.exists() and "after midnight" in e2.read_text(), True)

if fails:
    print("FAIL test_live_test_log_rollover")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS test_live_test_log_rollover (7 checks)")
