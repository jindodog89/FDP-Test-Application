"""
Case I4: VWC – Validate Flush Behavior (FB) Field
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminIdentifyVWCFlush(BaseTest):
    test_id = "admin_identify_vwc_flush"
    name = "Validate Flush Behavior (FB) Field"
    description = "Reads VWC Byte 525 and verifies the Flush Behavior (bits 2:1) is valid (10b or 11b)."
    category = "Admin"
    tags = ["admin", "identify", "vwc", "flush"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Reading VWC Byte and Flush Behavior...")
        parsed_id = driver.get_identify_parsed_fdp()
        if "error" in parsed_id:
            return TestResult(TestStatus.FAIL, f"Identify Controller failed: {parsed_id['error']}")
            
        fb = parsed_id["vwc_flush_behavior"]
        log(f"  Flush Behavior (Bits 2:1): {bin(fb)} (Decimal {fb})")

        if fb == 0:
            log("✗ Flush Behavior is 00b, which is prohibited for NVMe 1.4+ devices.")
            return TestResult(TestStatus.FAIL, "Prohibited Flush Behavior value (00b).")
        elif fb == 1:
            log("✗ Flush Behavior is 01b, which is reserved.")
            return TestResult(TestStatus.FAIL, "Reserved Flush Behavior value (01b).")
        elif fb == 2:
            log("✓ Flush Behavior is 10b (Flush applies to all namespaces).")
            return TestResult(TestStatus.PASS, "Valid Flush Behavior (10b).")
        elif fb == 3:
            log("✓ Flush Behavior is 11b (NSID-specific flush behavior).")
            return TestResult(TestStatus.PASS, "Valid Flush Behavior (11b).")
        
        return TestResult(TestStatus.FAIL, "Unexpected Flush Behavior value.")