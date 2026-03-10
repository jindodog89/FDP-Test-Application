"""
Case I3: VWC – Validate Global VWC vs. FDP VWC
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminIdentifyVWCGlobal(BaseTest):
    test_id = "admin_identify_vwc_global"
    name = "Validate Global VWC vs. FDP VWC"
    description = "Checks that if any FDP config advertises FDPVWC=1, the Global VWC bit is also 1."
    category = "Admin"
    tags = ["admin", "identify", "vwc", "log-20h"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Reading Global VWC from Identify Controller...")
        parsed_id = driver.get_identify_parsed_fdp()
        if "error" in parsed_id:
            return TestResult(TestStatus.FAIL, f"Identify Controller failed: {parsed_id['error']}")
            
        global_vwc_present = parsed_id["vwc_present"]
        log(f"  Global VWC Present (Byte 525, Bit 0): {global_vwc_present}")

        log("Step 2: Fetching FDP Configurations (Log 20h)...")
        log_res = driver.fdp_configs()
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to retrieve FDP Configurations.")

        configs = log_res.get("data", {}).get("fdp_configurations", log_res.get("data", {}).get("configurations", []))
        if not configs:
            return TestResult(TestStatus.SKIP, "No FDP Configurations found.")

        fdpvwc_found = False
        for idx, cfg in enumerate(configs):
            fdpa = int(cfg.get("fdpa", cfg.get("fdp_attributes", 0)))
            if fdpa & 0x1:
                fdpvwc_found = True
                log(f"  Config {idx} advertises FDPVWC=1.")

        if fdpvwc_found and not global_vwc_present:
            log("✗ FDP Configuration reports VWC is present, but Global VWC is 0.")
            return TestResult(TestStatus.FAIL, "Conflict: FDPVWC is 1 but Global VWC is 0.")
        
        log("✓ Global VWC state logically aligns with FDP Configurations.")
        return TestResult(TestStatus.PASS, "VWC configurations are internally consistent.")