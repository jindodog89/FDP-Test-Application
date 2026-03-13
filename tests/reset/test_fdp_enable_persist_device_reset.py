"""
Test: fdp_enable_persistence_across_device_reset

Checks that the FDP feature enable bit survives a PCIe link-level reset
performed by toggling the Link Disable bit (bit 4) in the Link Control
register of the upstream root port.  This is the most disruptive software-
initiated reset available without a power cycle.

Steps match the test spec exactly:
  1) Confirm FDP enabled
  2) Write 1 to Link Disable bit in root complex (upstream port) config space
  3) Write 0 to Link Disable bit — triggers link retraining
  4) Wait for device to re-enumerate
  5) Confirm FDP still enabled

Pass criteria : FDP remains enabled after full link re-enumeration.
Fail criteria : FDP disabled post-reset, PCIe driver fails, or no re-enum.
Skip criteria : FDP not enabled, or no upstream PCIe port resolvable.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.reset.reset_base import ResetTestBase


class TestFDPEnablePersistDeviceReset(ResetTestBase, BaseTest):
    test_id   = "fdp_enable_persistence_across_device_reset"
    name      = "FDP Enable — PCIe Link Reset Persistence"
    description = (
        "Verifies that the FDP enable bit survives a PCIe link-level reset. "
        "The test sets the Link Disable bit in the upstream root port's "
        "Link Control register, then clears it to trigger link retraining "
        "and device re-enumeration. This is the most disruptive software "
        "reset short of a power cycle."
    )
    category = "Reset"
    tags     = ["reset", "pcie", "link-disable", "device-reset", "fdp-enable", "persistence"]

    def run(self, driver, log) -> TestResult:

        # ── Step 1: Confirm FDP is enabled ────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log)
        if skip:
            return skip

        # ── Steps 2+3: Link Disable → Link Enable (link reset) ────────────────
        log("\nSteps 2–3: PCIe link reset via root complex Link Control register...")
        err = self._do_link_reset(driver, log)
        if err:
            return err

        # ── Step 4: Wait for device to re-enumerate ───────────────────────────
        log("\nStep 4: Waiting for device to re-enumerate...")
        if not self._post_reset_recovery(driver, log, is_link_reset=True):
            return TestResult(
                TestStatus.FAIL,
                f"Device did not re-enumerate within {self.RENUM_TIMEOUT_S}s "
                "after PCIe link reset. Check dmesg for PCIe link training errors."
            )

        # ── Step 5: Re-check FDP enable state ─────────────────────────────────
        log("\nStep 5: Verifying FDP enable state after link reset...")
        skip = self._assert_fdp_enabled(driver, log)
        if skip:
            return TestResult(
                TestStatus.FAIL,
                "FDP is no longer enabled after PCIe link reset. "
                "FDP state was not retained — device did not restore "
                "non-volatile configuration across link-level reset."
            )

        return TestResult(
            TestStatus.PASS,
            "FDP enable state correctly persisted across PCIe link reset"
        )
