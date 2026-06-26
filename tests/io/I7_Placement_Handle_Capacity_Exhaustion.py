"""
Test: I7. Placement Handle Capacity Exhaustion
Exhausts the Reclaim Unit capacity of a single placement handle by running a
fio sequential-write workload that fills the device using the target PID.

fio is used instead of individual nvme writes because some devices have very
large RUHs (hundreds of GB) that would require millions of individual 4k writes
and take impractically long to exhaust one-by-one.

Pass criteria:
  - fio completes without a fatal error, AND
  - The final ruamw for the target handle is 0 (fully exhausted), OR
  - The device has automatically triggered a Reclaim Unit Handle Update (RUHU)
    (ruamw resets to a higher value, indicating rotation to a new RU).
"""

import subprocess
import tempfile
import os
import re as _re
import time
from tests.base_test import BaseTest, TestResult, TestStatus
from backend import fio_registry


class TestFDPHandleCapacityExhaustion(BaseTest):
    test_id  = "fdp_handle_capacity_exhaustion"
    name     = "I7. Placement Handle Capacity Exhaustion"
    description = (
        "Runs a fio sequential-write workload targeting a single placement "
        "handle (fdp_pli) until the Reclaim Unit's remaining capacity (ruamw) "
        "reaches zero. Verifies the device correctly exhausts the RU and "
        "optionally triggers a new Reclaim Unit Handle Update (RUHU)."
    )
    category = "IO"
    tags     = ["write", "exhaustion", "ruhu", "ruhs", "capacity", "rotation", "fio"]

    DEFAULT_PARAMS = {
        "placement_handle": 0,       # PID / fdp_pli to target
        "namespace":        1,       # NSID
        "fio_block_size":   "128k",  # larger BS = fewer IOPS = faster fill
        "fio_queue_depth":  8,
        "fio_num_jobs":     1,
        "poll_interval_sec": 30,     # how often to check ruamw while fio runs
        "timeout_sec":      86400,   # hard ceiling (24 h)
    }

    def run(self, driver, log) -> TestResult:
        p   = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        pid = int(p["placement_handle"])
        ns  = int(p["namespace"])

        # ── Pre-flight ────────────────────────────────────────────────────────
        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP,
                              "fio not found — install with: sudo apt install fio")
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)
        ns_dev   = ctrl_dev + f"n{ns}"
        m        = _re.search(r"nvme(\d+)n(\d+)", ns_dev)
        ng_dev   = f"/dev/ng{m.group(1)}n{m.group(2)}" if m else ns_dev

        # ── Step 1: Read initial capacity ─────────────────────────────────────
        log(f"Step 1: Reading initial capacity for handle {pid}...")
        ruhs_r = driver.fdp_ruhs(ns=ns)
        if ruhs_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              f"Cannot read RUHS: {ruhs_r['stderr'].strip()}")
        ruhs   = driver.extract_ruhs(ruhs_r)
        handle = self._find_handle(ruhs, pid)
        if handle is None:
            return TestResult(TestStatus.FAIL,
                              f"Handle {pid} not found in RUHS response")

        initial_ruamw = int(handle.get("ruamw", 0))
        lba_size      = 4096   # assume 4 KiB LBAs
        initial_bytes = initial_ruamw * lba_size

        log(f"  Handle {pid}  ruamw={initial_ruamw:,} blocks  "
            f"≈ {initial_bytes / 1e9:.2f} GB")

        if initial_ruamw == 0:
            return TestResult(TestStatus.SKIP,
                              "Handle already at 0 capacity — "
                              "reset device state before running")

        # ── Step 2: Launch fio to fill the RU ────────────────────────────────
        log(f"\nStep 2: Launching fio to fill handle {pid} "
            f"(bs={p['fio_block_size']}, qd={p['fio_queue_depth']}, "
            f"size=100%, timeout={p['timeout_sec']}s)...")

        fio_job = "\n".join([
            "[global]",
            "ioengine=io_uring_cmd",
            "rw=write",
            f"bs={p['fio_block_size']}",
            f"iodepth={p['fio_queue_depth']}",
            f"numjobs={p['fio_num_jobs']}",
            "size=100%",          # fill entire device once
            "fdp=1",
            f"fdp_pli={pid}",
            "fdp_pli_select=roundrobin",
            "",
            f"[i7_exhaust_pid{pid}]",
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
        log(f"  fio started (PID {fio_proc.pid})")

        # ── Step 3: Poll ruamw while fio runs ─────────────────────────────────
        log(f"\nStep 3: Polling ruamw every {p['poll_interval_sec']}s...")
        start_time    = time.time()
        ruhu_detected = False
        prev_ruamw    = initial_ruamw
        polls         = 0

        try:
            while fio_proc.poll() is None:
                time.sleep(p["poll_interval_sec"])
                polls += 1
                elapsed = time.time() - start_time

                ruhs_now = driver.fdp_ruhs(ns=ns)
                if ruhs_now["rc"] == 0:
                    h = self._find_handle(driver.extract_ruhs(ruhs_now), pid)
                    if h:
                        cur_ruamw = int(h.get("ruamw", 0))
                        log(f"  Poll {polls} @ {elapsed:.0f}s — "
                            f"ruamw={cur_ruamw:,} blocks "
                            f"({cur_ruamw * lba_size / 1e9:.2f} GB remaining)")

                        # RUHU detected: ruamw went UP (device rotated to new RU)
                        if cur_ruamw > prev_ruamw:
                            log(f"  ✓ RUHU detected — ruamw rose from "
                                f"{prev_ruamw:,} → {cur_ruamw:,}")
                            ruhu_detected = True

                        prev_ruamw = cur_ruamw

                if elapsed > p["timeout_sec"]:
                    log(f"  ⚠ Timeout ({p['timeout_sec']}s) reached — "
                        f"terminating fio")
                    break

        finally:
            fio_registry.set_fio_process(None)
            if fio_proc.poll() is None:
                fio_proc.terminate()
                try:
                    fio_proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    fio_proc.kill()
            os.unlink(fio_path)

        fio_out, fio_err = fio_proc.communicate()
        log(f"  fio exited (rc={fio_proc.returncode})")
        if fio_err.strip():
            log(f"  fio stderr: {fio_err.strip()[:300]}")

        # ── Step 4: Final ruamw read ──────────────────────────────────────────
        log("\nStep 4: Final RUHS read...")
        final_r = driver.fdp_ruhs(ns=ns)
        final_ruamw = None
        if final_r["rc"] == 0:
            h = self._find_handle(driver.extract_ruhs(final_r), pid)
            if h:
                final_ruamw = int(h.get("ruamw", 0))
                log(f"  Final ruamw for handle {pid}: {final_ruamw:,} blocks "
                    f"({final_ruamw * lba_size / 1e9:.2f} GB remaining)")

        consumed_blocks = initial_ruamw - (final_ruamw or 0)
        details = {
            "initial_ruamw":  initial_ruamw,
            "final_ruamw":    final_ruamw,
            "consumed_blocks": consumed_blocks,
            "ruhu_detected":  ruhu_detected,
            "fio_rc":         fio_proc.returncode,
        }

        # ── Verdict ───────────────────────────────────────────────────────────
        if fio_proc.returncode not in (0, -15):
            return TestResult(TestStatus.FAIL,
                              f"fio exited with rc={fio_proc.returncode} — "
                              f"check stderr for details",
                              details=details)

        if ruhu_detected:
            return TestResult(TestStatus.PASS,
                              f"RUHU triggered — device correctly rotated to a "
                              f"new Reclaim Unit after consuming "
                              f"{consumed_blocks:,} blocks",
                              details=details)

        if final_ruamw == 0:
            return TestResult(TestStatus.PASS,
                              f"Handle {pid} capacity fully exhausted "
                              f"({consumed_blocks:,} blocks consumed) — "
                              "RUHU may be triggered on the next write",
                              details=details)

        return TestResult(TestStatus.WARN,
                          f"fio completed but handle {pid} was not fully exhausted "
                          f"(consumed {consumed_blocks:,} / {initial_ruamw:,} blocks). "
                          "Device may have very large RU — check poll logs.",
                          details=details)

    def _find_handle(self, ruhs: list, ruhid: int) -> dict | None:
        for ruh in ruhs:
            if ruh.get("ruhid") is not None and int(ruh["ruhid"]) == ruhid:
                return ruh
        return None