"""
Case: Validate FDP Log Header & Configuration Count
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateFDPConfigsHeader(BaseTest):
    test_id = "admin_validate_fdp_configs_header"
    name = "Validate FDP Log Header & Configuration Count"
    description = "Issues Get Log Page (LID 20h) and validates that the Number of FDP Configurations is >= 1."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Issuing Get Log Page (LID 20h) to read configurations...")
        log_res = driver.get_log(log_id=0x20)
        
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Failed to retrieve log: {log_res['stderr']}")

        # Extract number of configs (nvme-cli json output generally maps these fields natively)
        data = log_res.get("data", {})
        num_configs = data.get("num_fdp_configs", data.get("num_configs", 0))
        
        log(f"Step 2: Validating configuration count (Found: {num_configs})...")
        if int(num_configs) >= 1:
            log("✓ Number of FDP Configurations is >= 1.")
            return TestResult(TestStatus.PASS, f"Log header validated successfully. Configurations count: {num_configs}")
        else:
            log("✗ Number of FDP Configurations is less than 1 or field missing.")
            return TestResult(TestStatus.FAIL, "Log Header validation failed. Configuration count < 1.")