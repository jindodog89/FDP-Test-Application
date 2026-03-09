"""
Test: nvme_write_invalid_pid
Issue an NVMe write with a deliberately invalid placement handle and verify
that the device logs an Invalid Placement Identifier event (FDP event type 1).
"""

from tests.base_test import BaseTest, TestResult, TestStatus


class TestNVMeWriteInvalidPID(BaseTest):
    test_id = "nvme_write_invalid_pid"
    name = "NVMe Write — Invalid Placement ID"
    description = (
        "Issues an NVMe write using a deliberately invalid reclaim group or "
        "placement handle. Verifies the device logs an 'Invalid Placement "
        "Identifier' FDP event (event type 0x1) in the FDP Events log."
    )
    category = "IO"
    tags = ["write", "negative", "events", "placement-handle", "error-handling"]

    # An intentionally out-of-range handle. NVMe spec max placement handles = 128.
    INVALID_HANDLE = 0xFFFF

    def run(self, driver, log) -> TestResult:
        # ── Step 1: Read FDP events log before the write ─────────────────────
        log("Step 1: Reading FDP events log (baseline)...")
        events_before = self._read_events(driver, log)
        invalid_events_before = self._count_invalid_pid_events(events_before)
        log(f"  Baseline invalid PID events: {invalid_events_before}")

        # ── Step 2: Confirm the handle is actually invalid ────────────────────
        log(f"\nStep 2: Verifying handle 0x{self.INVALID_HANDLE:04x} is not a valid RUHS entry...")
        ruhs_result = driver.fdp_ruhs(ns=1)
        if ruhs_result["rc"] == 0:
            ruhs = driver.extract_ruhs(ruhs_result)
            valid_handles = [
                str(r.get("phndl", r.get("PlacementHandle", r.get("ruhid", ""))))
                for r in ruhs
            ]
            log(f"  Valid handles on device: {valid_handles}")
            if str(self.INVALID_HANDLE) in valid_handles:
                log(f"  ⚠ Handle {self.INVALID_HANDLE} unexpectedly exists — choosing a higher value")
                # This is extremely unlikely but handle it gracefully
                return TestResult(
                    TestStatus.SKIP,
                    f"Handle 0x{self.INVALID_HANDLE:04x} is unexpectedly valid on this device"
                )
            log(f"  ✓ Confirmed 0x{self.INVALID_HANDLE:04x} is not a valid handle")

        # ── Step 3: Issue write with invalid handle ───────────────────────────
        log(f"\nStep 3: Issuing NVMe write with invalid placement handle 0x{self.INVALID_HANDLE:04x}...")
        result = driver.run_cmd([
            "write",
            driver.device,
            "--namespace-id=1",
            "--start-block=0",
            "--block-count=0",
            "--data-size=4096",
            "--data=/dev/zero",
            "--dtype=2",
            f"--dspec={self.INVALID_HANDLE}",
        ], json_out=False)

        log(f"Command: {result.get('cmd', '')}")
        log(f"Return code: {result['rc']}")
        if result["stderr"].strip():
            log(f"stderr: {result['stderr'].strip()}")

        # The write may succeed at command level (device accepts then logs the event)
        # or may fail immediately — both are acceptable per spec
        if result["rc"] != 0:
            log("Device rejected write at command level (acceptable behavior)")
        else:
            log("Device accepted command (event logging path expected)")

        # ── Step 4: Check FDP events log for new Invalid PID event ───────────
        log("\nStep 4: Re-reading FDP events log to check for Invalid PID event...")
        events_after = self._read_events(driver, log)
        invalid_events_after = self._count_invalid_pid_events(events_after)
        log(f"  Invalid PID events after write: {invalid_events_after}")

        new_events = invalid_events_after - invalid_events_before
        if new_events > 0:
            log(f"✓ {new_events} new Invalid Placement Identifier event(s) logged")
            return TestResult(
                TestStatus.PASS,
                f"Device correctly logged {new_events} Invalid Placement Identifier event(s)",
                details={"invalid_pid_events_before": invalid_events_before,
                         "invalid_pid_events_after": invalid_events_after}
            )

        # Event not logged — could be device doesn't support event logging
        if result["rc"] != 0:
            return TestResult(
                TestStatus.WARN,
                "Write was rejected (correct) but no FDP event was logged — "
                "device may not support FDP event logging for this error type"
            )

        return TestResult(
            TestStatus.FAIL,
            "Write with invalid PID did not produce an Invalid Placement Identifier FDP event"
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _read_events(self, driver, log) -> list:
        result = driver.fdp_events(ns=1)
        if result["rc"] != 0:
            log(f"  Could not read events: {result['stderr'].strip()}")
            return []
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("events", "FdpEvents", "fdp_events"):
                if key in data:
                    return data[key]
        return []

    def _count_invalid_pid_events(self, events: list) -> int:
        count = 0
        for e in events:
            etype = e.get("etype", e.get("EventType", e.get("type", "")))
            # FDP event type 0x1 = Invalid Placement Identifier
            if str(etype) in ("1", "0x1", "invalid_pid", "InvalidPlacementIdentifier"):
                count += 1
        return count
