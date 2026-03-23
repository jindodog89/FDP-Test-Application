"""
Case: FDP Event Log Retention (No Reset)
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminEventLogRetention(BaseTest):
    test_id = "admin_event_log_retention"
    name = "A23. Event Log Retention (Enablement Cycle)"
    description = "Generates events, verifies they exist, cycles FDP (Disable -> Enable), and checks that the log is cleared."
    category = "Admin"
    tags = ["admin", "events", "retention", "set-feature"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)
        
        # 1. Ensure events are enabled and generate one
        enable_val = (1 << 8) | 0x00
        # en_res = driver.set_feature(feature_id=0x1E, value=enable_val, cdw12=endgrp)
        en_res = driver.set_feature_passthru(feature_id=0x1E, value=enable_val, endgrp=endgrp)
        if en_res["rc"] != 0:
            log(f"  ⚠ FID 1Eh not supported or timed out: {en_res['stderr'].strip()}")
            return TestResult(TestStatus.SKIP,
                "FDP event enable (FID 1Eh) not supported on this device — cannot generate events.")

        log("Step 1: Generating an FDP event...")
        driver.write(namespace=nsid, start_block=0, block_count=1, data_size=4096, dtype=2, dspec=0xCCCC)
        time.sleep(1)

        # 2. Confirm event exists
        initial_events = driver.fdp_events(endgrp=endgrp).get("data", {}).get("events", [])
        if len(initial_events) == 0:
            return TestResult(TestStatus.FAIL, "Failed to generate initial event for retention test.")
        log(f"Step 2: Confirmed {len(initial_events)} event(s) in log.")
        
        # 3. Disable FDP
        log("Step 3: Issuing Set Features to Disable FDP...")
        dis_res = driver.set_feature_passthru(feature_id=0x1D, value=0x0, endgrp=endgrp)
        if dis_res["rc"] != 0:
            log(f"  ⚠ FDP disable rejected: {dis_res['stderr'].strip()} — skipping FDP cycle.")
            return TestResult(TestStatus.SKIP,
                "Cannot disable FDP on this device — skipping retention cycle test.")

        # 4. Re-enable FDP
        log("Step 4: Re-enabling FDP...")
        driver.set_feature_passthru(feature_id=0x1D, value=0x1, endgrp=endgrp)
        time.sleep(1)  # Allow enablement to settle
        
        # 5. Check log
        log("Step 5: Reading Log 23h again...")
        final_events_res = driver.fdp_events(endgrp=endgrp)
        
        # If disabled/re-enabled, the log should either fail to read temporarily or return empty
        final_events = final_events_res.get("data", {}).get("events", []) if final_events_res["rc"] == 0 else []
        
        if len(final_events) == 0:
            log("✓ The event log is cleared; count returned to 0.")
            return TestResult(TestStatus.PASS, "Event log correctly tied to the current FDP enablement cycle.")
        else:
            log(f"✗ Event log was not cleared! Found {len(final_events)} events.")
            return TestResult(TestStatus.FAIL, "Controller preserved events across an FDP disable/enable cycle.")