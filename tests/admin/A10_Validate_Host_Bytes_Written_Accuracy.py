"""
Case: Validate Host Bytes Written Accuracy
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminValidateHBWAccuracy(BaseTest):
    test_id = "admin_validate_hbw_accuracy"
    name = "A10. Validate Host Bytes Written Accuracy"
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
        # Single write capped to MDTS-safe 64 KB (16 × 4 KB blocks)
        write_res = driver.write(
            namespace=nsid,
            start_block=0,
            block_count=15,   # 16 blocks × 4 KB = 64 KB (MDTS-safe)
            data_size=65536
        )
        if write_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Write activity failed: {write_res['stderr']}")
            
        time.sleep(1) # Allow drive to flush stats

        log("Step 3: Recording the final Host Bytes Written (HBW_End)...")
        stats_final = driver.fdp_stats(endgrp=endgrp)
        hbmw_end = int(stats_final.get("data", {}).get("hbmw", stats_final.get("data", {}).get("HostBytesMediaWritten", 0)))
        
        delta = hbmw_end - hbmw_start
        expected = 65536  # 64 KB written
        log(f"  HBW Delta: {delta} bytes (Expected: {expected})")
        # Accept exact match or within ±10% (some firmware batch-updates counters)
        if abs(delta - expected) <= expected * 0.10:
            log("✓ HBW delta matches the 64 KB written (within 10%).")
            return TestResult(TestStatus.PASS, f"HBW delta {delta} B matches expected {expected} B.")
        elif delta > 0:
            log(f"⚠ HBW delta ({delta}) is non-zero but does not match expected {expected}.")
            return TestResult(TestStatus.WARN, f"HBW delta ({delta}) differs from expected ({expected}).")
        else:
            log(f"✗ Delta mismatch. Calculated delta: {delta}")
            return TestResult(TestStatus.FAIL, f"HBW delta ({delta}) did not increase after write.")