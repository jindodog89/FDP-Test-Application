"""
Case: Validate Event Descriptor – Invalid Placement ID
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminValidateEventInvalidPID(BaseTest):
    test_id = "admin_validate_event_invalid_pid"
    name = "Validate Event Descriptor - Invalid Placement ID"
    description = "Enables the Invalid PID event, issues a write with an invalid handle, and verifies it is logged."
    category = "Admin"
    tags = ["admin", "events", "set-feature", "invalid-pid"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)
        invalid_pid = 0xDEAD
        
        log("Step 1: Enabling 'Invalid Placement Identifier' event (Type 0x00) via Set Features (FID 1Eh)...")
        # CDW11: bit 8 = 1 (Enable), bits 7:0 = 0x00 (Invalid PID Event)
        enable_val = (1 << 8) | 0x00
        driver.set_feature(feature_id=0x1E, value=enable_val, cdw12=endgrp)
        
        log(f"Step 2: Issuing a write command using invalid Placement Identifier ({hex(invalid_pid)})...")
        # dtype=2 (FDP directive), dspec=Placement ID
        driver.write(namespace=nsid, start_block=0, block_count=1, data_size=4096, dtype=2, dspec=invalid_pid)
        
        time.sleep(1) # Allow log to populate
        
        log("Step 3: Retrieving Log 23h and parsing the most recent event descriptor...")
        log_res = driver.fdp_events(endgrp=endgrp)
        events = log_res.get("data", {}).get("events", [])
        
        if not events:
            return TestResult(TestStatus.FAIL, "Log 23h is empty; expected an Invalid PID event.")
            
        last_event = events[-1]
        event_type = int(last_event.get("type", last_event.get("event_type", -1)))
        logged_pid = int(last_event.get("pid", last_event.get("placement_identifier", -1)))
        
        log(f"  Found Event - Type: {event_type}, PID: {hex(logged_pid)}")
        
        if event_type == 0x00 and logged_pid == invalid_pid:
            log("✓ Event Type is 0x00 (Invalid PID) and the Placement Identifier matches.")
            return TestResult(TestStatus.PASS, "Successfully logged and validated Invalid PID event.")
        else:
            log("✗ Most recent event does not match expected Invalid PID criteria.")
            return TestResult(TestStatus.FAIL, f"Expected Type: 0, PID: {invalid_pid}. Got Type: {event_type}, PID: {logged_pid}")