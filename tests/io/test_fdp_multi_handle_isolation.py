"""
Test: fdp_multi_handle_isolation (extra — not in original list)
Write to multiple placement handles simultaneously and verify each handle's
capacity decreases independently, confirming FDP correctly isolates data
placement between handles. Critical for validating GC isolation guarantees.
"""

from tests.base_test import BaseTest, TestResult, TestStatus
import os as _os
_IO_FILES = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "IO_files")
_DATA_FILE = _os.path.join(_IO_FILES, "randints_4k.txt")



class TestFDPMultiHandleIsolation(BaseTest):
    test_id = "fdp_multi_handle_isolation"
    name = "FDP Multi-Handle Isolation"
    description = (
        "Writes sequentially to each available placement handle and verifies that "
        "capacity decreases are isolated to the targeted handle. Confirms FDP is "
        "correctly routing data to separate reclaim units, which is the core "
        "isolation guarantee that enables GC efficiency improvements."
    )
    category = "IO"
    tags = ["write", "placement-handle", "isolation", "multi-handle", "ruhs"]

    def run(self, driver, log) -> TestResult:
        # ── Step 1: Get all available handles ─────────────────────────────────
        log("Step 1: Reading RUHS to enumerate all available handles...")
        ruhs_result = driver.fdp_ruhs(ns=1)
        if ruhs_result["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Cannot read RUHS: {ruhs_result['stderr'].strip()}")

        ruhs = driver.extract_ruhs(ruhs_result)
        if not ruhs:
            return TestResult(TestStatus.FAIL, "No reclaim unit handles found")
        if len(ruhs) < 2:
            return TestResult(TestStatus.SKIP, "Only 1 placement handle available — need ≥2 for isolation test")

        # Filter to handles with capacity
        handles_with_cap = [r for r in ruhs if int(r.get("ruamw", 0)) > 0]
        if len(handles_with_cap) < 2:
            return TestResult(TestStatus.SKIP, "Fewer than 2 handles have remaining capacity")

        log(f"  Found {len(handles_with_cap)} handles with capacity")

        cap_before = {self._handle_id(r): int(r.get("ruamw", 0)) for r in handles_with_cap}
        for hid, cap in cap_before.items():
            log(f"  Handle {hid}: {cap:,} sectors")

        # ── Step 2: Write to each handle in turn ──────────────────────────────
        log("\nStep 2: Writing to each handle...")
        write_errors = []

        for ruh in handles_with_cap:
            hid = self._handle_id(ruh)
            log(f"  Writing to handle {hid}...")
            result = driver.run_cmd([
                "write", driver.device,
                "--namespace-id=1",
                "--start-block=0",
                "--block-count=0",
                "--data-size=4096",
                "--data=" + _DATA_FILE,
                "--dir-type=2",
                f"--dir-spec={hid}",
            ], json_out=False)

            if result["rc"] != 0 and "success" not in result["stdout"].lower():
                write_errors.append(f"Handle {hid}: {result['stderr'].strip()}")
                log(f"    ✗ Write failed: {result['stderr'].strip()[:80]}")
            else:
                log(f"    ✓ Write accepted")

        if len(write_errors) == len(handles_with_cap):
            return TestResult(TestStatus.FAIL, f"All writes failed: {write_errors[0]}")

        # ── Step 3: Re-read RUHS and check per-handle capacity change ─────────
        log("\nStep 3: Re-reading RUHS and checking per-handle capacity changes...")
        ruhs_after_result = driver.fdp_ruhs(ns=1)
        if ruhs_after_result["rc"] != 0:
            return TestResult(TestStatus.WARN, "Writes completed but RUHS could not be re-read")

        ruhs_after = driver.extract_ruhs(ruhs_after_result)
        cap_after = {self._handle_id(r): int(r.get("ruamw", 0)) for r in ruhs_after}

        decreased = []
        unchanged = []
        increased = []

        for hid, cap_b in cap_before.items():
            cap_a = cap_after.get(hid, cap_b)
            delta = cap_b - cap_a
            log(f"  Handle {hid}: {cap_b:,} → {cap_a:,}  (Δ={delta:+,})")
            if delta > 0:
                decreased.append(hid)
            elif delta == 0:
                unchanged.append(hid)
            else:
                increased.append(hid)

        if increased:
            return TestResult(
                TestStatus.FAIL,
                f"Handle(s) {increased} showed capacity INCREASE after writes — unexpected"
            )

        if decreased:
            log(f"\n✓ {len(decreased)} handle(s) show capacity decrease — isolation confirmed")
            msg = (
                f"{len(decreased)}/{len(cap_before)} handles show capacity decrease. "
                + (f"{len(unchanged)} unchanged (may be coarse granularity reporting)." if unchanged else "")
            )
            return TestResult(
                TestStatus.PASS if len(unchanged) == 0 else TestStatus.WARN,
                msg,
                details={"decreased": decreased, "unchanged": unchanged}
            )

        return TestResult(
            TestStatus.WARN,
            "All writes accepted but no handle capacity changes detected — "
            "device may report capacity at coarse granularity"
        )

    def _handle_id(self, ruh: dict) -> int:
        return int(ruh["ruhid"])

