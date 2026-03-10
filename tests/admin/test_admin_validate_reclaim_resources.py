"""
Case: Validate Reclaim Resources (NRG & NRUH)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateReclaimResources(BaseTest):
    test_id = "admin_validate_reclaim_resources"
    name = "Validate Reclaim Resources (NRG & NRUH)"
    description = "Reads NRG and NRUH from the FDP Configuration Descriptor and ensures both are >= 1."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Retrieving FDP Configurations...")
        log_res = driver.fdp_configs()
        
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to retrieve FDP configs.")

        configs = log_res.get("data", {}).get("fdp_configurations", log_res.get("data", {}).get("configurations", []))
        if not configs:
            return TestResult(TestStatus.SKIP, "No FDP Configurations found.")

        first_config = configs[0]
        nrg = int(first_config.get("nrg", first_config.get("num_reclaim_groups", 0)))
        nruh = int(first_config.get("nruh", first_config.get("num_reclaim_unit_handles", 0)))

        log(f"Step 2: Validating limits. Found NRG: {nrg}, NRUH: {nruh}...")
        
        if nrg >= 1 and nruh >= 1:
            log("✓ Both NRG and NRUH are >= 1 as expected.")
            return TestResult(TestStatus.PASS, f"Reclaim resources valid: NRG={nrg}, NRUH={nruh}.")
        else:
            log("✗ Validation failed. Either NRG or NRUH is less than 1.")
            return TestResult(TestStatus.FAIL, f"Invalid Reclaim Resources: NRG={nrg}, NRUH={nruh}.")