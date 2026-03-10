"""
Case: Disable FDP (Stats Clearing)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminDisableFDPStatsClear(BaseTest):
    test_id = "admin_disable_fdp_stats_clear"
    name = "Disable FDP (Stats Clearing)"
    description = "Disables FDP via Set Features and verifies that all FDP-related events and statistics are cleared."
    category = "Admin"
    tags = ["admin", "set-feature", "fdp-disable", "stats"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log("Step 1: Issuing Set Features (FID 1Dh) to disable FDP...")
        # cdw11/value: bit 0 = 0 (disable)
        disable_result = driver.set_feature(
            feature_id=0x1D, 
            value=0x0, 
            cdw12=endgrp
        )

        if disable_result["rc"] != 0:
            log(f"✗ Failed to disable FDP: {disable_result['stderr']}")
            return TestResult(TestStatus.FAIL, "Set Features command to disable FDP failed.")
            
        log("✓ FDP successfully disabled.")

        log("Step 2: Verifying FDP Events log is cleared...")
        events_res = driver.fdp_events(endgrp=endgrp)
        
        if events_res["rc"] == 0:
            events_data = events_res.get("data", {})
            events = events_data.get("events", events_data.get("FdpEvents", []))
            if len(events) > 0:
                log(f"✗ Events log not cleared! Found {len(events)} events.")
                return TestResult(TestStatus.FAIL, "FDP Events log was not cleared after disabling FDP.")
            else:
                log("✓ FDP Events log is empty.")
        else:
             log("✓ FDP Events log correctly unreadable/empty while disabled.")

        log("Step 3: Verifying FDP Statistics are cleared...")
        stats_res = driver.fdp_stats(endgrp=endgrp)
        
        if stats_res["rc"] == 0:
             stats_data = stats_res.get("data", {})
             hbmw = int(stats_data.get("hbmw", stats_data.get("HostBytesMediaWritten", 1)))
             mbmw = int(stats_data.get("mbmw", stats_data.get("MediaBytesMediaWritten", 1)))
             if hbmw > 0 or mbmw > 0:
                 log(f"✗ Stats not cleared! HBMW: {hbmw}, MBMW: {mbmw}")
                 return TestResult(TestStatus.FAIL, "FDP Statistics were not cleared after disabling FDP.")
             else:
                 log("✓ FDP Statistics are effectively cleared.")
        else:
             log("✓ FDP Statistics correctly unreadable/empty while disabled.")

        return TestResult(TestStatus.PASS, "FDP successfully disabled and all statistics/events were cleared.")