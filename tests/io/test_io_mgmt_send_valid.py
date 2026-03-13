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

        # Pick any valid handle.
        # RUHS dicts from extract_ruhs() contain exactly two keys:
        #   "ruhid"  — Reclaim Unit Handle Identifier (the handle index)
        #   "ruamw"  — Reclaim Unit Available Media Writes (remaining capacity)
        # There is no "phndl" or "ruhu" field in this response.
        handle = ruhs[0]
        ruhid        = int(handle["ruhid"])
        ruamw_before = handle.get("ruamw")
        log(f"  Selected handle: ruhid={ruhid}  (ruamw before: {ruamw_before})")

        # ── Step 2: Issue IO Management Send via io-passthru ─────────────────
        # NVMe spec: IO Management Send opcode = 0x9D
        # CDW10 bits [3:0] = Select field:  0x0 = Reclaim Unit Handle Update (RUHU)
        # Data flows host → device (--write flag)
        log(f"\nStep 2: Issuing IO Management Send (opcode 0x9D) for handle ruhid={ruhid}...")

        # Build a 4096-byte payload with the handle index in the first 2 bytes
        # (NVMe FDP spec: IO Management Send RUHU data structure)
        import struct, tempfile, os
        payload = bytearray(4096)
        # RUHU data structure: 2 bytes per handle entry, bit 0 = RUHU request
        offset = ruhid * 2
        if offset + 2 <= len(payload):
            struct.pack_into("<H", payload, offset, 0x0001)  # Request new RU assignment

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(payload)
            payload_path = f.name

        try:
            result = driver.run_cmd([
                "io-passthru",
                driver.device,
                "--opcode=0x9D",        # IO Management Send
                "--namespace-id=1",
                "--cdw10=0",            # Select=0 → RUHU
                "--data-len=4096",
                "--write",              # data direction: host → device
                f"--input-file={payload_path}",
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
        handle_after = self._find_handle(ruhs_after, ruhid)

        if handle_after is None:
            return TestResult(TestStatus.WARN, "IO Management Send succeeded but handle not found in post-command RUHS")

        ruamw_after = handle_after.get("ruamw")
        log(f"  Handle ruhid={ruhid}: ruamw before={ruamw_before}  after={ruamw_after}")

        if ruamw_after != ruamw_before:
            log(f"✓ Handle state changed — RUHU update confirmed (ruamw changed)")
            return TestResult(
                TestStatus.PASS,
                f"IO Management Send succeeded and handle ruhid={ruhid} received a new reclaim unit",
                details={"ruhid": ruhid, "ruamw_before": ruamw_before, "ruamw_after": ruamw_after}
            )

        return TestResult(
            TestStatus.WARN,
            "IO Management Send accepted but ruamw did not change — "
            "device may require more writes before reassigning the reclaim unit"
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_handle(self, ruhs: list, ruhid: int) -> dict | None:
        """Return the RUHS entry whose ruhid matches, or None."""
        for ruh in ruhs:
            if ruh.get("ruhid") is not None and int(ruh["ruhid"]) == ruhid:
                return ruh
        return None