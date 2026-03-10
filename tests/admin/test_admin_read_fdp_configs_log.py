"""
Case: Read FDP Configurations (Log 20h)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminReadFDPConfigsLog(BaseTest):
    test_id = "admin_read_fdp_configs_log"
    name = "Read FDP Configurations (Log 20h)"
    description = "Issues Get Log Page with LID 20h using the standard Get Log wrapper."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "positive"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Issuing Get Log Page with LID 0x20...")
        # log_len defaults to 4096 which is enough for the header and initial descriptors
        log_res = driver.get_log(log_id=0x20)
        
        if log_res["rc"] == 0:
            data = log_res.get("data", {})
            if data:
                log("✓ Command succeeded. Controller returned a log containing FDP Configuration Descriptors.")
                return TestResult(TestStatus.PASS, "Successfully read Log 20h.", details=data)
            else:
                log("⚠ Command succeeded but returned empty JSON.")
                return TestResult(TestStatus.WARN, "Log 20h read succeeded but parser returned empty output.")
        else:
            log(f"✗ Command failed: {log_res['stderr']}")
            return TestResult(TestStatus.FAIL, "Failed to issue Get Log Page for LID 0x20.")