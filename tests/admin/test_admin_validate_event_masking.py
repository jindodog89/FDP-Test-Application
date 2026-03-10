"""
Case: Validate Event Masking (Disabled Events)
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminValidateEventMasking(BaseTest):
    test_id = "admin_validate_event_masking"
    name = "Validate Event Masking (Disabled Events)"
    description = "Disables the Invalid PID event, issues an invalid write, and confirms no new event is recorded."
    category = "Admin"
    tags = ["admin", "events", "set-feature", "masking"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)
        
        log("Step 1: Reading baseline event count...")
        baseline_events = driver.fdp_events(endgrp=endgrp).get("data", {}).get("events", [])
        initial_count = len(baseline_events)
        log(f"  Baseline Event Count: {initial_count}")

        log("Step 2: Disabling 'Invalid Placement Identifier' event (Type 0x00) via Set Features (FID 1Eh)...")
        # CDW11: bit 8 = 0 (Disable), bits 7:0 = 0x00 (Invalid PID Event)
        disable_val = (0 << 8) | 0x00
        driver.set_feature(feature_id=0x1E, value=disable_val, cdw12=endgrp)
        
        log("Step 3: Issuing a write command using invalid Placement Identifier (0xBEEF)...")
        driver.write(namespace=nsid, start_block=0, block_count=1, data_size=4096, dtype=2, dspec=0xBEEF)
        
        time.sleep(1)
        
        log("Step 4: Retrieving Log 23h and verifying count is unchanged...")
        final_events = driver.fdp_events(endgrp=endgrp).get("data", {}).get("events", [])
        final_count = len(final_events)
        log(f"  Final Event Count: {final_count}")
        
        if final_count == initial_count:
            log("✓ Event masking verified. No new event was recorded.")
            return TestResult(TestStatus.PASS, "Controller successfully masked the disabled FDP event.")
        else:
            log("✗ Event count increased despite being disabled.")
            return TestResult(TestStatus.FAIL, f"Event count changed from {initial_count} to {final_count}.")