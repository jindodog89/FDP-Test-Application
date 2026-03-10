"""
Case: Validate Reclaim Group Identifier Format (RGIF)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateRGIF(BaseTest):
    test_id = "admin_validate_rgif"
    name = "Validate Reclaim Group Identifier Format (RGIF)"
    description = "Verifies that RGIF provides enough bits to address all Reclaim Groups (NRG)."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        log_res = driver.fdp_configs()
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to retrieve FDP configs.")

        configs = log_res.get("data", {}).get("fdp_configurations", log_res.get("data", {}).get("configurations", []))
        if not configs:
            return TestResult(TestStatus.SKIP, "No FDP Configurations found.")

        first_config = configs[0]
        nrg = int(first_config.get("nrg", 0))
        rgif = int(first_config.get("rgif", 0))

        log(f"Found NRG: {nrg}, RGIF: {rgif}")

        if nrg > 1 and rgif == 0:
            log("✗ NRG > 1 but RGIF is 0. Insufficient bits to address Reclaim Groups.")
            return TestResult(TestStatus.FAIL, f"Invalid RGIF: NRG={nrg}, RGIF={rgif}")
        elif nrg == 1 and rgif >= 0:
             log("✓ NRG = 1, RGIF is valid.")
             return TestResult(TestStatus.PASS, f"RGIF validated. NRG={nrg}, RGIF={rgif}")
        elif nrg > 1 and rgif > 0:
             log("✓ NRG > 1 and RGIF > 0. Sufficient bit formatting provided.")
             return TestResult(TestStatus.PASS, f"RGIF validated. NRG={nrg}, RGIF={rgif}")
        
        return TestResult(TestStatus.WARN, f"Unexpected NRG/RGIF combination: NRG={nrg}, RGIF={rgif}")