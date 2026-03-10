"""
Case: Validate Host Bytes Written Accuracy
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminValidateHBWAccuracy(BaseTest):
    test_id = "admin_validate_hbw_accuracy"
    name = "Validate Host Bytes Written Accuracy"
    description = "Issues exactly 16MB of writes and verifies the Host Bytes Written counter reflects the exact delta."
    category = "Admin"
    tags = ["admin", "get-log", "log-22h", "stats", "io"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)
        
        log("Step 1: Recording the initial Host Bytes Written (HBW_Start)...")
        stats_initial = driver.fdp_stats(endgrp=endgrp)
        if stats_initial["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Could not read initial statistics.")
        
        hbmw_start = int(stats_initial.get("data", {}).get("hbmw", stats_initial.get("data", {}).get("HostBytesMediaWritten", 0)))
        
        log("Step 2: Issuing exactly 4096 write commands of 4 KB each (total 16 MB)...")
        write_res = driver.write(
            namespace=nsid, 
            start_block=0, 
            block_count=4095, # 4096 blocks
            data_size=16777216 
        )
        if write_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Write activity failed: {write_res['stderr']}")
            
        time.sleep(1) # Allow drive to flush stats

        log("Step 3: Recording the final Host Bytes Written (HBW_End)...")
        stats_final = driver.fdp_stats(endgrp=endgrp)
        hbmw_end = int(stats_final.get("data", {}).get("hbmw", stats_final.get("data", {}).get("HostBytesMediaWritten", 0)))
        
        delta = hbmw_end - hbmw_start
        log(f"  HBW Delta: {delta} bytes (Expected: 16777216)")

        # Some drives report in 16-byte units or exact bytes depending on FW parsing, 
        # but spec requires it to map out mathematically. We check for exact byte match here.
        if delta == 16777216:
            log("✓ Exact 16MB delta matched in Host Bytes Written.")
            return TestResult(TestStatus.PASS, "HBW_End - HBW_Start precisely matches the 16MB written.")
        else:
            log(f"✗ Delta mismatch. Calculated delta: {delta}")
            return TestResult(TestStatus.FAIL, f"HBW delta ({delta}) did not match expected 16MB (16777216 bytes).")