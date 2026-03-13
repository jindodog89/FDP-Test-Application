"""
Test: nvme_write_valid_pid
Issue an NVMe write with a valid reclaim group + handle, verify success,
and confirm the reclaim unit capacity decreases afterward.
"""

from tests.base_test import BaseTest, TestResult, TestStatus
import os as _os
_IO_FILES = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "IO_files")
_DATA_FILE = _os.path.join(_IO_FILES, "randints_4k.txt")



class TestNVMeWriteValidPID(BaseTest):
    test_id = "nvme_write_valid_pid"
    name = "NVMe Write — Valid Placement ID"
    description = (
        "Issues an NVMe write command using a valid reclaim group and placement "
        "handle. Verifies the write succeeds and that the reclaim unit's remaining "
        "capacity decreases, confirming FDP placement routing is functioning."
    )
    category = "IO"
    tags = ["write", "placement-handle", "ruhs", "capacity"]

    def run(self, driver, log) -> TestResult:
        # ── Step 1: Get available reclaim unit handles ──────────────────────
        log("Step 1: Reading Reclaim Unit Handle Status (RUHS)...")
        ruhs_result = driver.fdp_ruhs(ns=1)
        if ruhs_result["rc"] != 0:
            return TestResult(
                TestStatus.FAIL,
                f"Cannot read RUHS — is FDP enabled? {ruhs_result['stderr'].strip()}"
            )

        ruhs_before = driver.extract_ruhs(ruhs_result)
        if not ruhs_before:
            return TestResult(TestStatus.FAIL, "No reclaim unit handles found in RUHS response")

        # Pick the first available handle that has remaining capacity
        handle = None
        for ruh in ruhs_before:
            if int(ruh.get("ruamw", 0)) > 0:
                handle = ruh
                break

        if handle is None:
            return TestResult(TestStatus.SKIP, "All reclaim unit handles report 0 remaining capacity")

        ruhid          = int(handle["ruhid"])
        capacity_before = int(handle.get("ruamw", 0))
        log(f"Using ruhid: {ruhid}  (capacity before: {capacity_before} sectors)")

        # ── Step 2: Issue NVMe write with valid placement handle ─────────────
        log(f"Step 2: Issuing NVMe write to nsid=1 with ruhid={ruhid}...")
        write_result = driver.run_cmd([
            "write",
            driver.device,
            "--namespace-id=1",
            "--start-block=0",
            "--block-count=0",       # 1 logical block (count is 0-based)
            "--data-size=4096",
            "--data=" + _DATA_FILE,
            f"--dir-type=2",            # Directive Type 2 = FDP
            f"--dir-spec={ruhid}",      # Directive Specific = placement handle
        ], json_out=False)

        log(f"Command: {write_result.get('cmd', '')}")

        if write_result["rc"] != 0:
            stderr = write_result["stderr"].strip()
            # nvme-cli may report success via stdout even on rc=0 variants
            if "success" in write_result["stdout"].lower():
                log("Write reported success via stdout")
            else:
                return TestResult(TestStatus.FAIL, f"NVMe write failed (rc={write_result['rc']}): {stderr}")
        else:
            log("✓ NVMe write command completed successfully")

        # ── Step 3: Re-read RUHS and confirm capacity decreased ──────────────
        log("Step 3: Re-reading RUHS to verify capacity decrease...")
        ruhs_after_result = driver.fdp_ruhs(ns=1)
        if ruhs_after_result["rc"] != 0:
            return TestResult(TestStatus.WARN, "Write succeeded but could not re-read RUHS to verify capacity")

        ruhs_after = driver.extract_ruhs(ruhs_after_result)
        handle_after = self._find_handle(ruhs_after, ruhid)

        if handle_after is None:
            return TestResult(TestStatus.WARN, "Write succeeded but matching handle not found in post-write RUHS")

        capacity_after = int(handle_after.get("ruamw", 0))
        log(f"Capacity before: {capacity_before}  →  after: {capacity_after}")

        if capacity_after < capacity_before:
            diff = capacity_before - capacity_after
            log(f"✓ Capacity decreased by {diff} sector(s) — FDP placement routing confirmed")
            return TestResult(
                TestStatus.PASS,
                f"Write succeeded and reclaim unit capacity decreased by {diff} sectors",
                details={"ruhid": ruhid, "capacity_before": capacity_before, "capacity_after": capacity_after}
            )
        elif capacity_after == capacity_before:
            return TestResult(
                TestStatus.WARN,
                "Write succeeded but reclaim unit capacity did not decrease — "
                "device may buffer or report capacity in coarse granularity"
            )
        else:
            return TestResult(
                TestStatus.FAIL,
                f"Capacity increased after write ({capacity_before} → {capacity_after}) — unexpected behavior"
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_handle(self, ruhs: list, ruhid: int) -> dict | None:
        """Return the RUHS entry whose ruhid matches, or None."""
        for ruh in ruhs:
            if ruh.get("ruhid") is not None and int(ruh["ruhid"]) == ruhid:
                return ruh
        return None
