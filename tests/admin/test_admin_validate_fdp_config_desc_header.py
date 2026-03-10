"""
Case: Validate FDP Configuration Descriptor Header
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateFDPConfigDescHeader(BaseTest):
    test_id = "admin_validate_fdp_config_desc_header"
    name = "Validate FDP Configuration Descriptor Header"
    description = "Parses the first FDP Configuration Descriptor returned in Log 20h and verifies Descriptor Size and FDP Configuration Index."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Retrieving FDP Configurations (Log 20h)...")
        log_res = driver.fdp_configs()
        
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Failed to retrieve log: {log_res['stderr']}")

        data = log_res.get("data", {})
        configs = data.get("fdp_configurations", data.get("configurations", data.get("configs", [])))

        if not configs:
            return TestResult(TestStatus.SKIP, "No FDP Configurations found to validate.")

        log("Step 2: Parsing the first FDP Configuration Descriptor...")
        first_config = configs[0]
        
        # nvme-cli json output field names vary slightly by version, checking common ones
        ds = int(first_config.get("ds", first_config.get("descriptor_size", 0)))
        fci = first_config.get("fci", first_config.get("fdp_config_index", None))

        log(f"  Descriptor Size (DS): {ds}")
        log(f"  FDP Config Index (FCI): {fci}")

        if ds > 0 and fci is not None:
            log("✓ Descriptor Size is non-zero and Configuration Index is valid.")
            return TestResult(TestStatus.PASS, "FDP Configuration Descriptor Header validated successfully.")
        else:
            log(f"✗ Validation failed. DS: {ds}, FCI: {fci}")
            return TestResult(TestStatus.FAIL, "Descriptor Size is zero or FDP Configuration Index is missing.")