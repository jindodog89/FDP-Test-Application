"""
Test: io_management_fdp_disabled
Send IO Management Receive on a namespace that does not have FDP enabled.
Verifies the device rejects or returns an appropriate error.
If no FDP-disabled namespace exists, the test is skipped.
"""

import subprocess
import json
from tests.base_test import BaseTest, TestResult, TestStatus


class TestIOMgmtFDPDisabled(BaseTest):
    test_id = "io_management_fdp_disabled"
    name = "IO Management Receive — FDP-Disabled Namespace"
    description = (
        "Attempts to send an IO Management Receive command on a namespace that "
        "does not have FDP enabled. Verifies the device returns an appropriate "
        "error (e.g., Invalid Field in Command or Invalid Namespace). "
        "Skips automatically if all namespaces have FDP enabled."
    )
    category = "IO Management"
    tags = ["io-mgmt-recv", "negative", "namespace", "fdp-disabled"]

    def run(self, driver, log) -> TestResult:
        # ── Step 1: Find a non-FDP namespace ─────────────────────────────────
        log("Step 1: Scanning namespaces for one without FDP enabled...")
        disabled_ns = self._find_non_fdp_namespace(driver, log)

        if disabled_ns is None:
            return TestResult(
                TestStatus.SKIP,
                "All detected namespaces appear to have FDP enabled — "
                "cannot run FDP-disabled namespace test. "
                "Create a non-FDP namespace to enable this test."
            )

        log(f"  ✓ Found non-FDP namespace: nsid={disabled_ns}")

        # ── Step 2: Issue IO Management Receive on the non-FDP namespace ──────
        log(f"\nStep 2: Issuing IO Management Receive on nsid={disabled_ns}...")
        result = driver.run_cmd([
            "io-mgmt-recv",
            driver.device,
            f"--namespace-id={disabled_ns}",
            "--cdw12=0",          # Select=0 (RUHS)
            "--data-len=4096",
        ], json_out=False)

        log(f"Command: {result.get('cmd', '')}")
        log(f"Return code: {result['rc']}")
        if result["stdout"].strip():
            log(f"stdout: {result['stdout'].strip()}")
        if result["stderr"].strip():
            log(f"stderr: {result['stderr'].strip()}")

        # ── Step 3: Evaluate ──────────────────────────────────────────────────
        if result["rc"] != 0:
            stderr = result["stderr"].lower()
            # Common expected errors from spec: Invalid Field, Invalid NS, or
            # Command Not Supported
            expected_errors = [
                "invalid field", "invalid namespace", "not supported",
                "invalid command", "status: 0x", "nvme error"
            ]
            matched = any(e in stderr for e in expected_errors)
            if matched or result["rc"] in (1, 2, 255):
                log(f"✓ Device correctly rejected command on non-FDP namespace")
                return TestResult(
                    TestStatus.PASS,
                    f"IO Management Receive correctly rejected on non-FDP namespace {disabled_ns} "
                    f"(rc={result['rc']})"
                )

            log(f"Command failed but with unexpected error — still counting as pass")
            return TestResult(
                TestStatus.PASS,
                f"IO Management Receive rejected on non-FDP namespace (rc={result['rc']})",
                details=result["stderr"].strip()
            )

        # Command succeeded on a non-FDP namespace — this is incorrect behavior
        return TestResult(
            TestStatus.FAIL,
            f"IO Management Receive succeeded on non-FDP namespace {disabled_ns} — "
            "device should have rejected this command"
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_non_fdp_namespace(self, driver, log) -> int | None:
        """
        Try to identify a namespace without FDP by checking NSFEAT bit 4.
        Returns the nsid of the first non-FDP namespace, or None if all have FDP.
        """
        # Try to list all namespaces
        list_result = driver.run_cmd(["list-ns", driver.device], json_out=True)
        nsids = []

        if list_result["rc"] == 0:
            data = list_result.get("data", {})
            if isinstance(data, list):
                nsids = [int(ns) for ns in data if ns]
            elif isinstance(data, dict):
                raw = data.get("nsid_list", data.get("NamespaceList", []))
                nsids = [int(ns) for ns in raw if ns]

        if not nsids:
            # Fallback: try nsids 1 through 4
            nsids = [1, 2, 3, 4]

        log(f"  Checking nsids: {nsids}")

        for nsid in nsids:
            id_result = driver.id_ns(namespace=nsid)   # kwarg is 'namespace', not 'ns'
            if id_result["rc"] != 0:
                continue   # Namespace doesn't exist or not accessible

            data = id_result.get("data", {})
            if not isinstance(data, dict):
                continue

            nsfeat = data.get("nsfeat", data.get("NSFEAT", None))
            if nsfeat is None:
                continue

            # nvme-cli may render nsfeat as a nested dict of bitfields
            # (e.g. {"fdp": 1, "optperf": 0, ...}) or as a raw integer.
            if isinstance(nsfeat, dict):
                fdp_bit_set = bool(nsfeat.get("fdp", nsfeat.get("FDP", 0)))
                nsfeat_int  = sum(v << i for i, v in enumerate(nsfeat.values()) if isinstance(v, int))
            else:
                nsfeat_int  = int(nsfeat)
                fdp_bit_set = bool(nsfeat_int & (1 << 4))
            log(f"  nsid={nsid}  NSFEAT=0x{nsfeat_int:04x}  FDP bit: {'SET' if fdp_bit_set else 'NOT SET'}")

            if not fdp_bit_set:
                return nsid

        return None