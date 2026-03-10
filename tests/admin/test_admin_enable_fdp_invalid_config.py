"""
Case: Enable FDP with Invalid Config Index
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminEnableFDPInvalidConfig(BaseTest):
    test_id = "admin_enable_fdp_invalid_config"
    name = "Enable FDP with Invalid Config Index"
    description = "Issues Set Features with an invalid FDP Configuration Index and expects an Invalid Field error."
    category = "Admin"
    tags = ["admin", "set-feature", "fdp-enable", "negative"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log("Step 1: Issuing Set Features with invalid config index (0xFF)...")
        # cdw11/value: bit 0 = 1 (enable), bits 15:8 = config index 0xFF (255 - highly likely invalid)
        invalid_val = (0xFF << 8) | 0x1
        
        enable_result = driver.set_feature(
            feature_id=0x1D, 
            value=invalid_val, 
            cdw12=endgrp
        )

        if enable_result["rc"] != 0:
            err_out = enable_result["stderr"].lower()
            if "invalid field" in err_out or "invalid format" in err_out:
                log("✓ Command correctly aborted with Invalid Field in Command.")
                return TestResult(TestStatus.PASS, "Controller correctly rejected invalid FDP configuration index.")
            else:
                log(f"⚠ Command failed, but unexpected error string: {err_out}")
                return TestResult(TestStatus.WARN, f"Rejected, but expected Invalid Field error. Got: {err_out}")
        else:
            log("✗ Command unexpectedly succeeded with config index 0xFF.")
            return TestResult(TestStatus.FAIL, "Controller incorrectly accepted an invalid FDP Configuration Index.")