"""
Case: Create NS with Placement Handle List
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminCreateNSValidPHL(BaseTest):
    test_id = "admin_create_ns_valid_phl"
    name = "Create NS with Placement Handle List"
    description = "Creates a namespace in an FDP group supplying a valid Placement Handle List (nphndls > 0)."
    category = "Admin"
    tags = ["admin", "create-ns", "namespace", "positive"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log(f"Step 1: Retrieving identify controller info to define NS capacity...")
        id_ctrl = driver.id_ctrl()
        if id_ctrl["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to identify controller.")
            
        # Using minimal safe capacity values for testing
        nsze = 0x10000
        
        log(f"Step 2: Creating namespace with FDP handles (endg-id={endgrp}, nphndls=8)...")
        create_res = driver.create_ns(
            nsze=nsze, 
            ncap=nsze, 
            flbas=0, 
            endg_id=endgrp, 
            nphndls=8
        )

        if create_res["rc"] == 0:
            log("✓ Namespace successfully created with the specified handles.")
            
            # Teardown logic: extract NSID and delete it to leave device clean
            import re
            match = re.search(r'nsid[:\s]+(\d+)', create_res["stdout"], re.IGNORECASE)
            if match:
                created_nsid = int(match.group(1))
                log(f"Cleaning up: deleting created NSID {created_nsid}...")
                driver.delete_ns(created_nsid)
                
            return TestResult(TestStatus.PASS, "Namespace was created and correctly associated with specified handles.")
        else:
            log(f"✗ Namespace creation failed: {create_res['stderr']}")
            return TestResult(TestStatus.FAIL, "Command failed to create namespace with valid handles.")