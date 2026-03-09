"""
Test: nvme_write_user_controlled
NVMe write where the user can configure placement ID, LBA range, block count,
and data size via test parameters exposed in the UI.
"""

from tests.base_test import BaseTest, TestResult, TestStatus


class TestNVMeWriteUserControlled(BaseTest):
    test_id = "nvme_write_user_controlled"
    name = "NVMe Write — User Controlled Parameters"
    description = (
        "Issues an NVMe write command with fully user-configurable parameters: "
        "placement handle, starting LBA, number of LBAs, and data size. "
        "Useful for targeted testing of specific regions and placement handles."
    )
    category = "IO"
    tags = ["write", "configurable", "placement-handle", "lba"]

    # These defaults can be overridden via self.params in future UI integration
    DEFAULT_PARAMS = {
        "namespace":     1,
        "start_lba":     0,
        "block_count":   0,       # 0 = 1 block (nvme-cli uses 0-based count)
        "data_size":     4096,    # bytes
        "placement_handle": 0,
        "data_source":   "/dev/zero",
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        log("User-controlled NVMe write parameters:")
        log(f"  Namespace:         {p['namespace']}")
        log(f"  Starting LBA:      {p['start_lba']}")
        log(f"  Block count:       {p['block_count']} (0 = 1 block)")
        log(f"  Data size:         {p['data_size']} bytes")
        log(f"  Placement handle:  {p['placement_handle']}")
        log(f"  Data source:       {p['data_source']}")

        # ── Validate params ──────────────────────────────────────────────────
        if p["data_size"] <= 0 or p["data_size"] % 512 != 0:
            return TestResult(TestStatus.FAIL, f"Invalid data_size {p['data_size']} — must be a positive multiple of 512")
        if p["block_count"] < 0:
            return TestResult(TestStatus.FAIL, "block_count must be >= 0")
        if p["placement_handle"] < 0 or p["placement_handle"] > 65535:
            return TestResult(TestStatus.FAIL, "placement_handle must be in range 0–65535")

        # ── Confirm handle exists ────────────────────────────────────────────
        log(f"\nVerifying placement handle {p['placement_handle']} exists in RUHS...")
        ruhs_result = driver.fdp_ruhs(ns=p["namespace"])
        if ruhs_result["rc"] == 0:
            ruhs = driver.extract_ruhs(ruhs_result)
            handles = [
                str(r.get("phndl", r.get("PlacementHandle", r.get("ruhid", ""))))
                for r in ruhs
            ]
            if handles and str(p["placement_handle"]) not in handles:
                log(f"  Available handles: {handles}")
                return TestResult(
                    TestStatus.FAIL,
                    f"Placement handle {p['placement_handle']} not found in RUHS. Available: {handles}"
                )
            log(f"  ✓ Handle {p['placement_handle']} confirmed in RUHS")
        else:
            log("  RUHS check skipped (could not read RUHS)")

        # ── Issue write ──────────────────────────────────────────────────────
        log(f"\nIssuing NVMe write command...")
        result = driver.run_cmd([
            "write",
            driver.device,
            f"--namespace-id={p['namespace']}",
            f"--start-block={p['start_lba']}",
            f"--block-count={p['block_count']}",
            f"--data-size={p['data_size']}",
            f"--data={p['data_source']}",
            "--dtype=2",                          # FDP directive
            f"--dspec={p['placement_handle']}",
        ], json_out=False)

        log(f"Command: {result.get('cmd', '')}")

        if result["rc"] != 0:
            stderr = result["stderr"].strip()
            stdout = result["stdout"].strip()
            if "success" in stdout.lower():
                log(f"✓ Write reported success: {stdout}")
                return TestResult(TestStatus.PASS, "Write completed successfully", details=p)
            return TestResult(
                TestStatus.FAIL,
                f"Write failed (rc={result['rc']}): {stderr or stdout}",
                details=p
            )

        log(f"✓ Write completed successfully")
        if result["stdout"].strip():
            log(f"  Output: {result['stdout'].strip()}")

        return TestResult(TestStatus.PASS, "User-controlled NVMe write succeeded", details=p)
