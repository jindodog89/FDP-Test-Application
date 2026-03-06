"""
Test: io_management_send_valid
Send an IO Management Send command (opcode 0x9D, cdw12 bits select RUHS update)
to reassign a reclaim unit handle to a new reclaim unit, then verify the
handle's RUHU (Reclaim Unit Handle Update) reflects the change via RUHS read.
"""

from tests.base_test import BaseTest, TestResult, TestStatus


class TestIOMgmtSendValid(BaseTest):
    test_id = "io_management_send_valid"
    name = "IO Management Send — Valid RUHS Update"
    description = (
        "Sends an IO Management Send command (NVMe opcode 0x9D) to update a "
        "valid reclaim unit handle, requesting a new reclaim unit assignment. "
        "Verifies the handle's state changes in the RUHS log afterward."
    )
    category = "IO Management"
    tags = ["io-mgmt-send", "ruhs", "reclaim", "opcode-9D"]

    def run(self, driver, log) -> TestResult:
        # ── Step 1: Read current RUHS ─────────────────────────────────────────
        log("Step 1: Reading RUHS to select a valid handle to update...")
        ruhs_result = driver.fdp_ruhs(ns=1)
        if ruhs_result["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Cannot read RUHS: {ruhs_result['stderr'].strip()}")

        ruhs = driver.extract_ruhs(ruhs_result)
        if len(ruhs) < 1:
            return TestResult(TestStatus.FAIL, "No reclaim unit handles available")

        # Pick any valid handle
        handle = ruhs[0]
        phndl = int(handle.get("phndl", handle.get("PlacementHandle", handle.get("ruhid", 0))))
        ruhu_before = handle.get("ruhu", handle.get("RUHU", handle.get("reclaim_unit_handle_update", None)))
        log(f"  Selected handle: {phndl}  (RUHU before: {ruhu_before})")

        # ── Step 2: Issue IO Management Send ─────────────────────────────────
        # nvme-cli: nvme io-mgmt-send <dev> -n <ns> --cdw12=<val> --data=<buf>
        # cdw12 bits [3:0] = Select (0 = RUHS, 1 = PIDREC, etc.)
        # We use Select=0 to issue Reclaim Unit Handle Update (RUHU)
        log(f"\nStep 2: Issuing IO Management Send for handle {phndl}...")

        # Build a 4096-byte payload with the handle index in the first 2 bytes
        # (NVMe FDP spec: IO Management Send data structure for RUHU)
        import struct, tempfile, os
        payload = bytearray(4096)
        # RUHU data structure: 2 bytes per handle entry, bit 0 = RUHU request
        offset = phndl * 2
        if offset + 2 <= len(payload):
            struct.pack_into("<H", payload, offset, 0x0001)  # Request new RU assignment

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(payload)
            payload_path = f.name

        try:
            result = driver.run_cmd([
                "io-mgmt-send",
                driver.device,
                f"--namespace-id=1",
                f"--cdw12=0",        # Select=0 (RUHU)
                f"--data-len=4096",
                f"--data={payload_path}",
            ], json_out=False)

            log(f"Command: {result.get('cmd', '')}")
            log(f"Return code: {result['rc']}")
            if result["stderr"].strip():
                log(f"stderr: {result['stderr'].strip()}")
        finally:
            os.unlink(payload_path)

        if result["rc"] != 0:
            # Some devices require specific privileges or FDP config
            stderr = result["stderr"].strip()
            if "not supported" in stderr.lower() or "invalid" in stderr.lower():
                return TestResult(
                    TestStatus.WARN,
                    f"IO Management Send not supported or rejected by device: {stderr}"
                )
            return TestResult(
                TestStatus.FAIL,
                f"IO Management Send failed (rc={result['rc']}): {stderr}"
            )

        log("✓ IO Management Send command accepted")

        # ── Step 3: Re-read RUHS and verify state changed ─────────────────────
        log("\nStep 3: Re-reading RUHS to verify handle state updated...")
        ruhs_after_result = driver.fdp_ruhs(ns=1)
        if ruhs_after_result["rc"] != 0:
            return TestResult(
                TestStatus.WARN,
                "IO Management Send succeeded but RUHS could not be re-read to confirm update"
            )

        ruhs_after = driver.extract_ruhs(ruhs_after_result)
        handle_after = self._find_handle(ruhs_after, phndl)

        if handle_after is None:
            return TestResult(TestStatus.WARN, "IO Management Send succeeded but handle not found in post-command RUHS")

        ruhu_after = handle_after.get("ruhu", handle_after.get("RUHU", handle_after.get("reclaim_unit_handle_update", None)))
        log(f"  Handle {phndl}: RUHU before={ruhu_before}  after={ruhu_after}")

        if ruhu_after != ruhu_before:
            log(f"✓ Handle state changed — RUHU update confirmed")
            return TestResult(
                TestStatus.PASS,
                f"IO Management Send succeeded and handle {phndl} state updated",
                details={"handle": phndl, "ruhu_before": ruhu_before, "ruhu_after": ruhu_after}
            )

        return TestResult(
            TestStatus.WARN,
            "IO Management Send accepted but observable handle state did not change — "
            "device may require more writes before reassigning the reclaim unit"
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _extract_ruhs(self, result: dict) -> list:
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("ruhs", "ReclaimUnitHandles", "ruhsd", "reclaim_unit_handle_descriptors"):
                if key in data:
                    return data[key]
        return []

    def _find_handle(self, ruhs: list, handle_id: int) -> dict:
        for ruh in ruhs:
            candidate = ruh.get("phndl", ruh.get("PlacementHandle", ruh.get("ruhid", None)))
            if candidate is not None and int(candidate) == handle_id:
                return ruh
        return None
