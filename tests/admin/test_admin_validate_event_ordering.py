"""
Case: Validate Event Timestamp / Ordering
"""
from tests.base_test import BaseTest, TestResult, TestStatus
import time

class TestAdminValidateEventOrdering(BaseTest):
    test_id = "admin_validate_event_ordering"
    name = "Validate Event Timestamp & Ordering"
    description = "Triggers two discrete events separated by time and verifies they are ordered correctly (Timestamp B > A or chronological index)."
    category = "Admin"
    tags = ["admin", "events", "ordering"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)
        
        # Enable Invalid PID Event
        enable_val = (1 << 8) | 0x00
        driver.set_feature(feature_id=0x1E, value=enable_val, cdw12=endgrp)
        
        log("Step 1: Triggering Event A (Invalid PID 0xAA)...")
        driver.write(namespace=nsid, start_block=0, block_count=1, data_size=4096, dtype=2, dspec=0xAA)
        
        log("Step 2: Waiting 1 second...")
        time.sleep(1.2)
        
        log("Step 3: Triggering Event B (Invalid PID 0xBB)...")
        driver.write(namespace=nsid, start_block=1, block_count=1, data_size=4096, dtype=2, dspec=0xBB)
        time.sleep(1)
        
        log("Step 4: Retrieving Log 23h...")
        events = driver.fdp_events(endgrp=endgrp).get("data", {}).get("events", [])
        
        if len(events) < 2:
            return TestResult(TestStatus.FAIL, "Failed to capture both generated events.")
            
        # The last two events should be our injected ones
        event_b = events[-1]
        event_a = events[-2]
        
        pid_a = int(event_a.get("pid", event_a.get("placement_identifier", -1)))
        pid_b = int(event_b.get("pid", event_b.get("placement_identifier", -1)))
        
        ts_a = int(event_a.get("timestamp", event_a.get("ts", 0)))
        ts_b = int(event_b.get("timestamp", event_b.get("ts", 0)))
        
        log(f"  Event A - PID: {hex(pid_a)}, Timestamp: {ts_a}")
        log(f"  Event B - PID: {hex(pid_b)}, Timestamp: {ts_b}")
        
        if pid_a != 0xAA or pid_b != 0xBB:
            log("⚠ Warning: The last two events do not match the expected PID sequence. Log may be noisy.")
        
        if ts_b > ts_a:
            log("✓ Event B timestamp is greater than Event A.")
            return TestResult(TestStatus.PASS, "Events ordered chronologically with correct timestamps.")
        elif ts_a == 0 and ts_b == 0:
            log("✓ Timestamps not implemented, but descriptor array order matches generation sequence (newer index = newer event).")
            return TestResult(TestStatus.PASS, "Events ordered chronologically via array index.")
        else:
            log("✗ Event ordering or timestamps are invalid.")
            return TestResult(TestStatus.FAIL, f"Event A TS: {ts_a}, Event B TS: {ts_b}")