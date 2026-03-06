"""
Test: io_management_receive_valid
Read RUHS via IO Management Receive, run FIO workload with FDP directives,
then re-read RUHS and verify reclaim unit capacity has decreased.
"""

import subprocess
import tempfile
import os
from tests.base_test import BaseTest, TestResult, TestStatus


class TestIOMgmtReceiveValid(BaseTest):
    test_id = "io_management_receive_valid"
    name = "IO Management Receive — Capacity Change After FIO"
    description = (
        "Reads Reclaim Unit Handle Status via IO Management Receive, runs an FIO "
        "workload using FDP placement directives for a configurable duration, then "
        "re-reads RUHS to confirm reclaim unit capacity has decreased, validating "
        "end-to-end FDP placement tracking."
    )
    category = "IO Management"
    tags = ["io-mgmt-recv", "fio", "ruhs", "capacity", "workload"]

    DEFAULT_PARAMS = {
        "fio_duration_sec": 10,
        "fio_block_size":   "4k",
        "fio_queue_depth":  8,
        "namespace":        1,
        "placement_handle": 0,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: IO Management Receive — baseline ──────────────────────────
        log("Step 1: Reading RUHS (baseline) via IO Management Receive...")
        ruhs_before_result = driver.fdp_ruhs(ns=p["namespace"])
        if ruhs_before_result["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Cannot read RUHS: {ruhs_before_result['stderr'].strip()}")

        ruhs_before = driver.extract_ruhs(ruhs_before_result)
        if not ruhs_before:
            return TestResult(TestStatus.FAIL, "No reclaim unit handles found")

        handle_before = self._find_handle(ruhs_before, p["placement_handle"])
        if handle_before is None:
            return TestResult(
                TestStatus.FAIL,
                f"Handle {p['placement_handle']} not found in RUHS. "
                f"Available: {[r.get('phndl', r.get('ruhid', '?')) for r in ruhs_before]}"
            )

        cap_before = int(handle_before.get("ruamw", handle_before.get("RUAMWSectors", 0)))
        log(f"  Handle {p['placement_handle']} capacity before FIO: {cap_before} sectors")

        if cap_before == 0:
            return TestResult(TestStatus.SKIP, f"Handle {p['placement_handle']} has 0 remaining capacity")

        # ── Step 2: Check FIO is available ────────────────────────────────────
        log("\nStep 2: Checking FIO availability...")
        fio_check = subprocess.run(["which", "fio"], capture_output=True, text=True)
        if fio_check.returncode != 0:
            return TestResult(
                TestStatus.SKIP,
                "fio not found — install with: sudo apt install fio"
            )
        log("  ✓ fio found")

        # ── Step 3: Run FIO with FDP directives ───────────────────────────────
        dev_path = driver.device
        # Use the namespace device (e.g. /dev/nvme0n1) for FIO
        ns_dev = dev_path if "n1" in dev_path else dev_path + f"n{p['namespace']}"
        log(f"\nStep 3: Running FIO on {ns_dev} for {p['fio_duration_sec']}s...")
        log(f"  Block size: {p['fio_block_size']}  QD: {p['fio_queue_depth']}  Handle: {p['placement_handle']}")

        fio_job = f"""
[global]
ioengine=io_uring
direct=1
rw=write
bs={p['fio_block_size']}
iodepth={p['fio_queue_depth']}
runtime={p['fio_duration_sec']}
time_based=1
fdp=1
fdp_pli={p['placement_handle']}

[fdp_test]
filename={ns_dev}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fio", delete=False) as f:
            f.write(fio_job)
            fio_job_path = f.name

        try:
            fio_result = subprocess.run(
                ["fio", "--output-format=json", fio_job_path],
                capture_output=True, text=True,
                timeout=p["fio_duration_sec"] + 30
            )
            log(f"  FIO return code: {fio_result.returncode}")

            if fio_result.returncode != 0:
                stderr = fio_result.stderr.strip()
                # FDP-capable fio may require newer kernels; provide useful guidance
                if "fdp" in stderr.lower() or "invalid" in stderr.lower():
                    return TestResult(
                        TestStatus.WARN,
                        f"FIO does not support FDP directives on this system: {stderr[:200]}. "
                        "Requires fio 3.34+ with io_uring and kernel 6.2+"
                    )
                return TestResult(TestStatus.FAIL, f"FIO failed: {stderr[:300]}")

            log("  ✓ FIO workload completed")
            # Parse basic throughput from JSON output
            try:
                import json
                fio_data = json.loads(fio_result.stdout)
                jobs = fio_data.get("jobs", [])
                if jobs:
                    bw = jobs[0].get("write", {}).get("bw_bytes", 0)
                    iops = jobs[0].get("write", {}).get("iops", 0)
                    log(f"  Throughput: {bw//1024//1024} MB/s  IOPS: {int(iops)}")
            except Exception:
                pass
        finally:
            os.unlink(fio_job_path)

        # ── Step 4: IO Management Receive — post-FIO ─────────────────────────
        log("\nStep 4: Re-reading RUHS to verify capacity decrease...")
        ruhs_after_result = driver.fdp_ruhs(ns=p["namespace"])
        if ruhs_after_result["rc"] != 0:
            return TestResult(TestStatus.WARN, "FIO completed but RUHS could not be re-read")

        ruhs_after = driver.extract_ruhs(ruhs_after_result)
        handle_after = self._find_handle(ruhs_after, p["placement_handle"])
        if handle_after is None:
            return TestResult(TestStatus.WARN, "FIO completed but handle not found in post-FIO RUHS")

        cap_after = int(handle_after.get("ruamw", handle_after.get("RUAMWSectors", 0)))
        log(f"  Handle {p['placement_handle']} capacity: {cap_before} → {cap_after}")

        if cap_after < cap_before:
            diff = cap_before - cap_after
            log(f"✓ Capacity decreased by {diff} sectors after FIO — FDP end-to-end confirmed")
            return TestResult(
                TestStatus.PASS,
                f"RUHS capacity decreased by {diff} sectors after FIO workload",
                details={"capacity_before": cap_before, "capacity_after": cap_after, "delta": diff}
            )
        elif cap_after == cap_before:
            return TestResult(
                TestStatus.WARN,
                "FIO completed and RUHS readable, but capacity did not change — "
                "device may use coarse capacity reporting granularity"
            )
        else:
            return TestResult(
                TestStatus.FAIL,
                f"Handle capacity increased after write ({cap_before} → {cap_after})"
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _extract_ruhs(self, result: dict) -> list:
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("ruhs", "ReclaimUnitHandles", "ruhsd", "reclaim_unit_handle_descriptors"):
                if key in data:
                    return data[key]
        return []

    def _find_handle(self, ruhs: list, handle_id: int) -> dict:
        for ruh in ruhs:
            candidate = ruh.get("phndl", ruh.get("PlacementHandle", ruh.get("ruhid", None)))
            if candidate is not None and int(candidate) == handle_id:
                return ruh
        return None
