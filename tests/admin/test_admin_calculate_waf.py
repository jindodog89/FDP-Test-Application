"""
Case: Calculate & Validate Write-Amplification Factor (WAF)
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminCalculateWAF(BaseTest):
    test_id = "admin_calculate_waf"
    name = "Calculate & Validate Write-Amplification Factor (WAF)"
    description = "Resets FDP stats, runs a sequential workload, and calculates WAF = Media Bytes Written / Host Bytes Written."
    category = "Admin"
    tags = ["admin", "get-log", "log-22h", "stats", "waf"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)
        
        log("Step 1: Resetting FDP statistics by disabling then re-enabling FDP...")
        driver.set_feature(feature_id=0x1D, value=0x0, cdw12=endgrp) # Disable
        time.sleep(0.5)
        driver.set_feature(feature_id=0x1D, value=0x1, cdw12=endgrp) # Enable
        time.sleep(1)

        log("Step 2: Running a sequential, FDP-aligned workload (writing 16MB)...")
        # In a full-scale test, this would be 10GB+ using a tool like fio. 
        # For this nvme-cli unit test, we use a smaller size to prevent timeouts.
        write_res = driver.write(
            namespace=nsid, 
            start_block=0, 
            block_count=4095, # 16MB at 4K LBA
            data_size=16777216,
            dtype=2, # FDP Directive
            dspec=0  # Valid Placement Handle 0
        )
        if write_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Workload failed: {write_res['stderr']}")
            
        time.sleep(1) # Allow drive to flush internal counters

        log("Step 3: Retrieving Log 22h to compute WAF...")
        stats_res = driver.fdp_stats(endgrp=endgrp)
        data = stats_res.get("data", {})
        
        hbmw = int(data.get("hbmw", data.get("HostBytesMediaWritten", 0)))
        mbmw = int(data.get("mbmw", data.get("MediaBytesMediaWritten", 0)))
        
        log(f"  Host Bytes Written (HBW): {hbmw}")
        log(f"  Media Bytes Written (MBW): {mbmw}")

        if hbmw == 0:
            log("✗ Host Bytes Written is 0. Cannot compute WAF (division by zero).")
            return TestResult(TestStatus.FAIL, "Log 22h did not register the host writes.")

        # Compute WAF
        waf = mbmw / hbmw
        log(f"  Computed WAF: {waf:.4f}")

        # WAF should be >= 1.0. For a purely sequential FDP workload, it should be very close to 1.0.
        if 1.0 <= waf <= 1.5:
            log("✓ WAF is near 1.0 (ideal) for a sequential workload.")
            return TestResult(TestStatus.PASS, f"Successfully calculated WAF: {waf:.4f}")
        elif waf < 1.0:
            log("⚠ WAF is less than 1.0, which physically means compression is active or stats are delayed.")
            return TestResult(TestStatus.WARN, f"WAF is unusually low: {waf:.4f}")
        else:
            log("⚠ WAF is unexpectedly high for a sequential FDP workload.")
            return TestResult(TestStatus.WARN, f"WAF calculated, but higher than expected: {waf:.4f}")