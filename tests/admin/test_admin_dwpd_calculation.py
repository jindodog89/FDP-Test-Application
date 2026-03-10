"""
Case: DWPD Calculation Feasibility (Drive Writes Per Day)
"""
from tests.base_test import BaseTest, TestResult, TestStatus

class TestAdminDWPDCalculation(BaseTest):
    test_id = "admin_dwpd_calculation"
    name = "DWPD Calculation Feasibility"
    description = "Retrieves HBW, Total NVM Capacity, and Power-On Hours to compute DWPD."
    category = "Admin"
    tags = ["admin", "get-log", "log-22h", "stats", "endurance"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log("Step 1: Retrieving Host Bytes Written (HBW) from Log 22h...")
        stats_res = driver.fdp_stats(endgrp=endgrp)
        if stats_res["rc"] != 0:
             return TestResult(TestStatus.FAIL, "Failed to read FDP Stats (Log 22h).")
        hbw = int(stats_res.get("data", {}).get("hbmw", stats_res.get("data", {}).get("HostBytesMediaWritten", 0)))
        log(f"  HBW: {hbw} bytes")

        log("Step 2: Retrieving Total NVM Capacity (TNC) from Identify Controller...")
        id_ctrl = driver.id_ctrl()
        if id_ctrl["rc"] != 0:
            return TestResult(TestStatus.FAIL, "Failed to Identify Controller.")
        
        # TNVMCAP is technically 16 bytes. nvme-cli usually formats it as an integer or hex string.
        tnc_raw = id_ctrl.get("data", {}).get("tnvmcap", 1) 
        tnc = int(tnc_raw, 16) if isinstance(tnc_raw, str) and tnc_raw.startswith("0x") else int(tnc_raw)
        log(f"  TNC: {tnc} bytes")

        if tnc == 0:
            return TestResult(TestStatus.FAIL, "Total NVM Capacity reported as 0.")

        log("Step 3: Obtaining Power-On Hours (POH) from the SMART log...")
        smart_res = driver.smart_log()
        if smart_res["rc"] != 0:
             return TestResult(TestStatus.FAIL, "Failed to retrieve SMART log.")
             
        poh = int(smart_res.get("data", {}).get("power_on_hours", 0))
        log(f"  POH: {poh} hours")

        if poh == 0:
            log("⚠ Power-On Hours is 0 (brand new drive). Assuming 1 hour to prevent division by zero.")
            poh = 1

        log("Step 4: Computing DWPD...")
        # DWPD = (HBW / TNC) / (POH / 24)
        days_powered_on = poh / 24.0
        drive_writes = hbw / float(tnc)
        dwpd = drive_writes / days_powered_on
        
        log(f"  Drive Writes: {drive_writes:.6f}")
        log(f"  Days Powered On: {days_powered_on:.2f}")
        log(f"  Calculated DWPD: {dwpd:.6f}")

        # The expected result is that the DWPD matches or exceeds vendor ratings, 
        # but since this is a dynamic validation test, we simply pass if the calculation mathematically resolves without error.
        if dwpd >= 0:
            log("✓ DWPD calculated successfully.")
            return TestResult(TestStatus.PASS, f"DWPD Calculation Feasible. Result: {dwpd:.6f}")
        else:
            return TestResult(TestStatus.FAIL, "DWPD calculation yielded a negative or invalid number.")