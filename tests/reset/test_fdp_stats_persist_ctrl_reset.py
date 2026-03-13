"""
Test: fdp_stats_persistence_across_controller_reset

Runs a 10-second FDP IO workload, snapshots the FDP Statistics log page
(specifically "Media Bytes Media Written" — mbmw), issues a Controller Reset,
then re-reads the stats and asserts the value is unchanged.

FDP Statistics counters are defined as persistent across controller-level
resets by NVMe TP4146.  A counter that decreases or resets to 0 after a
Controller Reset indicates a firmware defect.

Pass criteria : mbmw (and hbmw, mbe where reported) unchanged after reset.
Warn criteria : Stats log readable but only some fields could be compared.
Fail criteria : Any counter changed, or controller did not recover.
Skip criteria : FDP not enabled, or fio not installed.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.reset.reset_base import ResetTestBase


class TestFDPStatsPersistCtrlReset(ResetTestBase, BaseTest):
    test_id   = "fdp_stats_persistence_across_controller_reset"
    name      = "FDP Stats — Controller Reset Persistence"
    description = (
        "Runs a 10-second FDP write workload, records the FDP Statistics "
        "log page (Media/Host Bytes Media Written, Media Bytes Erased), "
        "performs a Controller Reset, then verifies the counters are "
        "identical after recovery. FDP Statistics are defined as persistent "
        "across controller resets by NVMe TP4146."
    )
    category = "Reset"
    tags     = ["reset", "controller-reset", "fdp-stats", "mbmw", "persistence"]

    DEFAULT_PARAMS = {
        "fio_duration_sec": 10,
        "fio_block_size":   "128k",
        "queue_depth":      8,
        "placement_handle": 0,
        "namespace":        1,
        "endgrp":           1,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: Confirm FDP is enabled ────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log, endgrp=p["endgrp"])
        if skip:
            return skip

        # ── Step 2: Run IO workload to populate stats counters ─────────────────
        log(f"\nStep 2: Running {p['fio_duration_sec']}s FDP IO workload...")
        ok = self._run_fio_workload(
            driver, log,
            duration_sec=p["fio_duration_sec"],
            block_size=p["fio_block_size"],
            queue_depth=p["queue_depth"],
            placement_handle=p["placement_handle"],
            namespace=p["namespace"],
        )
        if not ok:
            return TestResult(
                TestStatus.SKIP,
                "fio workload could not be run — install fio (sudo apt install fio) "
                "or ensure the device has an accessible namespace"
            )

        # ── Step 3: Read FDP Stats baseline ───────────────────────────────────
        log(f"\nStep 3: Reading FDP Statistics log (endgrp={p['endgrp']})...")
        stats_before = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_before is None:
            return TestResult(
                TestStatus.FAIL,
                "FDP Statistics log page could not be read before reset. "
                "Ensure FDP is enabled and the device supports the FDP Stats log."
            )
        self._log_stats_snapshot(log, stats_before, label="before")

        mbmw_before = self._get_mbmw(stats_before)
        if mbmw_before is None:
            return TestResult(
                TestStatus.WARN,
                "FDP Statistics log returned no recognisable 'Media Bytes Media Written' "
                "field — firmware may use a non-standard field name. "
                "Cannot validate persistence."
            )
        log(f"  Recorded mbmw = {mbmw_before:,} bytes")

        # ── Step 4: Controller Reset ───────────────────────────────────────────
        log("\nStep 4: Issuing NVMe Controller Reset...")
        err = self._do_controller_reset(driver, log)
        if err:
            return err

        # ── Step 5: Wait for recovery ──────────────────────────────────────────
        log("\nStep 5: Waiting for controller to recover...")
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Controller did not respond within {self.RESET_TIMEOUT_S}s "
                "after Controller Reset"
            )

        # ── Step 6: Re-read FDP Stats and compare ─────────────────────────────
        log(f"\nStep 6: Re-reading FDP Statistics log post-reset...")
        stats_after = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_after is None:
            return TestResult(
                TestStatus.FAIL,
                "FDP Statistics log could not be read after Controller Reset. "
                "Log page may have been cleared or the device may not have "
                "fully recovered."
            )
        self._log_stats_snapshot(log, stats_after, label="after")

        log("\nComparing counters before / after reset:")
        comparison = self._compare_stats(stats_before, stats_after, log)

        if comparison["all_match"]:
            return TestResult(
                TestStatus.PASS,
                "All FDP Statistics counters (mbmw, hbmw, mbe) are identical "
                "before and after Controller Reset — stats correctly persisted"
            )
        else:
            changed = ", ".join(comparison["fields_changed"])
            return TestResult(
                TestStatus.FAIL,
                f"FDP Statistics counter(s) changed across Controller Reset: {changed}. "
                f"Counters must be preserved per NVMe TP4146 §5.x.",
                details=comparison["details"]
            )
