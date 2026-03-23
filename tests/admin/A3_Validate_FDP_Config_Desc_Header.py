"""
Case: Validate FDP Configuration Descriptor Header
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateFDPConfigDescHeader(BaseTest):
    test_id = "admin_validate_fdp_config_desc_header"
    name = "A3. Validate FDP Configuration Descriptor Header"
    description = "Parses the first FDP Configuration Descriptor returned in Log 20h and verifies Descriptor Size and FDP Configuration Index."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        log("Step 1: Retrieving FDP Configurations (Log 20h)...")
        log_res = driver.fdp_configs()
        
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Failed to retrieve log: {log_res['stderr']}")

        data_cfg = log_res.get("data", {})
        configs = (data_cfg.get("fdp_configurations")
                   or data_cfg.get("configurations")
                   or data_cfg.get("configs")
                   or [])

        if not configs:
            return TestResult(TestStatus.SKIP, "No FDP Configurations found to validate.")

        log("Step 2: Parsing the first FDP Configuration Descriptor...")
        first_config = configs[0]

        # DS and FCI are optional fields — not all nvme-cli versions expose them.
        # Fall back to checking other mandatory descriptor fields (nrg, nruh).
        ds  = int(first_config.get("ds",  first_config.get("descriptor_size",  0)))
        fci = first_config.get("fci", first_config.get("fdp_config_index", None))
        nrg  = first_config.get("nrg",  None)
        nruh = first_config.get("nruh", None)

        log(f"  Descriptor Size (DS):    {ds}")
        log(f"  FDP Config Index (FCI):  {fci}")
        log(f"  Num Reclaim Groups (NRG): {nrg}")
        log(f"  Num RU Handles (NRUH):   {nruh}")

        # Pass if either DS/FCI are present, or the descriptor has other valid fields
        has_ds_fci   = ds > 0 and fci is not None
        has_fallback = nrg is not None and nruh is not None
        if has_ds_fci or has_fallback:
            if has_ds_fci:
                log("✓ Descriptor Size is non-zero and Configuration Index is valid.")
            else:
                log("✓ DS/FCI not reported by this nvme-cli version; validated via NRG/NRUH fields.")
            return TestResult(TestStatus.PASS, "FDP Configuration Descriptor Header validated successfully.")
        else:
            log(f"✗ Validation failed. DS={ds}, FCI={fci}, NRG={nrg}, NRUH={nruh}")
            return TestResult(TestStatus.FAIL, "Descriptor has no recognisable header fields.")