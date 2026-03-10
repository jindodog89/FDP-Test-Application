"""
Case: Enable FDP with Existing Namespaces (Negative)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminEnableFDPWithNS(BaseTest):
    test_id = "admin_enable_fdp_with_ns"
    name = "Enable FDP with Existing Namespaces (Negative)"
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
        enable_result = driver.set_feature(
            feature_id=0x1D, 
            value=0x1, 
            cdw12=endgrp
        )

        if enable_result["rc"] != 0:
            err_out = enable_result["stderr"].lower()
            if "sequence" in err_out or "command sequence error" in err_out:
                log("✓ Command correctly aborted with Command Sequence Error.")
                return TestResult(TestStatus.PASS, "Controller correctly rejected FDP enable with existing namespaces.")
            else:
                log(f"⚠ Command failed, but unexpected error string: {err_out}")
                return TestResult(TestStatus.WARN, f"Rejected, but expected Command Sequence Error. Got: {err_out}")
        else:
            log("✗ Command unexpectedly succeeded despite existing namespaces.")
            return TestResult(TestStatus.FAIL, "Controller incorrectly allowed FDP enable on an endurance group with active namespaces.")