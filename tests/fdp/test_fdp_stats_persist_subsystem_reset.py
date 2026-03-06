"""
Test: fdp_stats_persistence_across_nvme_subsystem_reset

Same as the controller reset variant but uses nvme subsystem-reset (NSSR).
NSSR is a stronger test of non-volatile counter persistence because the
controller's internal state machines are fully torn down.

Pass criteria : mbmw/hbmw/mbe unchanged after NSSR.
Fail criteria : Any counter changed, or subsystem did not recover.
Skip criteria : FDP not enabled, or fio not installed.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.fdp.reset_base import ResetTestBase


class TestFDPStatsPersistSubsystemReset(ResetTestBase, BaseTest):
    test_id   = "fdp_stats_persistence_across_nvme_subsystem_reset"
    name      = "FDP Stats — NVM Subsystem Reset Persistence"
    description = (
        "Runs a 10-second FDP write workload, records the FDP Statistics "
        "log page, performs an NVM Subsystem Reset (NSSR), then verifies "
        "all counters are unchanged. NSSR is a stronger persistence test "
        "than a Controller Reset because it exercises the non-volatile "
        "storage of all controller state."
    )
    category = "Reset"
    tags     = ["reset", "subsystem-reset", "nssr", "fdp-stats", "mbmw", "persistence"]

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

        # ── Step 1: FDP enabled? ───────────────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log, endgrp=p["endgrp"])
        if skip:
            return skip

        # ── Step 2: IO workload ────────────────────────────────────────────────
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
                "fio workload could not be run — install fio or check device namespace"
            )

        # ── Step 3: Read FDP Stats baseline ───────────────────────────────────
        log(f"\nStep 3: Reading FDP Statistics log (endgrp={p['endgrp']})...")
        stats_before = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_before is None:
            return TestResult(
                TestStatus.FAIL,
                "FDP Statistics log page could not be read before NSSR"
            )
        self._log_stats_snapshot(log, stats_before, label="before")

        mbmw_before = self._get_mbmw(stats_before)
        if mbmw_before is None:
            return TestResult(
                TestStatus.WARN,
                "No recognisable 'Media Bytes Media Written' field in FDP Stats. "
                "Cannot validate persistence."
            )
        log(f"  Recorded mbmw = {mbmw_before:,} bytes")

        # ── Step 4: NVM Subsystem Reset ───────────────────────────────────────
        log("\nStep 4: Issuing NVM Subsystem Reset (NSSR)...")
        err = self._do_subsystem_reset(driver, log)
        if err:
            return err

        # ── Step 5: Wait for recovery ──────────────────────────────────────────
        log("\nStep 5: Waiting for subsystem to recover...")
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Subsystem did not respond within {self.RESET_TIMEOUT_S}s after NSSR"
            )

        # ── Step 6: Re-read and compare ────────────────────────────────────────
        log(f"\nStep 6: Re-reading FDP Statistics log post-NSSR...")
        stats_after = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_after is None:
            return TestResult(
                TestStatus.FAIL,
                "FDP Statistics log could not be read after NSSR"
            )
        self._log_stats_snapshot(log, stats_after, label="after")

        log("\nComparing counters before / after NSSR:")
        comparison = self._compare_stats(stats_before, stats_after, log)

        if comparison["all_match"]:
            return TestResult(
                TestStatus.PASS,
                "All FDP Statistics counters (mbmw, hbmw, mbe) are identical "
                "before and after NVM Subsystem Reset — stats correctly persisted"
            )
        else:
            changed = ", ".join(comparison["fields_changed"])
            return TestResult(
                TestStatus.FAIL,
                f"FDP Statistics counter(s) changed across NSSR: {changed}. "
                "Counters must be preserved in non-volatile storage.",
                details=comparison["details"]
            )
