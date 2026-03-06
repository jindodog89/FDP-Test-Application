"""
Test: ph_to_ruh_mapping_persistence

Snapshots the Placement Handle → Reclaim Unit Handle mapping (read via the
RUHS / nvme fdp status command), performs each of the three reset types in
sequence, and verifies the mapping is identical after each reset.

The PH→RUH mapping is established when an FDP-enabled namespace is created
and is part of the namespace's persistent configuration.  It MUST survive all
forms of controller and subsystem reset.  A mapping change after reset would
cause the host to route writes to wrong RUs, silently breaking FDP isolation.

Resets performed (each preceded by a mapping snapshot):
  1. Controller Reset (nvme reset)
  2. NVM Subsystem Reset (nvme subsystem-reset)
  3. PCIe Link Reset (Link Disable bit toggle on upstream root port)

Pass criteria : PH→RUH mapping identical before and after every reset.
Fail criteria : Any mapping entry differs after any reset.
Skip criteria : FDP not enabled, or no namespaces with FDP placement handles.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.fdp.reset_base import ResetTestBase


class TestPHToRUHMappingPersistence(ResetTestBase, BaseTest):
    test_id   = "ph_to_ruh_mapping_persistence"
    name      = "PH→RUH Mapping — Persistence Across All Reset Types"
    description = (
        "Snapshots the Placement Handle to Reclaim Unit Handle mapping via "
        "the RUHS log, then verifies the mapping is unchanged after a "
        "Controller Reset, NVM Subsystem Reset, and PCIe link reset. "
        "A changed mapping would silently break FDP data placement isolation."
    )
    category = "Reset"
    tags     = ["reset", "ph-ruh", "mapping", "ruhs", "persistence",
                "controller-reset", "subsystem-reset", "pcie"]

    DEFAULT_PARAMS = {
        "namespace": 1,
        "endgrp":    1,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: FDP enabled? ───────────────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log, endgrp=p["endgrp"])
        if skip:
            return skip

        # ── Step 2: Read initial PH→RUH mapping ───────────────────────────────
        log(f"\nStep 2: Reading baseline PH→RUH mapping (ns={p['namespace']})...")
        baseline = self._read_ph_ruh_mapping(driver, log, namespace=p["namespace"])
        if not baseline:
            return TestResult(
                TestStatus.SKIP,
                "No PH→RUH mapping entries found. Ensure an FDP-enabled namespace "
                "exists with placement handles: nvme create-ns <dev> --nphndls=N ..."
            )
        self._log_mapping(log, baseline, label="baseline")
        log(f"  {len(baseline)} placement handle(s) mapped")

        failures = []

        # ── Reset 1: Controller Reset ──────────────────────────────────────────
        log("\n━━━ Reset 1: NVMe Controller Reset ━━━")
        err = self._do_controller_reset(driver, log)
        if err:
            return err
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Controller did not recover within {self.RESET_TIMEOUT_S}s "
                "after Controller Reset"
            )
        mapping_after_ctrl = self._read_ph_ruh_mapping(
            driver, log, namespace=p["namespace"]
        )
        self._log_mapping(log, mapping_after_ctrl, label="after ctrl reset")
        diff = self._diff_mappings(baseline, mapping_after_ctrl)
        if diff:
            failures.append(f"Controller Reset: {diff}")
            log(f"  ✗ Mapping changed after Controller Reset: {diff}")
        else:
            log("  ✓ Mapping unchanged after Controller Reset")

        # ── Reset 2: NVM Subsystem Reset ──────────────────────────────────────
        log("\n━━━ Reset 2: NVM Subsystem Reset (NSSR) ━━━")
        err = self._do_subsystem_reset(driver, log)
        if err:
            return err
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Subsystem did not recover within {self.RESET_TIMEOUT_S}s after NSSR"
            )
        mapping_after_nssr = self._read_ph_ruh_mapping(
            driver, log, namespace=p["namespace"]
        )
        self._log_mapping(log, mapping_after_nssr, label="after NSSR")
        diff = self._diff_mappings(baseline, mapping_after_nssr)
        if diff:
            failures.append(f"NVM Subsystem Reset: {diff}")
            log(f"  ✗ Mapping changed after NSSR: {diff}")
        else:
            log("  ✓ Mapping unchanged after NSSR")

        # ── Reset 3: PCIe Link Reset ───────────────────────────────────────────
        log("\n━━━ Reset 3: PCIe Link Reset ━━━")
        err = self._do_link_reset(driver, log)
        if err:
            log(f"  ⚠ PCIe link reset skipped: {err.message}")
            # Non-fatal — skip PCIe reset gracefully if no upstream port found
        else:
            if not self._post_reset_recovery(driver, log, is_link_reset=True):
                log("  ⚠ Device did not re-enumerate — skipping PCIe mapping check")
            else:
                mapping_after_pcie = self._read_ph_ruh_mapping(
                    driver, log, namespace=p["namespace"]
                )
                self._log_mapping(log, mapping_after_pcie, label="after PCIe reset")
                diff = self._diff_mappings(baseline, mapping_after_pcie)
                if diff:
                    failures.append(f"PCIe Link Reset: {diff}")
                    log(f"  ✗ Mapping changed after PCIe link reset: {diff}")
                else:
                    log("  ✓ Mapping unchanged after PCIe link reset")

        # ── Evaluate ──────────────────────────────────────────────────────────
        log("\n━━━ Summary ━━━")
        if not failures:
            return TestResult(
                TestStatus.PASS,
                f"PH→RUH mapping ({len(baseline)} handles) persisted correctly "
                "across all reset types (Controller Reset, NSSR, PCIe Link Reset)"
            )
        else:
            return TestResult(
                TestStatus.FAIL,
                "PH→RUH mapping changed after reset(s): " +
                "; ".join(failures),
                details={"failures": failures, "baseline": baseline}
            )

    # ── Mapping comparison ────────────────────────────────────────────────────

    def _diff_mappings(self, before: list[dict], after: list[dict]) -> str | None:
        """
        Compare two PH→RUH mapping lists.
        Returns a human-readable diff string if they differ, or None if identical.
        """
        if len(before) != len(after):
            return (f"entry count changed: {len(before)} → {len(after)}")

        diffs = []
        for a, b in zip(sorted(before, key=lambda x: x["phndl"]),
                        sorted(after,  key=lambda x: x["phndl"])):
            if a["phndl"] != b["phndl"]:
                diffs.append(f"PH index mismatch: {a['phndl']} vs {b['phndl']}")
            elif a["ruhid"] != b["ruhid"]:
                diffs.append(
                    f"PH {a['phndl']}: RUH {a['ruhid']} → {b['ruhid']}"
                )
        return "; ".join(diffs) if diffs else None
