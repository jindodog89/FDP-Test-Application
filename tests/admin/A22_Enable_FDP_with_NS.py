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
            cdw11=endgrp,
            cdw12=0x1,
            save=True,
        )

        if enable_result["rc"] != 0:
            err_out = enable_result["stderr"].lower()
            # "Invalid Field in Command" (0x02) means the controller rejects Set
            # Features FID 0x1D entirely — not specifically because namespaces exist.
            # This is a device limitation, not a correct sequence-error rejection.
            if "invalid field" in err_out:
                log(f"⚠ Set Features FID 1Dh rejected with 'Invalid Field' — device does not support")
                log( "  this command at all, regardless of namespace state. Cannot verify sequence error.")
                return TestResult(TestStatus.SKIP,
                    "Device rejects Set Features FID 1Dh with 'Invalid Field' — "
                    "cannot confirm namespace-based rejection specifically.")
            # Any other rejection (e.g. Command Sequence Error 0x0C) is the correct behaviour
            log(f"✓ Command was rejected (rc={enable_result['rc']}): {err_out.strip()}")
            return TestResult(TestStatus.PASS,
                "Controller correctly rejected FDP enable with existing namespaces.")
        else:
            log("✗ Command unexpectedly succeeded despite existing namespaces.")
            return TestResult(TestStatus.FAIL,
                "Controller incorrectly allowed FDP enable on an endurance group with active namespaces.")