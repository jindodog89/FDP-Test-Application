"""
Test: fdp_endurance
Run an FDP-aware FIO workload and calculate Write Amplification Factor (WAF)
by reading FDP stats (nvme fdp stats) before and after. Also reports per-handle capacity
consumption for FDP efficiency analysis.
"""

import subprocess
import json
import tempfile
import os
from tests.base_test import BaseTest, TestResult, TestStatus


class TestFDPEndurance(BaseTest):
    test_id = "fdp_endurance"
    name = "I5. Endurance — WAF Calculation"
    description = (
        "Runs an FDP-aware FIO write workload and calculates Write Amplification "
        "Factor (WAF) by comparing host bytes media written (hbmw) and media bytes "
        "media written (mbmw) from nvme fdp stats before and after the workload. "
        "A WAF close to 1.0 indicates optimal FDP placement efficiency."
    )
    category = "IO"
    tags = ["fio", "waf", "fdp-stats", "endurance", "write-amplification"]

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

        # ── Step 1: Read FDP stats baseline ───────────────────────────────────
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        log("Step 1: Reading FDP stats (baseline)...")
        stats_before = self._read_fdp_stats(driver, log, endgrp)
        if stats_before is None:
            return TestResult(TestStatus.FAIL, "Cannot read FDP stats — required for WAF calculation")

        host_written_before = stats_before["hbmw"]
        nand_written_before = stats_before["mbmw"]
        log(f"  Host bytes media written (before): {host_written_before:,}")
        log(f"  Media bytes media written (before): {nand_written_before:,}")

        # ── Step 2: Read RUHS baseline ────────────────────────────────────────
        log("\nStep 2: Reading RUHS baseline...")
        ruhs_before_result = driver.fdp_ruhs(ns=p["namespace"])
        ruhs_before = driver.extract_ruhs(ruhs_before_result) if ruhs_before_result["rc"] == 0 else []
        total_cap_before = sum(int(r.get("ruamw", 0)) for r in ruhs_before)
        log(f"  Total RUHS capacity before: {total_cap_before:,} sectors across {len(ruhs_before)} handle(s)")

        # ── Step 3: Check FIO ─────────────────────────────────────────────────
        log("\nStep 3: Verifying FIO availability...")
        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP, "fio not found — install with: sudo apt install fio")
        log("  ✓ fio found")
        # Ensure io_uring is enabled (disabled by default on some kernels after boot)
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        # ── Step 4: Run FIO ───────────────────────────────────────────────────
        # io_uring_cmd requires a generic char device (/dev/ngXnY) rather than
        # the block namespace device (/dev/nvmeXnY). Derive it from driver.device:
        #   /dev/nvme0n1  →  /dev/ng0n1
        #   /dev/nvme1n2  →  /dev/ng1n2
        import re as _re
        _m = _re.search(r'nvme(\d+)n(\d+)', driver.device)
        ng_dev = f"/dev/ng{_m.group(1)}n{_m.group(2)}" if _m else driver.device
        log(f"\nStep 4: Running FIO workload on {ng_dev} (io_uring_cmd)...")
        log(f"  Duration: {p['fio_duration_sec']}s  BS: {p['fio_block_size']}  "
            f"QD: {p['fio_queue_depth']}  Jobs: {p['fio_num_jobs']}")

        fio_job = self._build_fio_job(ng_dev, p)

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
                log("  FIO output parsing failed — continuing with FDP stats check")
        finally:
            os.unlink(fio_path)

        # ── Step 5: Read FDP stats after ──────────────────────────────────────
        log("\nStep 5: Reading FDP stats (post-workload)...")
        stats_after = self._read_fdp_stats(driver, log, endgrp)
        if stats_after is None:
            return TestResult(
                TestStatus.WARN,
                "FIO workload completed but FDP stats could not be re-read for WAF calculation"
            )

        host_written_after = stats_after["hbmw"]
        nand_written_after = stats_after["mbmw"]
        log(f"  Host bytes media written (after):  {host_written_after:,}")
        log(f"  Media bytes media written (after): {nand_written_after:,}")

        # ── Step 6: Calculate WAF ─────────────────────────────────────────────
        log("\nStep 6: Calculating Write Amplification Factor (WAF)...")
        delta_host = host_written_after - host_written_before
        delta_nand = nand_written_after - nand_written_before

        log(f"  ΔHost bytes media written:  {delta_host:,}")
        log(f"  ΔMedia bytes media written: {delta_nand:,}")

        if delta_host <= 0:
            return TestResult(
                TestStatus.WARN,
                "Host bytes media written did not increase — "
                "device may update FDP stats counters infrequently"
            )

        if delta_nand <= 0:
            log("  Media bytes media written did not change")
            waf = None
        else:
            waf = round(delta_nand / delta_host, 3)
            log(f"  WAF = {delta_nand} / {delta_host} = {waf}")

        # ── Step 7: Read RUHS after for capacity delta ────────────────────────
        ruhs_after_result = driver.fdp_ruhs(ns=p["namespace"])
        ruhs_after = driver.extract_ruhs(ruhs_after_result) if ruhs_after_result["rc"] == 0 else []
        total_cap_after = sum(int(r.get("ruamw", 0)) for r in ruhs_after)
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
                f"FIO completed. WAF could not be calculated (mbmw counter did not change). "
                f"Host wrote {delta_host} bytes. RUHS consumed {cap_delta} sectors.",
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

    def _build_fio_job(self, ng_dev: str, p: dict) -> str:
        """Build an FDP fio job using io_uring_cmd against the generic char device."""
        lines = [
            "[global]",
            "ioengine=io_uring_cmd",
            "rw=write",
            f"bs={p['fio_block_size']}",
            f"iodepth={p['fio_queue_depth']}",
            f"numjobs={p['fio_num_jobs']}",
            f"runtime={p['fio_duration_sec']}",
            "time_based=1",
            "fdp=1",
            f"fdp_pli={p['placement_handle']}",
            "fdp_pli_select=roundrobin",
            "",
            "[endurance_test]",
            f"filename={ng_dev}",
            "",
        ]
        return "\n".join(lines)

    def _read_fdp_stats(self, driver, log, endgrp: int = 1) -> dict | None:
        """
        Read FDP statistics via `nvme fdp stats`.
        Returns {"hbmw": <int>, "mbmw": <int>} or None on failure.
          hbmw : Host Bytes Media Written
          mbmw : Media Bytes Media Written (used for WAF denominator)
        """
        result = driver.run_cmd(
            ["fdp", "stats", driver.device, f"--endgrp-id={endgrp}"],
            json_out=True
        )
        if result["rc"] != 0:
            log(f"  FDP stats error: {result['stderr'].strip()}")
            return None
        data = result.get("data", {})
        if not isinstance(data, dict):
            log("  FDP stats returned unexpected format")
            return None
        return {
            "hbmw": int(data.get("hbmw", 0)),
            "mbmw": int(data.get("mbmw", 0)),
        }