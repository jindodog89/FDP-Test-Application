"""
Case: Read FDP Configurations (Log 20h)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminReadFDPConfigsLog(BaseTest):
    test_id = "admin_read_fdp_configs_log"
    name = "A25. Read FDP Configurations (Log 20h)"
    description = "Issues Get Log Page with LID 20h using the standard Get Log wrapper."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "positive"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        log("Step 1: Issuing Get Log Page with LID 0x20...")
        # LSI (Log Specific Identifier) must be set to the Endurance Group ID
        # for FDP log pages (NVMe FDP spec requirement)
        log_res = driver.get_log(log_id=0x20, lsi=endgrp)
        
        if log_res["rc"] == 0:
            data = log_res.get("data", {})
            # nvme get-log may return raw bytes as a string for log 0x20 on some
            # devices — fall back to fdp_configs() which always returns clean JSON.
            if not isinstance(data, dict):
                log("  get-log returned non-JSON — falling back to 'nvme fdp configs'...")
                log_res = driver.fdp_configs(endgrp=endgrp)
                data = log_res.get("data", {}) if log_res["rc"] == 0 else {}
            if isinstance(data, dict) and data:
                log("✓ Command succeeded. Controller returned FDP Configuration Descriptors.")
                return TestResult(TestStatus.PASS, "Successfully read Log 20h.", details=data)
            else:
                log("⚠ Command succeeded but returned empty or unparseable output.")
                return TestResult(TestStatus.WARN, "Log 20h read succeeded but parser returned empty output.")
        else:
            log(f"✗ Command failed: {log_res['stderr']}")
            return TestResult(TestStatus.FAIL, "Failed to issue Get Log Page for LID 0x20.")