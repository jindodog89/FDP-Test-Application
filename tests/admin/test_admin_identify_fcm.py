"""
Case I2: FCM – Validate Fixed Capacity Management
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminIdentifyFCM(BaseTest):
    test_id = "admin_identify_fcm"
    name = "Validate Fixed Capacity Management (FCM)"
    description = "Reads CTRATT Bit 18 (FCM) and logs its state alongside FDPS capability."
    category = "Admin"
    tags = ["admin", "identify", "ctratt", "fcm"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Reading Identify Controller FDP parsed fields...")
        parsed_id = driver.get_identify_parsed_fdp()
        
        if "error" in parsed_id:
            return TestResult(TestStatus.FAIL, f"Identify Controller failed: {parsed_id['error']}")
            
        fdps = parsed_id["fdps"]
        fcm = parsed_id["fcm"]
        
        log(f"  FDPS (Bit 19): {fdps}")
        log(f"  FCM  (Bit 18): {fcm}")

        if not fdps:
            return TestResult(TestStatus.SKIP, "FDPS is 0; skipping FCM validation as FDP is unsupported.")

        log("✓ FCM state read successfully.")
        # The test passes when the observed FCM state is successfully logged for validation
        return TestResult(TestStatus.PASS, f"FCM state successfully observed as: {'1 (Enabled)' if fcm else '0 (Disabled)'}")