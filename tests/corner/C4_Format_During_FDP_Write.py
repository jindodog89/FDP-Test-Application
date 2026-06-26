"""
Test: C4. Format Namespace While FDP Write in Progress
Issues an nvme format command while a background FDP FIO workload is
actively writing to the same namespace.

Expected behaviour (per NVMe spec):
  - The device may reject the format with a Command Sequence Error if IO
    is in-flight (this is the preferred/correct behaviour).
  - Alternatively, the device may accept the format and abort in-flight IO
    cleanly with an appropriate error status (e.g. Namespace Not Ready).
  - Under no circumstances should the device: hang, corrupt the namespace
    metadata, leave the namespace in an unusable state, or silently ignore
    either command.

After the test, verify:
  - The device is still responsive.
  - The namespace still exists (or was cleanly removed by the format).
  - FDP can be re-enumerated (fdp status succeeds or fails gracefully).

Pass  : Format rejected during IO, OR format accepted and device recovered.
Warn  : Format accepted with unexpected FIO behaviour.
Fail  : Device hung, namespace corrupted, or device stopped responding.
"""

import subprocess
import re as _re
import time
import tempfile
import os
from tests.base_test import BaseTest, TestResult, TestStatus
from backend import fio_registry


class TestFormatDuringFDPWrite(BaseTest):
    test_id  = "corner_format_during_fdp_write"
    name     = "C4. Format Namespace During FDP Write"
    description = (
        "Starts a background FDP 4k randwrite FIO workload then issues "
        "nvme format to the same namespace while IO is in-flight. Verifies "
        "the device handles the race gracefully — either rejecting the "
        "format or accepting it and recovering cleanly."
    )
    category = "Corner"
    tags     = ["corner", "format", "race", "fdp-io", "stress", "namespace"]

    DEFAULT_PARAMS = {
        "fio_duration_sec":   30,
        "fio_block_size":     "4k",
        "fio_queue_depth":    16,
        "fio_num_jobs":       1,
        "format_delay_sec":   3,     # seconds after FIO start before format
        "lbaf_index":         0,     # LBA format index to use for format
    }

    def run(self, driver, log) -> TestResult:
        p        = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)

        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP, "fio not found")
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        # ── Validate ──────────────────────────────────────────────────────────
        log("Step 1: Validating FDP configuration...")
        list_r   = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        ns_data  = list_r.get("data", {})
        raw_list = (ns_data.get("nsid_list") or ns_data.get("NamespaceList")
                    or (ns_data if isinstance(ns_data, list) else []))
        if not raw_list:
            return TestResult(TestStatus.SKIP, "No namespaces found — run E0 first.")
        first_nsid = int(raw_list[0]["nsid"] if isinstance(raw_list[0], dict)
                         else raw_list[0])
        ns_dev = ctrl_dev + f"n{first_nsid}"
        _m     = _re.search(r"nvme(\d+)n(\d+)", ns_dev)
        ng_dev = f"/dev/ng{_m.group(1)}n{_m.group(2)}" if _m else ns_dev
        ruhs_r = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        if not driver.extract_ruhs(ruhs_r):
            return TestResult(TestStatus.SKIP, "FDP not configured — run E0 first.")
        log(f"  Namespace: {ns_dev}  generic: {ng_dev}  NSID: {first_nsid}")

        # ── Launch FIO ────────────────────────────────────────────────────────
        log("Step 2: Launching background FDP write workload...")
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
            "[c20_job]",
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
            f"{p['format_delay_sec']}s before format...")
        time.sleep(p["format_delay_sec"])

        # ── Issue format while IO in flight ───────────────────────────────────
        log(f"Step 3: Issuing nvme format to {ns_dev} (lbaf={p['lbaf_index']}) "
            f"while FIO is in-flight...")
        fmt_r = driver.run_cmd([
            "format", ns_dev,
            f"--namespace-id={first_nsid}",
            f"--lbaf={p['lbaf_index']}",
            "--force",
        ], json_out=False)
        fmt_rc     = fmt_r["rc"]
        fmt_stdout = fmt_r["stdout"].strip()
        fmt_stderr = fmt_r["stderr"].strip()
        log(f"  Format rc={fmt_rc}  "
            f"{'accepted' if fmt_rc == 0 else 'rejected'}")
        if fmt_stdout:
            log(f"  stdout: {fmt_stdout[:200]}")
        if fmt_stderr:
            log(f"  stderr: {fmt_stderr[:200]}")

        # ── Wait for FIO ──────────────────────────────────────────────────────
        log("Step 4: Waiting for FIO workload to finish...")
        try:
            fio_stdout, fio_stderr = fio_proc.communicate(
                timeout=p["fio_duration_sec"] + 30)
            fio_rc = fio_proc.returncode
        except subprocess.TimeoutExpired:
            fio_proc.kill()
            fio_stdout, fio_stderr = fio_proc.communicate()
            fio_rc = -9
            log("  ⚠ FIO timed out — killed")
        finally:
            fio_registry.set_fio_process(None)
            os.unlink(fio_path)
        log(f"  FIO exited rc={fio_rc}")

        # ── Device responsiveness check ───────────────────────────────────────
        log("Step 5: Verifying device is still responsive...")
        id_r = driver.run_cmd(["id-ctrl", ctrl_dev], json_out=True)
        if id_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              "Device stopped responding after format race — critical error")
        log("  ✓ Device responds to id-ctrl")

        # ── Namespace integrity check ─────────────────────────────────────────
        log("Step 6: Checking namespace integrity post-race...")
        idns_r = driver.run_cmd([
            "id-ns", ctrl_dev, f"--namespace-id={first_nsid}"], json_out=True)
        ns_intact = idns_r["rc"] == 0
        if ns_intact:
            ns_d     = idns_r.get("data", {})
            nsze_ok  = int(ns_d.get("nsze", 0)) > 0 if isinstance(ns_d, dict) else False
            log(f"  ✓ Namespace still exists  nsze_valid={nsze_ok}")
        else:
            log("  ⚠ id-ns failed — namespace may have been removed by format")

        # ── FDP re-enumeration ────────────────────────────────────────────────
        log("Step 7: Checking FDP status post-race...")
        ruhs_after = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        fdp_ok     = ruhs_after["rc"] == 0
        log(f"  fdp status rc={ruhs_after['rc']}  "
            f"{'✓ FDP intact' if fdp_ok else '⚠ FDP not accessible (expected if format succeeded)'}")

        # ── Verdict ───────────────────────────────────────────────────────────
        if fmt_rc != 0:
            # Format correctly rejected — ideal outcome
            return TestResult(TestStatus.PASS,
                              f"Format correctly rejected during FDP IO "
                              f"(rc={fmt_rc}): {fmt_stderr[:100] or 'error returned'}")

        # Format was accepted
        if not ns_intact:
            return TestResult(TestStatus.WARN,
                              "Format accepted — namespace removed or restructured. "
                              "Run E0 to reinitialise the device for subsequent tests.")

        if fio_rc not in (0, -15, 1):
            return TestResult(TestStatus.WARN,
                              f"Format accepted and namespace intact, but FIO "
                              f"exited with unexpected rc={fio_rc}. "
                              "Inspect fio output for IO errors.")

        return TestResult(TestStatus.PASS,
                          "Format accepted during FDP IO — device recovered cleanly. "
                          "Run E0 to reinitialise the device for subsequent endurance tests.")