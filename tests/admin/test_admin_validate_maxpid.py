"""
Case: Validate Max Placement Identifiers (MAXPID)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateMAXPID(BaseTest):
    test_id = "admin_validate_maxpid"
    name = "Validate Max Placement Identifiers (MAXPID)"
    description = "Reads MAXPID from the descriptor and compares it with NRG to ensure it is >= NRG."
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
        maxpid = int(first_config.get("maxpids", first_config.get("maxpid", 0)))

        log(f"Comparing MAXPID ({maxpid}) against NRG ({nrg})...")

        if maxpid >= nrg:
            log("✓ MAXPID is >= NRG.")
            return TestResult(TestStatus.PASS, f"MAXPID ({maxpid}) correctly accommodates NRG ({nrg}).")
        else:
            log("✗ MAXPID is less than NRG, which violates specification expectations.")
            return TestResult(TestStatus.FAIL, f"MAXPID ({maxpid}) < NRG ({nrg}).")