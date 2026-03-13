from ..base_test import BaseTest, TestResult, TestStatus

class TestFDPStatus(BaseTest):
    test_id = "fdp_status"
    name = "FDP Status Check"
    description = "Reads FDP status log (Log Page 0x31) and validates FDP is enabled on the device."
    category = "Basic"
    tags = ["read-only", "log-page", "status"]

    def run(self, driver, log) -> TestResult:
        log("Querying FDP status log page (0x31)...")
        result = driver.get_fdp_status()

        if "error" in result:
            return TestResult(TestStatus.FAIL, f"FDP status unavailable: {result['error']}")

        data = result.get("data", {})
        log(f"FDP Status raw response received")

        if isinstance(data, dict):
            fdp_enabled = data.get("fdp_enabled", data.get("FdpEnabled", None))
            if fdp_enabled is not None:
                if fdp_enabled:
                    log("✓ FDP is ENABLED on this device")
                    return TestResult(TestStatus.PASS, "FDP is enabled and status log is accessible")
                else:
                    log("✗ FDP is reported as DISABLED")
                    return TestResult(TestStatus.FAIL, "FDP is disabled on this device")

        log("FDP status log accessible (format may vary by firmware)")
        return TestResult(TestStatus.PASS, "FDP status log page accessible", details=data)