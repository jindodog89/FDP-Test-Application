"""
Case: Read FDP Statistics (Log 22h)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminReadFDPStats(BaseTest):
    test_id = "admin_read_fdp_stats"
    name = "Read FDP Statistics (Log 22h)"
    description = "Issues Get Log Page with LID 22h to retrieve and validate statistical counters."
    category = "Admin"
    tags = ["admin", "get-log", "log-22h", "stats", "positive"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log(f"Step 1: Issuing Get Log Page (LID 22h) for Endurance Group {endgrp}...")
        stats_res = driver.fdp_stats(endgrp=endgrp)
        
        if stats_res["rc"] != 0:
            log(f"✗ Failed to read FDP Statistics: {stats_res['stderr']}")
            return TestResult(TestStatus.FAIL, "Failed to retrieve Log 22h (FDP Statistics).")
            
        data = stats_res.get("data", {})
        if not data:
            return TestResult(TestStatus.FAIL, "Command succeeded but returned empty statistics.")

        # Validate presence of mandatory counters
        hbmw = data.get("hbmw", data.get("HostBytesMediaWritten"))
        mbmw = data.get("mbmw", data.get("MediaBytesMediaWritten"))
        
        if hbmw is not None and mbmw is not None:
            log(f"✓ Valid counters returned. HBMW: {hbmw}, MBMW: {mbmw}")
            return TestResult(TestStatus.PASS, "Log 22h returned valid statistical counters.", details=data)
        else:
            log("⚠ Log retrieved but expected counter fields (HBMW, MBMW) are missing from the JSON output.")
            return TestResult(TestStatus.WARN, "Log 22h parsed but missing primary counters.")