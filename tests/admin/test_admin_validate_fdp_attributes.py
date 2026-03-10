"""
Case: Validate FDP Attributes (VWC & Enabled Status)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateFDPAttributes(BaseTest):
    test_id = "admin_validate_fdp_attributes"
    name = "Validate FDP Attributes (VWC Status)"
    description = "Reads the FDP Attributes and compares the FDPVWC bit with the controller's main Identify Controller VWC field."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Reading Volatile Write Cache (VWC) capability from Identify Controller...")
        id_ctrl_res = driver.id_ctrl()
        if id_ctrl_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to Identify Controller.")
            
        ctrl_vwc_raw = int(id_ctrl_res.get("data", {}).get("vwc", 0))
        # VWC bit 0 = 1 means VWC is present
        ctrl_vwc_present = bool(ctrl_vwc_raw & 0x1)
        log(f"  Identify Controller VWC bit 0: {ctrl_vwc_present}")

        log("Step 2: Reading FDP Attributes from Log 20h...")
        log_res = driver.fdp_configs()
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to retrieve FDP configs.")

        configs = log_res.get("data", {}).get("fdp_configurations", log_res.get("data", {}).get("configurations", []))
        if not configs:
            return TestResult(TestStatus.SKIP, "No FDP Configurations found.")

        first_config = configs[0]
        # Look for FDP Attributes (fdpa)
        fdpa = int(first_config.get("fdpa", first_config.get("fdp_attributes", 0)))
        
        # FDPVWC is bit 0 of the FDPA field
        fdpvwc_present = bool(fdpa & 0x1)
        log(f"  FDP Configuration FDPA bit 0 (FDPVWC): {fdpvwc_present}")

        if ctrl_vwc_present == fdpvwc_present:
            log("✓ FDPVWC bit matches Controller VWC capability.")
            return TestResult(TestStatus.PASS, "FDP Attributes Volatile Write Cache bit aligns with Identify Controller.")
        else:
            log("✗ Mismatch between Controller VWC capability and FDPVWC attribute.")
            return TestResult(TestStatus.FAIL, f"Controller VWC: {ctrl_vwc_present}, FDPVWC: {fdpvwc_present}")