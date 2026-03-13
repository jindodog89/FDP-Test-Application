"""
Test: fdp_enable_persistence_across_nvme_subsystem_reset

Checks that the FDP feature enable bit survives an NVM Subsystem Reset (NSSR).
NSSR is heavier than a controller reset — it affects all controllers in the
subsystem and exercises non-volatile storage of controller configuration.

Pass criteria : FDP remains enabled after the subsystem comes back.
Fail criteria : FDP is disabled post-reset, or subsystem does not recover.
Skip criteria : FDP was not enabled before the test started.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.reset.reset_base import ResetTestBase


class TestFDPEnablePersistSubsystemReset(ResetTestBase, BaseTest):
    test_id   = "fdp_enable_persistence_across_nvme_subsystem_reset"
    name      = "FDP Enable — NVM Subsystem Reset Persistence"
    description = (
        "Verifies that the FDP enable bit survives an NVM Subsystem Reset "
        "(nvme subsystem-reset / NSSR). NSSR is a heavier reset than a "
        "Controller Reset; it exercises non-volatile retention of FDP "
        "configuration state across a full subsystem power-on sequence."
    )
    category = "Reset"
    tags     = ["reset", "subsystem-reset", "nssr", "fdp-enable", "persistence"]

    def run(self, driver, log) -> TestResult:

        # ── Step 1: Confirm FDP is enabled ────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log)
        if skip:
            return skip

        # ── Step 2: NVM Subsystem Reset ───────────────────────────────────────
        log("\nStep 2: Issuing NVM Subsystem Reset (NSSR)...")
        err = self._do_subsystem_reset(driver, log)
        if err:
            return err

        # ── Step 3: Wait for subsystem to recover (longer than ctrl reset) ────
        log("\nStep 3: Waiting for subsystem to recover...")
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Controller did not respond within {self.RESET_TIMEOUT_S}s "
                "after NVM Subsystem Reset. The subsystem may have failed to "
                "reinitialise — check dmesg for NVMe errors."
            )

        # ── Step 4: Re-check FDP enable state ─────────────────────────────────
        log("\nStep 4: Verifying FDP enable state post-NSSR...")
        skip = self._assert_fdp_enabled(driver, log)
        if skip:
            return TestResult(
                TestStatus.FAIL,
                "FDP is no longer enabled after NVM Subsystem Reset. "
                "FDP enable state was not preserved across NSSR — "
                "controller is not retaining configuration in non-volatile storage."
            )

        return TestResult(
            TestStatus.PASS,
            "FDP enable state correctly persisted across NVM Subsystem Reset (NSSR)"
        )
