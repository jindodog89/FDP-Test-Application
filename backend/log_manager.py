"""
Log Manager — writes two parallel log streams for every test run:

  logs/
    run_<timestamp>_<run_id>.json   — structured result log (one per run)

  logs/debug/
    run_<timestamp>_<run_id>.log    — verbose nvme-cli command debug log
"""

import logging
import json
import os
from datetime import datetime
from pathlib import Path

# Root of the project (one level up from backend/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR     = PROJECT_ROOT / "logs"
DEBUG_DIR    = LOGS_DIR / "debug"


def _ensure_dirs():
    LOGS_DIR.mkdir(exist_ok=True)
    DEBUG_DIR.mkdir(exist_ok=True)


class RunLogger:
    """
    Created once per test run. Collects structured results and writes
    them to logs/ on completion. Also sets up the debug file handler
    so all nvme_cli.debug log records go to logs/debug/ for this run.
    """

    def __init__(self, run_id: str, device: str, test_ids: list):
        _ensure_dirs()
        self.run_id   = run_id
        self.device   = device
        self.test_ids = test_ids
        self.started  = datetime.now()
        self.results  = []

        ts = self.started.strftime("%Y%m%d_%H%M%S")
        self.stem = f"run_{ts}_{run_id}"

        # ── Debug log handler (nvme-cli verbose output) ───────────────────
        self.debug_path  = DEBUG_DIR / f"{self.stem}.log"
        self._fh         = logging.FileHandler(self.debug_path, encoding="utf-8")
        self._fh.setLevel(logging.DEBUG)
        self._fh.setFormatter(logging.Formatter(
            "%(asctime)s  %(message)s", datefmt="%H:%M:%S"
        ))

        self._debug_logger = logging.getLogger("nvme_cli.debug")
        self._debug_logger.setLevel(logging.DEBUG)
        self._debug_logger.addHandler(self._fh)
        self._debug_logger.propagate = False

        # Write run header to debug log
        self._debug_logger.debug("=" * 72)
        self._debug_logger.debug("RUN  : %s", run_id)
        self._debug_logger.debug("DEV  : %s", device)
        self._debug_logger.debug("TESTS: %s", ", ".join(test_ids))
        self._debug_logger.debug("=" * 72)

    def log_test_start(self, test_id: str, test_name: str):
        self._debug_logger.debug("")
        self._debug_logger.debug("─" * 60)
        self._debug_logger.debug("TEST START: [%s] %s", test_id, test_name)
        self._debug_logger.debug("─" * 60)

    def log_test_end(self, test_id: str, status: str, message: str):
        self._debug_logger.debug("TEST END  : [%s] status=%s  msg=%s",
                                 test_id, status, message)

    def record_result(self, result: dict):
        """Store a completed test result dict."""
        self.results.append(result)

    def finalize(self, run_status: str = "complete"):
        """Write the structured JSON result log and close the debug handler."""
        ended   = datetime.now()
        elapsed = (ended - self.started).total_seconds()

        summary = {
            "run_id":      self.run_id,
            "device":      self.device,
            "status":      run_status,
            "started_at":  self.started.isoformat(),
            "ended_at":    ended.isoformat(),
            "elapsed_sec": round(elapsed, 2),
            "total":       len(self.results),
            "pass":        sum(1 for r in self.results if r.get("status") == "pass"),
            "fail":        sum(1 for r in self.results if r.get("status") == "fail"),
            "warn":        sum(1 for r in self.results if r.get("status") == "warn"),
            "error":       sum(1 for r in self.results if r.get("status") == "error"),
            "skip":        sum(1 for r in self.results if r.get("status") == "skip"),
            "results":     self.results,
        }

        result_path = LOGS_DIR / f"{self.stem}.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)

        self._debug_logger.debug("")
        self._debug_logger.debug("=" * 72)
        self._debug_logger.debug(
            "RUN COMPLETE: %s  pass=%d fail=%d warn=%d  elapsed=%.1fs",
            run_status, summary["pass"], summary["fail"],
            summary["warn"], elapsed
        )
        self._debug_logger.debug("=" * 72)

        # Remove this run's handler so it doesn't bleed into the next run
        self._debug_logger.removeHandler(self._fh)
        self._fh.close()

        return str(result_path)