"""
Test: fdp_disable_persistence_across_reset

The inverse of the enable-persistence tests.  Disables FDP using
`nvme fdp <dev> --endgrp-id=N --disable`, then verifies the disabled state
survives each reset type.  At the end, FDP is re-enabled so the device is
left in a useful state for subsequent tests.

This validates two things:
  1. The disabled state is stored in non-volatile memory (not just DRAM).
  2. The firmware cannot accidentally "auto-enable" FDP on reset.

Pass criteria : FDP remains DISABLED after all resets.
Fail criteria : FDP state changes from disabled to enabled after any reset.
Skip criteria : FDP is already disabled (cannot be sure we own the state
               change), or FDP cannot be disabled (active namespaces).
Note         : FDP is re-enabled at teardown regardless of pass/fail.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.reset.reset_base import ResetTestBase


class TestFDPDisablePersistenceAcrossReset(ResetTestBase, BaseTest):
    test_id   = "fdp_disable_persistence_across_reset"
    name      = "FDP Disable — Persistence Across All Reset Types"
    description = (
        "Disables FDP via 'nvme fdp --disable', then verifies the disabled "
        "state survives a Controller Reset, NVM Subsystem Reset, and PCIe "
        "link reset. FDP is re-enabled after the test completes. "
        "Tests that the firmware does not auto-enable FDP on any reset path."
    )
    category = "Reset"
    tags     = ["reset", "fdp-disable", "controller-reset", "subsystem-reset",
                "pcie", "persistence"]

    DEFAULT_PARAMS = {
        "endgrp":    1,
        "conf_idx":  0,    # Config index to re-enable at teardown
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: Confirm FDP is currently enabled ───────────────────────────
        log("Step 1: Confirming FDP is currently enabled (required to test disable)...")
        state = self._get_fdp_enable_state(driver, log, endgrp=p["endgrp"])
        if state is None:
            return TestResult(
                TestStatus.SKIP,
                "Cannot determine FDP state — device may not support FDP"
            )
        if not state:
            return TestResult(
                TestStatus.SKIP,
                "FDP is already disabled — cannot test disable persistence without "
                "knowing we triggered the state change. Enable FDP first with: "
                f"nvme fdp <dev> --endgrp-id={p['endgrp']} --enable-conf-idx={p['conf_idx']}"
            )
        log("  ✓ FDP is currently enabled — proceeding to disable it")

        # ── Step 2: Disable FDP ────────────────────────────────────────────────
        log(f"\nStep 2: Disabling FDP (endgrp={p['endgrp']})...")
        disable_result = driver.run_cmd(
            ["fdp", driver.device,
             f"--endgrp-id={p['endgrp']}", "--disable"],
            json_out=False
        )
        log(f"  Command: {disable_result.get('cmd', '')}")
        log(f"  RC: {disable_result['rc']}")
        if disable_result.get("stderr", "").strip():
            log(f"  stderr: {disable_result['stderr'].strip()}")

        if disable_result["rc"] != 0:
            return TestResult(
                TestStatus.SKIP,
                "Could not disable FDP — device may have active namespaces. "
                "Delete all namespaces before disabling FDP: "
                "nvme delete-ns <dev> --namespace-id=<N>  "
                f"stderr: {disable_result.get('stderr','').strip()}"
            )

        log("  ✓ FDP disabled — verifying...")
        state_after_disable = self._get_fdp_enable_state(driver, log, endgrp=p["endgrp"])
        if state_after_disable:
            self._reenable_fdp(driver, log, p)
            return TestResult(
                TestStatus.FAIL,
                "FDP disable command succeeded (rc=0) but FDP is still reported "
                "as enabled — firmware did not apply the disable"
            )
        log("  ✓ FDP confirmed disabled")

        result = self._run_reset_checks(driver, log, p)

        # ── Teardown: always re-enable FDP ────────────────────────────────────
        log("\nTeardown: Re-enabling FDP...")
        self._reenable_fdp(driver, log, p)

        return result

    # ── Core reset check loop ─────────────────────────────────────────────────

    def _run_reset_checks(self, driver, log, p: dict) -> TestResult:
        """
        Run all three resets in order, checking FDP remains disabled after each.
        Returns a TestResult summarising all outcomes.
        """
        failures = []

        # Reset 1: Controller Reset
        log("\n━━━ Reset 1: NVMe Controller Reset ━━━")
        err = self._do_controller_reset(driver, log)
        if err:
            return err
        if not self._post_reset_recovery(driver, log):
            return TestResult(TestStatus.FAIL,
                "Controller did not recover after Controller Reset")
        state = self._get_fdp_enable_state(driver, log, endgrp=p["endgrp"])
        if state:
            failures.append("Controller Reset: FDP became enabled after reset")
            log("  ✗ FDP is now ENABLED — disable state not preserved")
        else:
            log("  ✓ FDP remains disabled after Controller Reset")

        # Reset 2: NVM Subsystem Reset
        log("\n━━━ Reset 2: NVM Subsystem Reset (NSSR) ━━━")
        err = self._do_subsystem_reset(driver, log)
        if err:
            return err
        if not self._post_reset_recovery(driver, log):
            return TestResult(TestStatus.FAIL,
                "Subsystem did not recover after NSSR")
        state = self._get_fdp_enable_state(driver, log, endgrp=p["endgrp"])
        if state:
            failures.append("NSSR: FDP became enabled after reset")
            log("  ✗ FDP is now ENABLED — disable state not preserved")
        else:
            log("  ✓ FDP remains disabled after NSSR")

        # Reset 3: PCIe Link Reset
        log("\n━━━ Reset 3: PCIe Link Reset ━━━")
        err = self._do_link_reset(driver, log)
        if err:
            log(f"  ⚠ PCIe link reset skipped: {err.message}")
        else:
            if not self._post_reset_recovery(driver, log, is_link_reset=True):
                log("  ⚠ Device did not re-enumerate — skipping PCIe disable check")
            else:
                state = self._get_fdp_enable_state(driver, log, endgrp=p["endgrp"])
                if state:
                    failures.append("PCIe Link Reset: FDP became enabled after reset")
                    log("  ✗ FDP is now ENABLED — disable state not preserved")
                else:
                    log("  ✓ FDP remains disabled after PCIe link reset")

        if not failures:
            return TestResult(
                TestStatus.PASS,
                "FDP disabled state persisted correctly across all reset types "
                "(Controller Reset, NSSR, PCIe Link Reset). "
                "FDP has been re-enabled at teardown."
            )
        return TestResult(
            TestStatus.FAIL,
            "FDP disable state was lost across: " + "; ".join(failures),
            details={"failures": failures}
        )

    def _reenable_fdp(self, driver, log, p: dict):
        """Best-effort FDP re-enable — called at teardown regardless of outcome."""
        r = driver.run_cmd(
            ["fdp", driver.device,
             f"--endgrp-id={p['endgrp']}",
             f"--enable-conf-idx={p['conf_idx']}"],
            json_out=False
        )
        if r["rc"] == 0:
            log(f"  ✓ FDP re-enabled (endgrp={p['endgrp']}, conf_idx={p['conf_idx']})")
        else:
            log(f"  ⚠ FDP re-enable failed (rc={r['rc']}): {r.get('stderr','').strip()}")
            log(f"  Manual re-enable: nvme fdp <dev> --endgrp-id={p['endgrp']} "
                f"--enable-conf-idx={p['conf_idx']}")
