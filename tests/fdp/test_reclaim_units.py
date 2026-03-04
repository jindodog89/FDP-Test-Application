from ..base_test import BaseTest, TestResult, TestStatus

class TestReclaimUnits(BaseTest):
    test_id = "fdp_reclaim_units"
    name = "Reclaim Unit Handle Status"
    description = "Reads RUHS (Reclaim Unit Handle Status) log and verifies reclaim unit availability."
    category = "Reclaim"
    tags = ["ruhs", "reclaim", "namespace"]

    def run(self, driver, log) -> TestResult:
        log("Reading Reclaim Unit Handle Status (RUHS)...")
        result = driver.get_reclaim_unit_handle_status(namespace=1)

        if "error" in result:
            return TestResult(TestStatus.FAIL, f"RUHS unavailable: {result['error']}")

        data = result.get("data", {})
        log("RUHS data received")

        ruhs = []
        if isinstance(data, dict):
            ruhs = data.get("ruhs", data.get("ReclaimUnitHandles", []))
        elif isinstance(data, list):
            ruhs = data

        if ruhs:
            active = [r for r in ruhs if r.get("active", r.get("Active", True))]
            log(f"✓ {len(ruhs)} reclaim unit handle(s), {len(active)} active")
            return TestResult(TestStatus.PASS, f"{len(ruhs)} RUH(s) found", details=ruhs[:10])

        return TestResult(TestStatus.PASS, "RUHS log accessible", details=data)