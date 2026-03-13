"""
Test: fdp_stats_persistence_across_device_reset

Same stats persistence check as the controller/subsystem variants, but uses
a PCIe link-level reset (Link Disable bit toggle on upstream root port).  This
is the strongest software-initiated reset possible without a physical power
cycle and most closely simulates a surprise removal/reinsertion scenario.

Pass criteria : mbmw/hbmw/mbe unchanged after link reset + re-enumeration.
Fail criteria : Any counter changed, re-enumeration fails, or PCIe error.
Skip criteria : FDP not enabled, fio not installed, or no upstream port.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.reset.reset_base import ResetTestBase


class TestFDPStatsPersistDeviceReset(ResetTestBase, BaseTest):
    test_id   = "fdp_stats_persistence_across_device_reset"
    name      = "FDP Stats — PCIe Link Reset Persistence"
    description = (
        "Runs a 10-second FDP write workload, snapshots the FDP Statistics "
        "log page, performs a PCIe link reset (Link Disable bit toggle on "
        "the upstream root port), waits for re-enumeration, then verifies "
        "all counters are unchanged. This is the most disruptive software "
        "reset and validates that stats are stored in non-volatile memory."
    )
    category = "Reset"
    tags     = ["reset", "pcie", "link-disable", "device-reset",
                "fdp-stats", "mbmw", "persistence"]

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
                "FDP Statistics log page could not be read before link reset"
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

        # ── Steps 4+5: PCIe link reset ─────────────────────────────────────────
        log("\nSteps 4–5: PCIe link reset via root complex Link Control register...")
        err = self._do_link_reset(driver, log)
        if err:
            return err

        # ── Step 6: Wait for re-enumeration ───────────────────────────────────
        log("\nStep 6: Waiting for device to re-enumerate...")
        if not self._post_reset_recovery(driver, log, is_link_reset=True):
            return TestResult(
                TestStatus.FAIL,
                f"Device did not re-enumerate within {self.RENUM_TIMEOUT_S}s "
                "after PCIe link reset"
            )

        # ── Step 7: Re-read and compare ────────────────────────────────────────
        log(f"\nStep 7: Re-reading FDP Statistics log post-link-reset...")
        stats_after = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_after is None:
            return TestResult(
                TestStatus.FAIL,
                "FDP Statistics log could not be read after PCIe link reset. "
                "Device may not have fully re-enumerated."
            )
        self._log_stats_snapshot(log, stats_after, label="after")

        log("\nComparing counters before / after link reset:")
        comparison = self._compare_stats(stats_before, stats_after, log)

        if comparison["all_match"]:
            return TestResult(
                TestStatus.PASS,
                "All FDP Statistics counters (mbmw, hbmw, mbe) are identical "
                "before and after PCIe link reset — stats correctly stored in "
                "non-volatile memory"
            )
        else:
            changed = ", ".join(comparison["fields_changed"])
            return TestResult(
                TestStatus.FAIL,
                f"FDP Statistics counter(s) changed across PCIe link reset: {changed}. "
                "Counters were not persisted in non-volatile storage.",
                details=comparison["details"]
            )
