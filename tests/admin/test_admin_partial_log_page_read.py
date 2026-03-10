"""
Case: Partial Log Page Read (Boundary)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminPartialLogPageRead(BaseTest):
    test_id = "admin_partial_log_page_read"
    name = "Partial Log Page Read (Boundary) - Log 20h"
    description = "Issues Get Log Page (LID 20h) with partial lengths and offsets to verify proper boundary handling."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "boundary"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Issuing Get Log Page (LID 20h) for exactly 8 bytes (Header only)...")
        # Requesting fewer DWORDs than a full descriptor (just the 8-byte header)
        partial_len_res = driver.get_log(log_id=0x20, log_len=8, bin_out=True)
        
        if partial_len_res["rc"] != 0:
            log(f"✗ Failed partial read (8 bytes): {partial_len_res['stderr']}")
            return TestResult(TestStatus.FAIL, "Controller rejected partial length read of Log 20h.")
        log("✓ Controller successfully returned partial log (header only).")

        log("Step 2: Issuing Get Log Page with an offset of 8 bytes (skipping header)...")
        # Requesting data starting exactly at the first descriptor (offset 8)
        offset_res = driver.get_log(log_id=0x20, log_len=32, offset=8, bin_out=True)
        
        if offset_res["rc"] != 0:
            log(f"✗ Failed offset read (offset 8): {offset_res['stderr']}")
            return TestResult(TestStatus.FAIL, "Controller rejected offset read of Log 20h.")
        log("✓ Controller successfully handled offset landing inside/at a descriptor boundary.")

        return TestResult(TestStatus.PASS, "Controller handles partial lengths and offsets for Log 20h correctly.")