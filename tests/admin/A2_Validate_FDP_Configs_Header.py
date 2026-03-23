"""
Case: Validate FDP Log Header & Configuration Count
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateFDPConfigsHeader(BaseTest):
    test_id = "admin_validate_fdp_configs_header"
    name = "A2. Validate FDP Configs Header"
    description = "Issues Get Log Page (LID 20h) and validates that the Number of FDP Configurations is >= 1."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        log("Step 1: Issuing Get Log Page (LID 20h) to read configurations...")
        # LSI = endurance group ID required for FDP log pages
        log_res = driver.get_log(log_id=0x20, lsi=endgrp)

        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Failed to retrieve log: {log_res['stderr']}")

        # get_log may return raw stdout as a string when nvme-cli outputs non-JSON
        # for Log 0x20 (e.g. binary dump). Fall back to fdp_configs() in that case
        # since it uses the dedicated 'nvme fdp configs' subcommand which always
        # returns well-formed JSON.
        raw_data = log_res.get("data", {})
        if not isinstance(raw_data, dict):
            log("  get-log returned non-JSON output — falling back to 'nvme fdp configs'...")
            log_res = driver.fdp_configs(endgrp=endgrp)
            if log_res["rc"] != 0:
                return TestResult(TestStatus.FAIL, f"Fallback fdp_configs also failed: {log_res['stderr']}")
            raw_data = log_res.get("data", {})
            if not isinstance(raw_data, dict):
                return TestResult(TestStatus.FAIL, "Could not retrieve FDP configuration data in any parseable form.")

        # nvme-cli exposes the config list under several possible key names
        data = raw_data
        configs = (data.get("fdp_configurations")
                   or data.get("configurations")
                   or data.get("configs")
                   or [])
        num_configs = (data.get("num_fdp_configs")
                       or data.get("num_configs")
                       or data.get("n")
                       or len(configs))

        log(f"Step 2: Validating configuration count (Found: {num_configs}, list len: {len(configs)})...")
        # Accept either a non-zero header count or a non-empty config list
        if int(num_configs) >= 1 or len(configs) >= 1:
            log("✓ Number of FDP Configurations is >= 1.")
            return TestResult(TestStatus.PASS, f"Log header validated successfully. Configurations count: {num_configs or len(configs)}")
        else:
            log("✗ Number of FDP Configurations is less than 1 or field missing.")
            return TestResult(TestStatus.FAIL, "Log Header validation failed. Configuration count < 1.")