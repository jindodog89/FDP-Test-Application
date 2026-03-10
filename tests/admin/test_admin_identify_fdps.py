"""
Case I1: FDPS – Validate FDPS Bit in Controller Attributes
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminIdentifyFDPS(BaseTest):
    test_id = "admin_identify_fdps"
    name = "Validate FDPS Bit in Controller Attributes"
    description = "Checks CTRATT Bit 19 (FDPS) and verifies Set Features (FID 1Dh) acceptance aligns with it."
    category = "Admin"
    tags = ["admin", "identify", "ctratt", "fdps"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log("Step 1: Reading Identify Controller FDP parsed fields...")
        parsed_id = driver.get_identify_parsed_fdp()
        
        if "error" in parsed_id:
            return TestResult(TestStatus.FAIL, f"Identify Controller failed: {parsed_id['error']}")
            
        fdps_supported = parsed_id["fdps"]
        log(f"  FDPS (CTRATT Bit 19): {fdps_supported}")

        log("Step 2: Testing Set Features (FID 1Dh) behavior...")
        # Issue a Set Features to disable FDP (0x0) - this is a safe operation that simply tests command acceptance
        set_feat_res = driver.set_feature(feature_id=0x1D, value=0x0, cdw12=endgrp)
        command_accepted = (set_feat_res["rc"] == 0)
        
        if fdps_supported:
            if command_accepted:
                log("✓ FDPS is 1 and Set Features (FID 1Dh) was accepted.")
                return TestResult(TestStatus.PASS, "Controller supports FDP and correctly accepts FID 1Dh.")
            else:
                log(f"✗ FDPS is 1, but Set Features failed: {set_feat_res['stderr']}")
                return TestResult(TestStatus.FAIL, "Controller advertises FDP support but rejects FID 1Dh.")
        else:
            if not command_accepted:
                log("✓ FDPS is 0 and Set Features (FID 1Dh) correctly failed.")
                return TestResult(TestStatus.PASS, "Controller correctly rejects FID 1Dh when FDP is unsupported.")
            else:
                log("✗ FDPS is 0, but Set Features unexpectedly succeeded.")
                return TestResult(TestStatus.FAIL, "Controller lacks FDP support but incorrectly accepted FID 1Dh.")