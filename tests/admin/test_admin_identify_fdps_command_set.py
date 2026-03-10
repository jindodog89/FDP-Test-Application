"""
Case I5: FDPS – FDPS & Command Set Consistency
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminIdentifyFDPSCommandSet(BaseTest):
    test_id = "admin_identify_fdps_command_set"
    name = "FDPS & Command Set Consistency"
    description = "Checks that if FDPS=1, the controller supports the NVM Command Set (CSI=0x00)."
    category = "Admin"
    tags = ["admin", "identify", "fdps", "csi"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Checking FDPS support...")
        parsed_id = driver.get_identify_parsed_fdp()
        if "error" in parsed_id:
            return TestResult(TestStatus.FAIL, f"Identify Controller failed: {parsed_id['error']}")
            
        if not parsed_id["fdps"]:
            return TestResult(TestStatus.SKIP, "FDPS is 0; skipping Command Set consistency check.")
            
        log("  FDPS is 1. Verifying NVM Command Set support...")

        # Step 2: Use generic identify wrapper for Identify I/O Command Set (CNS 1Ch) 
        # Alternatively, we can use id-ctrl with CSI=0. If it succeeds, the controller supports the NVM command set.
        log("Step 2: Issuing Identify Controller with CSI=0x00 (NVM Command Set)...")
        csi_res = driver.identify(cns=0x01, csi=0x00)
        
        if csi_res["rc"] == 0:
            log("✓ Controller successfully returned Identify data for NVM Command Set (CSI 0x00).")
            return TestResult(TestStatus.PASS, "FDPS and Command Set consistency verified.")
        else:
            log(f"✗ Controller failed Identify with CSI=0x00: {csi_res['stderr']}")
            return TestResult(TestStatus.FAIL, "FDPS is 1, but controller does not appear to support the NVM Command Set.")