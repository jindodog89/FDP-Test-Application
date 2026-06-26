"""
Test: C1. Sanitize During FDP IO
Issues an nvme sanitize command while a background FIO workload is actively
writing to an FDP-enabled namespace.

Expected behaviour (per NVMe spec):
  - The device may either reject the sanitize with a Command Sequence Error
    (the FDP IO is ongoing), or it may accept the sanitize and abort
    in-flight IO cleanly with appropriate status codes.
  - The device must NOT hang, wedge, or return undefined behaviour.
  - After the sanitize completes (or is rejected), the device must still
    respond to admin commands.

Pass  : Sanitize rejected OR sanitize accepted and device recovered cleanly.
Warn  : Sanitize accepted but FIO errors were unexpected.
Fail  : Device hung, stopped responding, or sanitize returned a fatal error.
"""

import subprocess
import re as _re
import time
import tempfile
import os
from tests.base_test import BaseTest, TestResult, TestStatus
from backend import fio_registry


class TestSanitizeDuringFDPIO(BaseTest):
    test_id  = "corner_sanitize_during_fdp_io"
    name     = "C1. Sanitize During FDP IO"
    description = (
        "Starts a background FDP 4k randwrite FIO workload then immediately "
        "issues nvme sanitize (Block Erase). Verifies the device rejects the "
        "sanitize gracefully or accepts it and recovers cleanly. Device must "
        "remain responsive after the operation."
    )
    category = "Corner"
    tags     = ["corner", "sanitize", "race", "fdp-io", "stress"]

    DEFAULT_PARAMS = {
        "fio_duration_sec":  30,    # short — just long enough for sanitize to race
        "fio_block_size":    "4k",
        "fio_queue_depth":   16,
        "fio_num_jobs":      1,
        "sanitize_action":   1,     # 1 = Block Erase, 2 = Overwrite, 4 = Crypto Erase
        "sanitize_delay_sec": 3,    # seconds after FIO launch before issuing sanitize
    }

    def run(self, driver, log) -> TestResult:
        p        = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)

        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP, "fio not found")
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        # ── Validate device has FDP namespace ────────────────────────────────
        log("Step 1: Checking for FDP-enabled namespace...")
        list_r = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        ns_data  = list_r.get("data", {})
        raw_list = (ns_data.get("nsid_list") or ns_data.get("NamespaceList")
                    or (ns_data if isinstance(ns_data, list) else []))
        if not raw_list:
            return TestResult(TestStatus.SKIP,
                              "No namespaces found — run E0 first.")
        first_nsid = int(raw_list[0]["nsid"] if isinstance(raw_list[0], dict)
                         else raw_list[0])
        ns_dev = ctrl_dev + f"n{first_nsid}"
        _m     = _re.search(r"nvme(\d+)n(\d+)", ns_dev)
        ng_dev = f"/dev/ng{_m.group(1)}n{_m.group(2)}" if _m else ns_dev
        ruhs_r = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        if ruhs_r["rc"] != 0 or not driver.extract_ruhs(ruhs_r):
            return TestResult(TestStatus.SKIP,
                              "FDP not configured — run E0 first.")
        log(f"  Namespace: {ns_dev}  generic: {ng_dev}")

        # ── Build fio job ─────────────────────────────────────────────────────
        log("Step 2: Launching background FDP IO...")
        fio_job = "\n".join([
            "[global]",
            "ioengine=io_uring_cmd",
            "rw=randwrite",
            f"bs={p['fio_block_size']}",
            f"iodepth={p['fio_queue_depth']}",
            f"numjobs={p['fio_num_jobs']}",
            f"runtime={p['fio_duration_sec']}",
            "time_based=1",
            "fdp=1",
            "fdp_pli=0",
            "fdp_pli_select=roundrobin",
            "",
            "[c1_job]",
            f"filename={ng_dev}",
            "",
        ])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fio",
                                         delete=False) as f:
            f.write(fio_job)
            fio_path = f.name

        fio_proc = subprocess.Popen(
            ["fio", "--output-format=normal", fio_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        fio_registry.set_fio_process(fio_proc)
        log(f"  FIO running (PID {fio_proc.pid}) — waiting "
            f"{p['sanitize_delay_sec']}s before sanitize...")
        time.sleep(p["sanitize_delay_sec"])

        # ── Issue sanitize ────────────────────────────────────────────────────
        log(f"Step 3: Issuing nvme sanitize (action={p['sanitize_action']}) "
            f"to {ctrl_dev} while FIO is in flight...")
        san_r = driver.run_cmd([
            "sanitize", ctrl_dev,
            f"--sanact={p['sanitize_action']}",
        ], json_out=False)
        sanitize_rc      = san_r["rc"]
        sanitize_stdout  = san_r["stdout"].strip()
        sanitize_stderr  = san_r["stderr"].strip()
        log(f"  Sanitize rc={sanitize_rc}  "
            f"{'accepted' if sanitize_rc == 0 else 'rejected'}")
        if sanitize_stdout:
            log(f"  stdout: {sanitize_stdout[:200]}")
        if sanitize_stderr:
            log(f"  stderr: {sanitize_stderr[:200]}")

        # ── Wait for FIO to finish ────────────────────────────────────────────
        log("Step 4: Waiting for FIO workload to finish...")
        try:
            fio_stdout, fio_stderr = fio_proc.communicate(
                timeout=p["fio_duration_sec"] + 30)
            fio_rc = fio_proc.returncode
        except subprocess.TimeoutExpired:
            fio_proc.kill()
            fio_stdout, fio_stderr = fio_proc.communicate()
            fio_rc = fio_proc.returncode
            log("  ⚠ FIO timed out — killed")
        finally:
            fio_registry.set_fio_process(None)
            os.unlink(fio_path)

        log(f"  FIO exited rc={fio_rc}")

        # ── Verify device still responds ──────────────────────────────────────
        log("Step 5: Verifying device still responds to admin commands...")
        id_r = driver.run_cmd(["id-ctrl", ctrl_dev], json_out=True)
        device_alive = id_r["rc"] == 0
        log(f"  id-ctrl rc={id_r['rc']}  "
            f"{'✓ device responsive' if device_alive else '✗ device not responding'}")

        # ── If sanitize was accepted, wait for it to complete ─────────────────
        if sanitize_rc == 0:
            log("Step 6: Polling sanitize log until complete...")
            for attempt in range(60):
                time.sleep(5)
                sl_r = driver.run_cmd(["sanitize-log", ctrl_dev], json_out=True)
                sl_data = sl_r.get("data", {})
                progress = None
                if isinstance(sl_data, dict):
                    progress = sl_data.get("sprog") or sl_data.get("progress")
                if progress is not None:
                    log(f"  Sanitize progress: {progress}")
                    if int(progress) >= 65535:   # 0xFFFF = complete
                        log("  ✓ Sanitize complete")
                        break
                else:
                    break

        # ── Verdict ───────────────────────────────────────────────────────────
        if not device_alive:
            return TestResult(TestStatus.FAIL,
                              "Device stopped responding after sanitize — critical error")

        if sanitize_rc != 0:
            return TestResult(TestStatus.PASS,
                              f"Sanitize correctly rejected during FDP IO "
                              f"(rc={sanitize_rc}): {sanitize_stderr[:100]}")

        # Sanitize was accepted
        if fio_rc not in (0, -15, 1):   # 1 is acceptable (IO aborted by sanitize)
            return TestResult(TestStatus.WARN,
                              f"Sanitize accepted — device recovered but FIO "
                              f"exited with unexpected rc={fio_rc}")

        return TestResult(TestStatus.PASS,
                          "Sanitize accepted during FDP IO — device recovered cleanly")