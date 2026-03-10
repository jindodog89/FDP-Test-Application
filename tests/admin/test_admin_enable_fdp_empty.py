"""
Case: Enable FDP on Empty Endurance Group
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminEnableFDPEmpty(BaseTest):
    test_id = "admin_enable_fdp_empty"
    name = "Enable FDP on Empty Endurance Group"
    description = "Issues Set Features (FID 1Dh) to enable FDP on a valid Endurance Group containing no namespaces."
    category = "Admin"
    tags = ["admin", "set-feature", "fdp-enable", "positive"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log(f"Step 1: Checking that Endurance Group {endgrp} has no namespaces...")
        list_ns = driver.list_namespaces()
        
        if list_ns["rc"] == 0 and list_ns.get("data"):
            ns_list = list_ns["data"].get("nsid_list", list_ns["data"].get("NamespaceList", []))
            if ns_list:
                return TestResult(
                    TestStatus.SKIP, 
                    f"Namespaces exist on device. Test requires an empty endurance group. Found NSIDs: {ns_list}"
                )

        log(f"Step 2: Issuing Set Features (FID 1Dh) to enable FDP on Endurance Group {endgrp}...")
        # cdw11/value: bit 0 = 1 (enable), bits 15:8 = config index 0
        enable_result = driver.set_feature(
            feature_id=0x1D, 
            value=0x1, 
            cdw12=endgrp
        )

        if enable_result["rc"] == 0:
            log("✓ Set Features completed successfully (Status 00h).")
            return TestResult(TestStatus.PASS, "Successfully enabled FDP on an empty endurance group.")
        else:
            log(f"✗ Command failed: {enable_result['stderr']}")
            return TestResult(TestStatus.FAIL, f"Failed to enable FDP: {enable_result['stderr']}")