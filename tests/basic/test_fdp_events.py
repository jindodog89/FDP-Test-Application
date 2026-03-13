from ..base_test import BaseTest, TestResult, TestStatus

class TestFDPEvents(BaseTest):
    test_id = "fdp_events"
    name = "FDP Events Log"
    description = "Reads the FDP Events log page and checks for anomalies (media errors, placement violations)."
    category = "Events"
    tags = ["events", "log-page", "errors"]

    def run(self, driver, log) -> TestResult:
        log("Reading FDP events log...")
        result = driver.get_fdp_events(endgrp=1)

        if "error" in result:
            return TestResult(TestStatus.FAIL, f"FDP events log unavailable: {result['error']}")

        data = result.get("data", {})
        log("FDP events data received")

        events = []
        if isinstance(data, dict):
            events = data.get("events", data.get("FdpEvents", []))
        elif isinstance(data, list):
            events = data

        error_types = {"media_error", "placement_violation", "overflow"}
        errors_found = [e for e in events if str(e.get("type", "")).lower() in error_types]

        if errors_found:
            log(f"⚠ {len(errors_found)} error event(s) found")
            return TestResult(TestStatus.WARN, f"{len(errors_found)} FDP error events detected", details=errors_found)

        log(f"✓ {len(events)} event(s), no critical errors")
        return TestResult(TestStatus.PASS, f"{len(events)} events logged, no critical errors", details=events[:10])