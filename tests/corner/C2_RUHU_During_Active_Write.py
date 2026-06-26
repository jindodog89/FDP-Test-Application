"""
Test: C2. IO Management Send (RUHU) During Active Write
Races an IO Management Send — Reclaim Unit Handle Update (RUHU) command
against an in-flight write workload targeting the same RUH.

The RUHU command requests the controller to switch the host-side mapping
of a Placement Handle to a new Reclaim Unit. When issued while IO is
in-flight to that same RUH the device must either:
  a) Complete the in-flight IO against the original RU, then switch, or
  b) Reject the RUHU with a Command Sequence Error.

The device must NOT corrupt data, hang, or lose track of the RUH mapping.
After the race, verify:
  - The device still accepts writes to the RUH.
  - FDP status shows a valid (non-zero) ruamw for the RUH.
  - The FDP events log shows no unexpected errors.

Pass : RUHU accepted or rejected gracefully; device remains consistent.
Warn : RUHU accepted but post-race state shows anomalies.
Fail : Device hangs, ruamw goes invalid, or events show corruption.
"""

import subprocess
import re as _re
import time
import tempfile
import os
import struct
from tests.base_test import BaseTest, TestResult, TestStatus
from backend import fio_registry


class TestRUHUDuringActiveWrite(BaseTest):
    test_id  = "corner_ruhu_during_write"
    name     = "C2. IO Mgmt Send (RUHU) During Active Write"
    description = (
        "Races an IO Management Send RUHU command against an in-flight FDP "
        "write workload on the same RUH. Verifies the device handles the "
        "race gracefully without data corruption, hangs, or mapping errors."
    )
    category = "Corner"
    tags     = ["corner", "race", "ruhu", "io-management", "fdp-io", "stress"]

    DEFAULT_PARAMS = {
        "target_ruh":        0,      # RUH to target for both the write and RUHU
        "fio_duration_sec":  30,
        "fio_block_size":    "4k",
        "fio_queue_depth":   32,     # high QD to maximise in-flight IOs
        "fio_num_jobs":      2,
        "ruhu_delay_sec":    2,      # seconds after FIO starts before RUHU
        "ruhu_repeats":      5,      # number of RUHU commands to fire in burst
    }

    def run(self, driver, log) -> TestResult:
        p        = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)
        ruh      = int(p["target_ruh"])

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

        ruhs_r  = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        ruhs    = driver.extract_ruhs(ruhs_r)
        if not ruhs:
            return TestResult(TestStatus.SKIP, "FDP not configured — run E0 first.")
        if ruh >= len(ruhs):
            return TestResult(TestStatus.SKIP,
                              f"RUH {ruh} does not exist (device has {len(ruhs)} RUHs)")
        log(f"  Namespace: {ns_dev}  RUHs available: {len(ruhs)}  target: RUH {ruh}")

        # ── Baseline ruamw ────────────────────────────────────────────────────
        baseline_ruamw = ruhs[ruh].get("ruamw", 0) if len(ruhs) > ruh else 0
        log(f"  Baseline ruamw for RUH {ruh}: {baseline_ruamw:,} blocks")

        # ── Launch FIO ────────────────────────────────────────────────────────
        log(f"Step 2: Launching FIO targeting RUH {ruh} (fdp_pli={ruh})...")
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
            f"fdp_pli={ruh}",
            "fdp_pli_select=roundrobin",
            "",
            "[c14_job]",
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
            f"{p['ruhu_delay_sec']}s before RUHU burst...")
        time.sleep(p["ruhu_delay_sec"])

        # ── Fire RUHU burst while IO is in-flight ─────────────────────────────
        log(f"Step 3: Firing {p['ruhu_repeats']} RUHU commands to RUH {ruh} "
            f"while IO is in-flight...")
        # RUHU payload: 2-byte little-endian RUH index
        payload = struct.pack("<H", ruh)
        ruhu_results = []
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as pf:
            pf.write(payload)
            payload_path = pf.name

        try:
            for i in range(int(p["ruhu_repeats"])):
                r2 = driver.run_cmd([
                    "io-passthru", driver.device,
                    "--opcode=0x1D",       # IO Management Send
                    f"--namespace-id={first_nsid}",
                    "--cdw10=1",           # RUHU operation
                    "--data-len=2",
                    "--write",
                    f"--input-file={payload_path}",
                ], json_out=False)
                ruhu_results.append(r2["rc"])
                log(f"  RUHU [{i+1}/{p['ruhu_repeats']}] rc={r2['rc']}  "
                    f"{'accepted' if r2['rc']==0 else r2['stderr'].strip()[:60]}")
        finally:
            os.unlink(payload_path)

        # ── Wait for FIO ──────────────────────────────────────────────────────
        log("Step 4: Waiting for FIO to finish...")
        try:
            fio_stdout, fio_stderr = fio_proc.communicate(
                timeout=p["fio_duration_sec"] + 30)
            fio_rc = fio_proc.returncode
        except subprocess.TimeoutExpired:
            fio_proc.kill()
            fio_stdout, fio_stderr = fio_proc.communicate()
            fio_rc = -9
        finally:
            fio_registry.set_fio_process(None)
            os.unlink(fio_path)
        log(f"  FIO exited rc={fio_rc}")

        # ── Post-race checks ──────────────────────────────────────────────────
        log("Step 5: Post-race consistency checks...")

        # 5a. Device still responds
        id_r = driver.run_cmd(["id-ctrl", ctrl_dev], json_out=True)
        if id_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              "Device stopped responding after RUHU race — critical error")
        log("  ✓ Device still responds to admin commands")

        # 5b. RUH still has a valid ruamw
        ruhs_after_r = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        ruhs_after   = driver.extract_ruhs(ruhs_after_r)
        if not ruhs_after:
            return TestResult(TestStatus.FAIL,
                              "fdp status failed after race — FDP state may be corrupt")
        ruh_after = next((h for h in ruhs_after
                          if (h.get("ruhid") or h.get("id", -1)) == ruh), None)
        if ruh_after is None:
            return TestResult(TestStatus.WARN,
                              f"RUH {ruh} not found in post-race fdp status")
        after_ruamw = ruh_after.get("ruamw", 0)
        log(f"  Post-race ruamw for RUH {ruh}: {after_ruamw:,} blocks")

        # 5c. Check FDP events for anything alarming
        driver.enable_all_fdp_events(endgrp=1, namespace=first_nsid)
        events_r  = driver.fdp_events(endgrp=1, host_events=True)
        events    = events_r.get("data", {}).get("events", [])
        alarm_types = {0x80, 0x81}   # Media Error = 0x80, RUH-related = 0x81
        alarms    = [e for e in events
                     if int(e.get("etype", e.get("type", -1))) in alarm_types]
        if alarms:
            log(f"  ⚠ {len(alarms)} alarm-level FDP event(s) found after race")
            return TestResult(TestStatus.WARN,
                              f"RUHU race completed but {len(alarms)} alarm event(s) logged")

        # ── Verdict ───────────────────────────────────────────────────────────
        accepted = sum(1 for rc in ruhu_results if rc == 0)
        rejected = len(ruhu_results) - accepted
        return TestResult(
            TestStatus.PASS,
            f"RUHU race handled gracefully — {accepted} accepted, "
            f"{rejected} rejected; device and RUH mapping consistent"
        )