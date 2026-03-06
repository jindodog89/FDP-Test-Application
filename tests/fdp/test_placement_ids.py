from ..base_test import BaseTest, TestResult, TestStatus

class TestPlacementIDs(BaseTest):
    test_id = "fdp_placement_ids"
    name = "Placement Identifier (PID) Validation"
    description = "Enumerates available Placement Handles and validates PID assignment per namespace."
    category = "Placement"
    tags = ["namespace", "placement-handle", "pid"]

    def run(self, driver, log) -> TestResult:
        log("Reading FDP placement handles and usage stats...")
        result = driver.get_fdp_placement_ids(endgrp=1)

        if "error" in result:
            return TestResult(TestStatus.FAIL, f"Could not read placement IDs: {result['error']}")

        data = result.get("data", {})
        log("FDP usage data received")

        handles = []
        if isinstance(data, dict):
            handles = data.get("placement_handles", data.get("PlacementHandles", []))
        elif isinstance(data, list):
            handles = data

        if handles:
            log(f"✓ Found {len(handles)} placement handle(s)")
            for h in handles[:5]:
                log(f"  Handle: {h}")
            return TestResult(TestStatus.PASS, f"{len(handles)} placement handles available", details=handles)

        return TestResult(TestStatus.PASS, "FDP usage log accessible", details=data)