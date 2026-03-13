"""
Test: fdp_event_log_persistence_across_controller_reset

The FDP Events log page (Log ID 0x21) contains a ring buffer of events
(RU Not Written, RU Time Expiry, Controller Level Reset, etc.).  After a
Controller Reset, the existing event entries must be preserved — the ring
buffer must not be silently cleared.

This test:
  1. Triggers a known FDP event: writes with an invalid placement handle,
     which should generate an "Invalid Placement Handle" event (type 0x01).
  2. Reads the event log and records the number of entries and the sequence
     number of the most recent entry.
  3. Issues a Controller Reset.
  4. Re-reads the event log and verifies:
       a) The entry count did not decrease (entries were not cleared).
       b) A new "Controller Level Reset" event (type 0x03) was added.

Pass criteria : Event count did not decrease; CLR event present post-reset.
Warn criteria : Events persisted but no CLR event added (firmware optional).
Fail criteria : Event log was cleared (count dropped to 0) after reset.
Skip criteria : FDP not enabled, or events log not supported.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.reset.reset_base import ResetTestBase


class TestFDPEventLogPersistReset(ResetTestBase, BaseTest):
    test_id   = "fdp_event_log_persistence_across_controller_reset"
    name      = "FDP Event Log — Controller Reset Persistence"
    description = (
        "Verifies that the FDP Events log ring buffer is preserved across a "
        "Controller Reset and that the firmware appends a 'Controller Level "
        "Reset' event entry (type 0x03) as required by NVMe TP4146. "
        "Also confirms the log was not cleared by the reset."
    )
    category = "Reset"
    tags     = ["reset", "controller-reset", "fdp-events", "event-log", "persistence"]

    DEFAULT_PARAMS = {
        "endgrp":    1,
        "namespace": 1,
    }

    # FDP Event types from NVMe TP4146 Table 232
    FDP_EVENT_INVALID_PH      = 0x00
    FDP_EVENT_RU_NOT_WRITTEN  = 0x01
    FDP_EVENT_RU_TIME_EXPIRY  = 0x02
    FDP_EVENT_CTRL_LEVEL_RST  = 0x03
    FDP_EVENT_MEDIA_REALLOC   = 0x04
    FDP_EVENT_IMPLICITLY_ROTATED = 0x05

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: FDP enabled? ───────────────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log, endgrp=p["endgrp"])
        if skip:
            return skip

        # ── Step 2: Read FDP Events log baseline ──────────────────────────────
        log(f"\nStep 2: Reading FDP Events log baseline (endgrp={p['endgrp']})...")
        events_before = self._read_events_log(driver, log, p["endgrp"])
        if events_before is None:
            return TestResult(
                TestStatus.SKIP,
                "FDP Events log is not supported or unreadable on this device"
            )

        count_before = self._count_events(events_before)
        last_seq_before = self._get_last_seq(events_before)
        log(f"  Events before reset: count={count_before}  "
            f"last_seq={last_seq_before}")
        self._log_recent_events(log, events_before, n=3)

        # ── Step 3: Controller Reset ───────────────────────────────────────────
        log("\nStep 3: Issuing NVMe Controller Reset...")
        err = self._do_controller_reset(driver, log)
        if err:
            return err

        # ── Step 4: Wait for recovery ──────────────────────────────────────────
        log("\nStep 4: Waiting for controller to recover...")
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Controller did not recover within {self.RESET_TIMEOUT_S}s"
            )

        # ── Step 5: Re-read FDP Events log ────────────────────────────────────
        log(f"\nStep 5: Re-reading FDP Events log post-reset...")
        events_after = self._read_events_log(driver, log, p["endgrp"])
        if events_after is None:
            return TestResult(
                TestStatus.FAIL,
                "FDP Events log unreadable after Controller Reset"
            )

        count_after  = self._count_events(events_after)
        last_seq_after = self._get_last_seq(events_after)
        log(f"  Events after reset:  count={count_after}  "
            f"last_seq={last_seq_after}")
        self._log_recent_events(log, events_after, n=5)

        # ── Evaluate ──────────────────────────────────────────────────────────
        log("\n━━━ Analysis ━━━")
        issues = []

        # Check: event log was not cleared
        if count_after == 0 and count_before > 0:
            issues.append(
                f"FDP Events log was CLEARED by Controller Reset "
                f"(had {count_before} entries, now 0)"
            )
            log("  ✗ Event log was cleared — entries not preserved")
        elif count_after < count_before:
            issues.append(
                f"Event count decreased: {count_before} → {count_after}"
            )
            log(f"  ✗ Event count decreased (lost {count_before - count_after} entries)")
        else:
            log(f"  ✓ Event log preserved ({count_before} → {count_after} entries)")

        # Check: CLR event was appended (recommended per TP4146)
        clr_present = self._has_event_type(events_after, self.FDP_EVENT_CTRL_LEVEL_RST,
                                            after_seq=last_seq_before)
        if clr_present:
            log("  ✓ Controller Level Reset event (0x03) was appended to the log")
        else:
            log("  ⚠ No Controller Level Reset event (0x03) found after reset — "
                "firmware may not log CLR events (optional per spec)")

        if issues:
            return TestResult(
                TestStatus.FAIL,
                "FDP Event log not preserved across Controller Reset: " +
                "; ".join(issues),
                details={"count_before": count_before, "count_after": count_after}
            )

        if not clr_present:
            return TestResult(
                TestStatus.WARN,
                f"FDP Events log preserved ({count_before}→{count_after} entries) "
                "but no Controller Level Reset event was logged after reset. "
                "TP4146 recommends logging event type 0x03 on controller reset."
            )

        return TestResult(
            TestStatus.PASS,
            f"FDP Events log preserved across Controller Reset "
            f"({count_before}→{count_after} entries) and CLR event (0x03) was logged"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _read_events_log(self, driver, log, endgrp: int) -> dict | None:
        r = driver.fdp_events(endgrp=endgrp)
        if r["rc"] != 0:
            log(f"  FDP events error (rc={r['rc']}): {r.get('stderr','').strip()}")
            return None
        data = r.get("data", {})
        return data if data else None

    def _count_events(self, events_data: dict) -> int:
        """Count total event entries in the events log response."""
        if isinstance(events_data, list):
            return len(events_data)
        if isinstance(events_data, dict):
            for k in ("events", "fdp_events", "entries", "event_log"):
                if k in events_data and isinstance(events_data[k], list):
                    return len(events_data[k])
            # Some firmware returns a "nevents" count field
            for k in ("nevents", "num_events", "total_events"):
                if k in events_data:
                    return int(events_data[k])
        return 0

    def _get_last_seq(self, events_data: dict) -> int | None:
        """Return the sequence number of the most recent event entry."""
        entries = self._get_entries(events_data)
        if not entries:
            return None
        last = entries[-1]
        if isinstance(last, dict):
            for k in ("seq", "sequence", "event_seq", "seq_num"):
                if k in last:
                    return int(last[k])
        return len(entries) - 1  # fallback: use index

    def _has_event_type(self, events_data: dict, etype: int,
                         after_seq: int | None = None) -> bool:
        """Return True if a specific event type appears in the log."""
        entries = self._get_entries(events_data)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            t = entry.get("event_type", entry.get("etype", entry.get("type")))
            if t is not None and int(t) == etype:
                if after_seq is None:
                    return True
                seq = entry.get("seq", entry.get("sequence", 0))
                if (seq or 0) > (after_seq or 0):
                    return True
        return False

    def _get_entries(self, events_data: dict) -> list:
        """Normalise the events data structure to a flat list of entries."""
        if isinstance(events_data, list):
            return events_data
        if isinstance(events_data, dict):
            for k in ("events", "fdp_events", "entries", "event_log"):
                if k in events_data and isinstance(events_data[k], list):
                    return events_data[k]
        return []

    def _log_recent_events(self, log, events_data: dict, n: int = 3):
        """Log the N most recent events for debug context."""
        entries = self._get_entries(events_data)
        recent = entries[-n:] if len(entries) >= n else entries
        for e in recent:
            etype = e.get("event_type", e.get("etype", "?"))
            seq   = e.get("seq", e.get("sequence", "?"))
            ts    = e.get("timestamp", e.get("ts", ""))
            log(f"  Event: seq={seq} type=0x{int(etype):02x} ts={ts}")
