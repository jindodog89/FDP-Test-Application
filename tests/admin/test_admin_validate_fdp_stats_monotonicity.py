"""
Case: Validate FDP Statistics Counters (Monotonicity)
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminValidateFDPStatsMonotonicity(BaseTest):
    test_id = "admin_validate_fdp_stats_monotonicity"
    name = "Validate FDP Statistics Monotonicity"
    description = "Reads Log 22h, performs writes, and ensures Host and Media Bytes Written increase monotonically."
    category = "Admin"
    tags = ["admin", "get-log", "log-22h", "stats", "io"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)
        
        log("Step 1: Recording initial FDP Statistics (Log 22h)...")
        stats_initial = driver.fdp_stats(endgrp=endgrp)
        if stats_initial["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Could not read initial statistics.")
        
        data_start = stats_initial.get("data", {})
        hbmw_start = int(data_start.get("hbmw", data_start.get("HostBytesMediaWritten", 0)))
        mbmw_start = int(data_start.get("mbmw", data_start.get("MediaBytesMediaWritten", 0)))
        log(f"  Initial - HBMW: {hbmw_start}, MBMW: {mbmw_start}")

        log("Step 2: Performing write activity (writing data to namespace)...")
        # Writing 4096 blocks of 4KB (16MB total) to ensure counters move
        write_res = driver.write(
            namespace=nsid, 
            start_block=0, 
            block_count=4095, # 0-based, so 4095 = 4096 blocks
            data_size=16777216 
        )
        if write_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Write activity failed: {write_res['stderr']}")
            
        time.sleep(1) # Allow firmware stats to update

        log("Step 3: Recording final FDP Statistics (Log 22h)...")
        stats_final = driver.fdp_stats(endgrp=endgrp)
        data_end = stats_final.get("data", {})
        hbmw_end = int(data_end.get("hbmw", data_end.get("HostBytesMediaWritten", 0)))
        mbmw_end = int(data_end.get("mbmw", data_end.get("MediaBytesMediaWritten", 0)))
        log(f"  Final   - HBMW: {hbmw_end}, MBMW: {mbmw_end}")

        if hbmw_end > hbmw_start and mbmw_end >= mbmw_start:
            log("✓ Host Bytes Written and Media Bytes Written progressed monotonically.")
            return TestResult(TestStatus.PASS, "Counters showed proper monotonicity after write activity.")
        else:
            log("✗ Counters did not increase as expected.")
            return TestResult(TestStatus.FAIL, "Statistics Monotonicity validation failed.")