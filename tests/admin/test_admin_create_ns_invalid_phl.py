"""
Case: Create NS with Invalid Handle List
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminCreateNSInvalidPHL(BaseTest):
    test_id = "admin_create_ns_invalid_phl"
    name = "Create NS with Invalid Handle List"
    description = "Attempts to create a namespace using a Reclaim Unit Handle count/index that exceeds the supported range."
    category = "Admin"
    tags = ["admin", "create-ns", "namespace", "negative"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsze = 0x10000
        
        # We intentionally pass an exceedingly high nphndls value (e.g., 1024) 
        # that exceeds standard device configurations.
        invalid_nphndls = 1024
        
        log(f"Step 1: Attempting to create namespace with nphndls={invalid_nphndls}...")
        create_res = driver.create_ns(
            nsze=nsze, 
            ncap=nsze, 
            flbas=0, 
            endg_id=endgrp, 
            nphndls=invalid_nphndls
        )

        if create_res["rc"] != 0:
            err_out = create_res["stderr"].lower()
            if "invalid field" in err_out or "invalid format" in err_out:
                log("✓ Command correctly aborted with Invalid Field error.")
                return TestResult(TestStatus.PASS, "Controller successfully rejected out-of-bounds nphndls value.")
            else:
                log(f"⚠ Command failed, but unexpected error string: {err_out}")
                return TestResult(TestStatus.WARN, f"Rejected, but expected Invalid Field error. Got: {err_out}")
        else:
            log("✗ Command unexpectedly succeeded with invalid handle request.")
            # Cleanup if it incorrectly succeeded
            import re
            match = re.search(r'nsid[:\s]+(\d+)', create_res["stdout"], re.IGNORECASE)
            if match:
                driver.delete_ns(int(match.group(1)))
            return TestResult(TestStatus.FAIL, "Controller incorrectly allowed creation with invalid handle index.")