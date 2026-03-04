"""
Test: fdp_endurance
Run an FDP-aware FIO workload and calculate Write Amplification Factor (WAF)
by reading SMART log data before and after. Also reports per-handle capacity
consumption for FDP efficiency analysis.
"""

import subprocess
import json
import tempfile
import os
from tests.base_test import BaseTest, TestResult, TestStatus


class TestFDPEndurance(BaseTest):
    test_id = "fdp_endurance"
    name = "FDP Endurance — WAF Calculation"
    description = (
        "Runs an FDP-aware FIO write workload and calculates Write Amplification "
        "Factor (WAF) by comparing host-written and NAND-written units from the "
        "NVMe SMART log before and after the workload. A WAF close to 1.0 "
        "indicates optimal FDP placement efficiency."
    )
    category = "Endurance"
    tags = ["fio", "waf", "smart", "endurance", "write-amplification"]

    DEFAULT_PARAMS = {
        "fio_duration_sec":   30,
        "fio_block_size":     "4k",
        "fio_queue_depth":    16,
        "fio_num_jobs":       1,
        "namespace":          1,
        "placement_handle":   0,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: Read SMART log baseline ───────────────────────────────────
        log("Step 1: Reading SMART log (baseline)...")
        smart_before = self._read_smart(driver, log)
        if smart_before is None:
            return TestResult(TestStatus.FAIL, "Cannot read SMART log — required for WAF calculation")

        host_written_before = self._get_host_written(smart_before)
        nand_written_before = self._get_nand_written(smart_before)
        log(f"  Host written (before): {host_written_before:,} units")
        log(f"  NAND written (before): {nand_written_before:,} units")

        # ── Step 2: Read RUHS baseline ────────────────────────────────────────
        log("\nStep 2: Reading RUHS baseline...")
        ruhs_before_result = driver.fdp_ruhs(ns=p["namespace"])
        ruhs_before = self._extract_ruhs(ruhs_before_result) if ruhs_before_result["rc"] == 0 else []
        total_cap_before = sum(
            int(r.get("ruamw", r.get("RUAMWSectors", 0))) for r in ruhs_before
        )
        log(f"  Total RUHS capacity before: {total_cap_before:,} sectors across {len(ruhs_before)} handle(s)")

        # ── Step 3: Check FIO ─────────────────────────────────────────────────
        log("\nStep 3: Verifying FIO availability...")
        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP, "fio not found — install with: sudo apt install fio")
        log("  ✓ fio found")

        # ── Step 4: Run FIO ───────────────────────────────────────────────────
        dev_path = driver.device
        ns_dev = dev_path if "n" in dev_path.split("/")[-1] else dev_path + f"n{p['namespace']}"
        log(f"\nStep 4: Running FDP FIO workload on {ns_dev}...")
        log(f"  Duration: {p['fio_duration_sec']}s  BS: {p['fio_block_size']}  "
            f"QD: {p['fio_queue_depth']}  Jobs: {p['fio_num_jobs']}")

        fio_job = f"""
[global]
ioengine=io_uring
direct=1
rw=write
bs={p['fio_block_size']}
iodepth={p['fio_queue_depth']}
numjobs={p['fio_num_jobs']}
runtime={p['fio_duration_sec']}
time_based=1
fdp=1
fdp_pli={p['placement_handle']}

[endurance_test]
filename={ns_dev}
"""
        fio_stats = {}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fio", delete=False) as f:
            f.write(fio_job)
            fio_path = f.name

        try:
            fio_result = subprocess.run(
                ["fio", "--output-format=json", fio_path],
                capture_output=True, text=True,
                timeout=p["fio_duration_sec"] + 60
            )
            log(f"  FIO return code: {fio_result.returncode}")

            if fio_result.returncode != 0:
                stderr = fio_result.stderr.strip()
                if "fdp" in stderr.lower():
                    return TestResult(
                        TestStatus.WARN,
                        f"FIO does not support FDP on this system: {stderr[:200]}. "
                        "Requires fio 3.34+ and kernel 6.2+ with io_uring"
                    )
                return TestResult(TestStatus.FAIL, f"FIO failed: {stderr[:300]}")

            try:
                fio_data = json.loads(fio_result.stdout)
                jobs = fio_data.get("jobs", [])
                if jobs:
                    wr = jobs[0].get("write", {})
                    fio_stats = {
                        "bw_mbs":    round(wr.get("bw_bytes", 0) / 1e6, 1),
                        "iops":      round(wr.get("iops", 0), 1),
                        "lat_us":    round(wr.get("lat_ns", {}).get("mean", 0) / 1000, 1),
                        "io_bytes":  wr.get("io_bytes", 0),
                    }
                    log(f"  ✓ FIO done — {fio_stats['bw_mbs']} MB/s  {fio_stats['iops']} IOPS  "
                        f"lat={fio_stats['lat_us']}µs  written={fio_stats['io_bytes']//1024//1024}MB")
            except Exception:
                log("  FIO output parsing failed — continuing with SMART check")
        finally:
            os.unlink(fio_path)

        # ── Step 5: Read SMART log after ──────────────────────────────────────
        log("\nStep 5: Reading SMART log (post-workload)...")
        smart_after = self._read_smart(driver, log)
        if smart_after is None:
            return TestResult(
                TestStatus.WARN,
                "FIO workload completed but SMART log could not be re-read for WAF calculation"
            )

        host_written_after = self._get_host_written(smart_after)
        nand_written_after = self._get_nand_written(smart_after)
        log(f"  Host written (after):  {host_written_after:,} units")
        log(f"  NAND written (after):  {nand_written_after:,} units")

        # ── Step 6: Calculate WAF ─────────────────────────────────────────────
        log("\nStep 6: Calculating Write Amplification Factor (WAF)...")
        delta_host = host_written_after - host_written_before
        delta_nand = nand_written_after - nand_written_before

        log(f"  ΔHost written: {delta_host:,} units")
        log(f"  ΔNAND written: {delta_nand:,} units")

        if delta_host <= 0:
            return TestResult(
                TestStatus.WARN,
                "Host-written units did not increase in SMART log — "
                "device may update SMART counters infrequently or at coarse granularity"
            )

        if delta_nand <= 0:
            log("  NAND-written counter did not change (vendor-specific field may not be supported)")
            waf = None
        else:
            waf = round(delta_nand / delta_host, 3)
            log(f"  WAF = {delta_nand} / {delta_host} = {waf}")

        # ── Step 7: Read RUHS after for capacity delta ────────────────────────
        ruhs_after_result = driver.fdp_ruhs(ns=p["namespace"])
        ruhs_after = self._extract_ruhs(ruhs_after_result) if ruhs_after_result["rc"] == 0 else []
        total_cap_after = sum(int(r.get("ruamw", r.get("RUAMWSectors", 0))) for r in ruhs_after)
        cap_delta = total_cap_before - total_cap_after
        log(f"  Total RUHS capacity consumed: {cap_delta:,} sectors")

        # ── Evaluate result ───────────────────────────────────────────────────
        details = {
            "waf": waf,
            "delta_host_written": delta_host,
            "delta_nand_written": delta_nand,
            "ruhs_capacity_consumed_sectors": cap_delta,
            **fio_stats,
        }

        if waf is None:
            return TestResult(
                TestStatus.WARN,
                f"FIO completed. WAF could not be calculated (NAND-written counter unsupported). "
                f"Host wrote {delta_host} units. RUHS consumed {cap_delta} sectors.",
                details=details
            )

        if waf <= 1.5:
            verdict = f"Excellent WAF {waf} — FDP placement is highly effective"
            status = TestStatus.PASS
        elif waf <= 3.0:
            verdict = f"Acceptable WAF {waf} — some write amplification observed"
            status = TestStatus.WARN
        else:
            verdict = f"High WAF {waf} — FDP may not be reducing write amplification effectively"
            status = TestStatus.WARN

        log(f"\n{'✓' if status == TestStatus.PASS else '⚠'} {verdict}")
        return TestResult(status, verdict, details=details)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _read_smart(self, driver, log) -> dict | None:
        result = driver.run_cmd(["smart-log", driver.device], json_out=True)
        if result["rc"] != 0:
            log(f"  SMART log error: {result['stderr'].strip()}")
            return None
        return result.get("data", {})

    def _get_host_written(self, smart: dict) -> int:
        for key in ("data_units_written", "DataUnitsWritten", "data_units_write"):
            if key in smart:
                val = smart[key]
                # SMART returns 512-byte units; may be dict with 'lo'/'hi' for 128-bit
                if isinstance(val, dict):
                    return int(val.get("lo", 0)) + (int(val.get("hi", 0)) << 64)
                return int(val)
        return 0

    def _get_nand_written(self, smart: dict) -> int:
        # Vendor-specific field — common keys across major NVMe vendors
        for key in ("nand_bytes_written", "physical_media_units_written",
                    "PhysicalMediaUnitsWritten", "nand_writes_1gib",
                    "vendor_specific_media_units_written"):
            if key in smart:
                val = smart[key]
                if isinstance(val, dict):
                    return int(val.get("lo", 0)) + (int(val.get("hi", 0)) << 64)
                return int(val)
        return 0

    def _extract_ruhs(self, result: dict) -> list:
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("ruhs", "ReclaimUnitHandles", "ruhsd", "reclaim_unit_handle_descriptors"):
                if key in data:
                    return data[key]
        return []
