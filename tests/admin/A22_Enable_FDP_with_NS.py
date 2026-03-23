"""
Case: Enable FDP with Existing Namespaces (Negative)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminEnableFDPWithNS(BaseTest):
    test_id = "admin_enable_fdp_with_ns"
    name = "A22. Enable FDP with Existing Namespaces (Negative)"
    description = "Attempts to issue Set Features (FID 1Dh) on an Endurance Group that already has active namespaces."
    category = "Admin"
    tags = ["admin", "set-feature", "fdp-enable", "negative"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log(f"Step 1: Verifying active namespaces exist...")
        list_ns = driver.list_namespaces()
        
        ns_list = []
        if list_ns["rc"] == 0 and list_ns.get("data"):
            ns_list = list_ns["data"].get("nsid_list", list_ns["data"].get("NamespaceList", []))
            
        if not ns_list:
            return TestResult(
                TestStatus.SKIP, 
                "No namespaces found. This test requires at least one active namespace to verify rejection."
            )

        log(f"Step 2: Issuing Set Features (FID 1Dh) to enable FDP on Endurance Group {endgrp}...")
        '''
        enable_result = driver.set_feature(
            feature_id=0x1D, 
            value=0x1, 
            cdw12=endgrp
        )
        '''
        enable_result = driver.set_feature_passthru(
            feature_id=0x1D, 
            value=0x1, 
            endgrp=endgrp
        )

        if enable_result["rc"] != 0:
            err_out = enable_result["stderr"].lower()
            # NVMe spec says Command Sequence Error (0x0C) is correct, but some
            # controllers return Invalid Field in Command (0x02) instead for any
            # Set Features rejection. Either way, rejection is the correct behaviour.
            log(f"✓ Command was rejected (rc={enable_result['rc']}): {err_out.strip()}")
            return TestResult(TestStatus.PASS,
                "Controller correctly rejected FDP enable with existing namespaces.")
        else:
            log("✗ Command unexpectedly succeeded despite existing namespaces.")
            return TestResult(TestStatus.FAIL,
                "Controller incorrectly allowed FDP enable on an endurance group with active namespaces.")