"""
Case: Validate Event Log Header & Count
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateEventLogHeader(BaseTest):
    test_id = "admin_validate_event_log_header"
    name = "Validate Event Log Header & Count"
    description = "Retrieves Log 23h and verifies the Number of FDP Events matches the parsed descriptor count."
    category = "Admin"
    tags = ["admin", "get-log", "log-23h", "events", "validation"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log(f"Step 1: Issuing Get Log Page (LID 23h) for Endurance Group {endgrp}...")
        log_res = driver.fdp_events(endgrp=endgrp)
        
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Failed to retrieve Log 23h: {log_res['stderr']}")

        data = log_res.get("data", {})
        
        # nvme-cli typically outputs 'num_events' and the 'events' array
        num_events_header = int(data.get("num_events", data.get("nevents", 0)))
        events_array = data.get("events", data.get("FdpEvents", []))
        array_count = len(events_array)
        
        log(f"Step 2: Validating counts. Header claims: {num_events_header}, Array length: {array_count}...")
        
        if num_events_header == array_count:
            log("✓ Number of FDP Events in the header matches the descriptor count.")
            return TestResult(TestStatus.PASS, f"Header validation successful. Count: {num_events_header}")
        else:
            log("✗ Mismatch between header count and actual descriptor count.")
            return TestResult(TestStatus.FAIL, f"Header: {num_events_header}, Array: {array_count}")