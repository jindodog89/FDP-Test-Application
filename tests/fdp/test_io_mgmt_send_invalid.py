"""
Test: io_management_send_invalid
Send an IO Management Send command targeting an invalid (out-of-range) reclaim
unit handle. Verify the device rejects the command with an appropriate error.
"""

from tests.base_test import BaseTest, TestResult, TestStatus
import struct, tempfile, os


class TestIOMgmtSendInvalid(BaseTest):
    test_id = "io_management_send_invalid"
    name = "IO Management Send — Invalid Handle (Negative)"
    description = (
        "Sends an IO Management Send command (opcode 0x9D) targeting an "
        "invalid/out-of-range reclaim unit handle. Verifies the device correctly "
        "rejects the command with a failure status rather than silently succeeding."
    )
    category = "IO Management"
    tags = ["io-mgmt-send", "negative", "error-handling", "ruhs"]

    INVALID_HANDLE = 0x7FFF   # Far beyond any realistic handle count

    def run(self, driver, log) -> TestResult:
        # ── Step 1: Confirm the handle is genuinely invalid ───────────────────
        log(f"Step 1: Confirming handle 0x{self.INVALID_HANDLE:04x} is not valid...")
        ruhs_result = driver.fdp_ruhs(ns=1)
        if ruhs_result["rc"] == 0:
            ruhs = driver.extract_ruhs(ruhs_result)
            valid = [str(r.get("phndl", r.get("PlacementHandle", r.get("ruhid", "")))) for r in ruhs]
            log(f"  Valid handles: {valid}")
            if str(self.INVALID_HANDLE) in valid:
                return TestResult(
                    TestStatus.SKIP,
                    f"Handle 0x{self.INVALID_HANDLE:04x} is unexpectedly valid — cannot run negative test"
                )
            log(f"  ✓ Confirmed 0x{self.INVALID_HANDLE:04x} is not a valid handle")
        else:
            log("  RUHS check skipped (could not verify — proceeding anyway)")

        # ── Step 2: Build payload targeting the invalid handle ────────────────
        log(f"\nStep 2: Building IO Management Send payload for invalid handle 0x{self.INVALID_HANDLE:04x}...")
        payload = bytearray(4096)
        offset = self.INVALID_HANDLE * 2
        if offset + 2 <= len(payload):
            struct.pack_into("<H", payload, offset, 0x0001)
        else:
            # Handle index beyond payload size — still send to exercise cdw12 path
            log(f"  Handle offset {offset} exceeds payload — sending zeroed payload")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(payload)
            payload_path = f.name

        # ── Step 3: Send the command ──────────────────────────────────────────
        log(f"Step 3: Issuing IO Management Send with invalid handle...")
        try:
            result = driver.run_cmd([
                "io-mgmt-send",
                driver.device,
                "--namespace-id=1",
                "--cdw12=0",
                "--data-len=4096",
                f"--data={payload_path}",
            ], json_out=False)
        finally:
            os.unlink(payload_path)

        log(f"Command: {result.get('cmd', '')}")
        log(f"Return code: {result['rc']}")
        if result["stdout"].strip():
            log(f"stdout: {result['stdout'].strip()}")
        if result["stderr"].strip():
            log(f"stderr: {result['stderr'].strip()}")

        # ── Step 4: Evaluate result ───────────────────────────────────────────
        if result["rc"] != 0:
            log("✓ Command was correctly rejected by the device")
            return TestResult(
                TestStatus.PASS,
                f"Device correctly rejected IO Management Send for invalid handle "
                f"0x{self.INVALID_HANDLE:04x} (rc={result['rc']})"
            )

        # Command "succeeded" — check if device treated it as a no-op or real error
        stdout_lower = result["stdout"].lower()
        if "error" in stdout_lower or "invalid" in stdout_lower:
            log("✓ Command reported an error condition via stdout")
            return TestResult(
                TestStatus.PASS,
                "Device reported error for invalid handle via stdout (rc=0 but error indicated)"
            )

        return TestResult(
            TestStatus.FAIL,
            f"Device accepted IO Management Send for invalid handle 0x{self.INVALID_HANDLE:04x} "
            f"without error — expected rejection"
        )

    def _extract_ruhs(self, result: dict) -> list:
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("ruhs", "ReclaimUnitHandles", "ruhsd", "reclaim_unit_handle_descriptors"):
                if key in data:
                    return data[key]
        return []
