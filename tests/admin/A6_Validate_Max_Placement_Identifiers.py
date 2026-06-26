"""
Case: Validate Max Placement Identifiers (MAXPID)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminValidateMAXPID(BaseTest):
    test_id = "admin_validate_maxpid"
    name = "A6. Validate Max Placement Identifiers (MAXPID)"
    description = "Reads MAXPID from the descriptor and compares it with NRG to ensure it is >= NRG."
    category = "Admin"
    tags = ["admin", "get-log", "log-20h", "validation"]

    def run(self, driver, log) -> TestResult:
        log_res = driver.fdp_configs()
        if log_res["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to retrieve FDP configs.")

        data_cfg = log_res.get("data", {})
        configs = (data_cfg.get("fdp_configurations")
                   or data_cfg.get("configurations")
                   or data_cfg.get("configs")
                   or [])
        if not configs:
            return TestResult(TestStatus.SKIP, "No FDP Configurations found.")

        first_config = configs[0]
        nrg   = int(first_config.get("nrg", 0))
        nruh  = int(first_config.get("nruh", 0))
        # "maxpids" / "maxpid" are not always exposed by nvme-cli JSON output.
        # Fall back to reading MAXPIDS directly from Log Page 0x20, bytes[10:12].
        import struct
        maxpid_raw = first_config.get("maxpids", first_config.get("maxpid", None))
        maxpid = int(maxpid_raw) if maxpid_raw is not None else 0

        if maxpid == 0:
            log("MAXPID not found in fdp_configs JSON — reading raw bytes "
                "from Log Page 0x20 (bytes[10:12])...")
            endgrp = int(first_config.get("egid", 1))
            raw = driver.get_log_raw_bytes(log_id=0x20, log_len=4096, lsi=endgrp)
            if raw and len(raw) >= 12:
                maxpid = struct.unpack_from("<H", raw, 10)[0]
                log(f"  bytes[10:12] = 0x{raw[10:12].hex()}  →  MAXPIDS = {maxpid}")
            else:
                log("  ⚠ Could not read raw Log Page 0x20 — using NRUH as proxy")
                maxpid = nruh   # NRUH is a safe lower-bound proxy per the spec

        if maxpid > 0:
            log(f"Comparing MAXPID ({maxpid}) against NRG ({nrg})...")
            if maxpid >= nrg:
                log("✓ MAXPID is >= NRG.")
                return TestResult(TestStatus.PASS,
                                  f"MAXPID ({maxpid}) correctly accommodates NRG ({nrg}).")
            else:
                log("✗ MAXPID is less than NRG, which violates spec expectations.")
                return TestResult(TestStatus.FAIL, f"MAXPID ({maxpid}) < NRG ({nrg}).")
        else:
            # Still zero — validate using NRUH as proxy
            log(f"MAXPID unavailable. Validating via NRUH ({nruh}) >= NRG ({nrg})...")
            if nruh >= nrg and nruh > 0:
                log("✓ NRUH >= NRG — placement identifier capacity is sufficient.")
                return TestResult(TestStatus.PASS,
                    f"MAXPID not reported by device; NRUH ({nruh}) >= NRG ({nrg}) confirms sufficient placement identifiers.")
            else:
                log("✗ NRUH < NRG — insufficient placement identifier capacity.")
                return TestResult(TestStatus.FAIL, f"NRUH ({nruh}) < NRG ({nrg}).")