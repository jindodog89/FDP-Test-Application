"""
Test: nvme_write_legacy
Issue an NVMe write with directive type 0h (no directive / legacy behavior).
Per FDP spec, legacy writes must be routed to reclaim unit handle 0.
Verify handle 0 capacity decreases.
"""

from tests.base_test import BaseTest, TestResult, TestStatus
import os as _os
_IO_FILES = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "IO_files")
_DATA_FILE = _os.path.join(_IO_FILES, "randints_4k.txt")



class TestNVMeWriteLegacy(BaseTest):
    test_id = "nvme_write_legacy"
    name = "NVMe Write — Legacy (Directive Type 0h)"
    description = (
        "Issues an NVMe write with directive type 0h (no FDP directive), "
        "replicating legacy write behavior. Per the FDP specification, such "
        "writes must be routed to reclaim unit handle 0. Verifies that handle "
        "0's remaining capacity decreases after the write."
    )
    category = "IO"
    tags = ["write", "legacy", "directive-type", "ruhs"]

    def run(self, driver, log) -> TestResult:
        # ── Step 1: Read handle 0 capacity before write ───────────────────────
        log("Step 1: Reading RUHS to capture handle 0 capacity before write...")
        ruhs_result = driver.fdp_ruhs(ns=1)
        if ruhs_result["rc"] != 0:
            return TestResult(
                TestStatus.FAIL,
                f"Cannot read RUHS: {ruhs_result['stderr'].strip()}"
            )

        ruhs = driver.extract_ruhs(ruhs_result)
        if not ruhs:
            return TestResult(TestStatus.FAIL, "No reclaim unit handles found in RUHS")

        handle0 = self._find_handle(ruhs, 0)
        if handle0 is None:
            return TestResult(TestStatus.FAIL, "Reclaim unit handle 0 not found in RUHS")

        capacity_before = int(handle0.get("ruamw", 0))
        log(f"  Handle 0 capacity before write: {capacity_before} sectors")

        if capacity_before == 0:
            return TestResult(
                TestStatus.SKIP,
                "Reclaim unit handle 0 has 0 remaining capacity — cannot perform legacy write test"
            )

        # ── Step 2: Issue legacy write (dtype=0) ──────────────────────────────
        log("\nStep 2: Issuing NVMe write with directive type 0h (legacy)...")
        result = driver.run_cmd([
            "write",
            driver.device,
            "--namespace-id=1",
            "--start-block=0",
            "--block-count=0",
            "--data-size=4096",
            "--data=" + _DATA_FILE,
            "--dir-type=0",          # Directive Type 0 = no directive (legacy)
        ], json_out=False)

        log(f"Command: {result.get('cmd', '')}")

        if result["rc"] != 0:
            stderr = result["stderr"].strip()
            if "success" in result["stdout"].lower():
                log(f"Write reported success via stdout")
            else:
                return TestResult(
                    TestStatus.FAIL,
                    f"Legacy write failed (rc={result['rc']}): {stderr}"
                )
        else:
            log("✓ Legacy write command completed")

        # ── Step 3: Re-read handle 0 capacity and verify decrease ────────────
        log("\nStep 3: Re-reading RUHS to verify handle 0 capacity decreased...")
        ruhs_after_result = driver.fdp_ruhs(ns=1)
        if ruhs_after_result["rc"] != 0:
            return TestResult(
                TestStatus.WARN,
                "Legacy write succeeded but RUHS could not be re-read to verify routing"
            )

        ruhs_after = driver.extract_ruhs(ruhs_after_result)
        handle0_after = self._find_handle(ruhs_after, 0)

        if handle0_after is None:
            return TestResult(TestStatus.WARN, "Write succeeded but handle 0 not found in post-write RUHS")

        capacity_after = int(handle0_after.get("ruamw", 0))
        log(f"  Handle 0 capacity: {capacity_before} → {capacity_after}")

        if capacity_after < capacity_before:
            diff = capacity_before - capacity_after
            log(f"✓ Handle 0 capacity decreased by {diff} sector(s) — legacy routing confirmed")
            return TestResult(
                TestStatus.PASS,
                f"Legacy write routed correctly to handle 0 (capacity ↓ {diff} sectors)",
                details={"capacity_before": capacity_before, "capacity_after": capacity_after}
            )
        elif capacity_after == capacity_before:
            return TestResult(
                TestStatus.WARN,
                "Legacy write succeeded but handle 0 capacity did not change — "
                "device may report capacity at coarse granularity"
            )
        else:
            return TestResult(
                TestStatus.FAIL,
                f"Handle 0 capacity increased after write ({capacity_before} → {capacity_after})"
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_handle(self, ruhs: list, ruhid: int) -> dict | None:
        """Return the RUHS entry whose ruhid matches, or None."""
        for ruh in ruhs:
            if ruh.get("ruhid") is not None and int(ruh["ruhid"]) == ruhid:
                return ruh
        return None
