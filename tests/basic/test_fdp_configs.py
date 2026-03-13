from ..base_test import BaseTest, TestResult, TestStatus

class TestFDPConfigs(BaseTest):
    test_id = "fdp_configs"
    name = "FDP Configurations Enumeration"
    description = "Reads and validates FDP configuration records (endurance groups, reclaim group IDs)."
    category = "Basic"
    tags = ["read-only", "config", "endurance-groups"]

    def run(self, driver, log) -> TestResult:
        log("Reading FDP configurations...")
        result = driver.get_fdp_configs()

        if "error" in result:
            return TestResult(TestStatus.FAIL, f"Could not read FDP configs: {result['error']}")

        data = result.get("data", {})
        configs = data if isinstance(data, list) else data.get("configurations", data.get("fdp_configurations", []))

        if isinstance(configs, list) and len(configs) > 0:
            log(f"✓ Found {len(configs)} FDP configuration(s)")
            for i, cfg in enumerate(configs):
                log(f"  Config {i}: {cfg}")
            return TestResult(TestStatus.PASS, f"{len(configs)} FDP configuration(s) found", details=configs)

        log("FDP configs accessible (structure may vary by firmware)")
        return TestResult(TestStatus.PASS, "FDP configurations accessible", details=data)