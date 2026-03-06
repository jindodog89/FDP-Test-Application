"""
Test: fdp_enable_persistence_across_controller_reset

Checks that the FDP feature enable bit survives an NVMe Controller Reset
(CC.EN = 0 followed by CC.EN = 1).  Per NVMe TP4146, FDP enable state is
defined as persistent across controller-level resets.

Pass criteria : FDP remains enabled after the controller comes back.
Fail criteria : FDP is disabled after reset, or controller does not recover.
Skip criteria : FDP was not enabled before the test started.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.fdp.reset_base import ResetTestBase


class TestFDPEnablePersistCtrlReset(ResetTestBase, BaseTest):
    test_id   = "fdp_enable_persistence_across_controller_reset"
    name      = "FDP Enable — Controller Reset Persistence"
    description = (
        "Verifies that the FDP enable bit survives an NVMe Controller Reset "
        "(nvme reset / CC.EN cycle). FDP enable state is defined as persistent "
        "across controller-level resets by the FDP specification (TP4146)."
    )
    category = "Reset"
    tags     = ["reset", "controller-reset", "fdp-enable", "persistence"]

    def run(self, driver, log) -> TestResult:

        # ── Step 1: Confirm FDP is enabled ────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log)
        if skip:
            return skip

        # ── Step 2: Controller Reset ──────────────────────────────────────────
        log("\nStep 2: Issuing NVMe Controller Reset...")
        err = self._do_controller_reset(driver, log)
        if err:
            return err

        # ── Step 3: Wait for controller to recover ────────────────────────────
        log("\nStep 3: Waiting for controller to recover...")
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Controller did not respond within {self.RESET_TIMEOUT_S}s "
                "after controller reset"
            )

        # ── Step 4: Re-check FDP enable state ─────────────────────────────────
        log("\nStep 4: Verifying FDP enable state post-reset...")
        skip = self._assert_fdp_enabled(driver, log)
        if skip:
            return TestResult(
                TestStatus.FAIL,
                "FDP is no longer enabled after Controller Reset. "
                "FDP enable state was not preserved — device is non-compliant "
                "with NVMe TP4146 persistence requirements."
            )

        return TestResult(
            TestStatus.PASS,
            "FDP enable state correctly persisted across NVMe Controller Reset"
        )
