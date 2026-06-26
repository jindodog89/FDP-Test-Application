"""
Test: E0. Endurance — Pre-conditioning
Sequence:
  1. Read total NVM capacity from id-ctrl (tnvmcap).
  2. Delete all existing namespaces.
  3. Create one namespace spanning the entire device capacity using the
     configured number of RUHs (n_ruhs, default 4) — matching the
     configuration used by E1 and E2.
  4. Run 3 sequential full-device 4k write passes via fio to bring the device
     into a steady-state condition before endurance measurements are taken.

Pass criteria: all 3 sequential-fill passes complete without fio error.
"""

import subprocess
import re as _re
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.utils import attach_ns
from tests.endurance.precondition import run_precondition


class TestPreconditioning(BaseTest):
    test_id  = "endurance_precondition"
    name     = "E0. Endurance — Pre-conditioning"
    description = (
        "Deletes all namespaces and creates one full-capacity namespace with "
        "n_ruhs RU Handles (default 4, configurable). Then runs 3 sequential "
        "full-device 4k write passes via fio (io_uring_cmd, size=100%) to "
        "bring the device into steady state before endurance workloads."
    )
    category = "Endurance"
    tags     = ["fio", "preconditioning", "endurance", "sequential-write",
                "long-running", "namespace-setup"]

    DEFAULT_PARAMS = {
        "endgrp":          1,
        "n_ruhs":          4,
        "lba_size_bytes":  4096,
        "passes":          3,
        "fio_block_size":  "128k",
        "fio_queue_depth": 64,
        "fio_num_jobs":    4,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        endgrp   = p["endgrp"]
        n_ruhs   = int(p["n_ruhs"])
        lba_sz   = int(p["lba_size_bytes"])
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)

        # ── Pre-flight ────────────────────────────────────────────────────────
        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP,
                              "fio not found — install with: sudo apt install fio")
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        # ══════════════════════════════════════════════════════════════════════
        # Phase 1: Read total capacity from id-ctrl
        # ══════════════════════════════════════════════════════════════════════
        log("Phase 1: Reading total NVM capacity from id-ctrl (tnvmcap)...")
        idctrl_r = driver.run_cmd(["id-ctrl", ctrl_dev], json_out=True)
        if idctrl_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              f"id-ctrl failed: {idctrl_r['stderr'].strip()}")
        idctrl = idctrl_r.get("data", {})
        if not isinstance(idctrl, dict):
            return TestResult(TestStatus.FAIL,
                              "id-ctrl returned unexpected data format")

        tnvmcap_bytes = int(idctrl.get("tnvmcap", 0))
        if tnvmcap_bytes == 0:
            return TestResult(TestStatus.FAIL,
                              "tnvmcap is 0 — cannot determine device capacity")

        nsze_lbas = tnvmcap_bytes // lba_sz
        log(f"  tnvmcap: {tnvmcap_bytes:,} bytes  →  {nsze_lbas:,} LBAs "
            f"(at {lba_sz} B/LBA)  ≈ {tnvmcap_bytes / 1e12:.2f} TB")

        # ══════════════════════════════════════════════════════════════════════
        # Phase 1b: Query device max RUHs from FDP Configurations log
        # ══════════════════════════════════════════════════════════════════════
        log("\nPhase 1b: Querying max RUHs from FDP Configurations log...")
        nruh_from_device = 0
        cfg_r = driver.run_cmd(["fdp", "configs", ctrl_dev,
                                f"--endgrp-id={endgrp}"], json_out=True)
        if cfg_r["rc"] == 0:
            cfg_data = cfg_r.get("data", {})
            configs  = (cfg_data.get("configs") or cfg_data.get("configurations")
                        or cfg_data.get("fdp_configs") or [])
            if configs:
                nruh_from_device = int(configs[0].get("nruh", 0))
        if nruh_from_device > 0:
            log(f"  Device supports {nruh_from_device} RU Handle(s) (nruh from fdp configs)")
            # Use device max, capped by user-supplied n_ruhs if explicitly reduced
            n_ruhs = min(n_ruhs, nruh_from_device) if n_ruhs < nruh_from_device else nruh_from_device
            log(f"  Using n_ruhs = {n_ruhs}")
        else:
            log(f"  Could not read nruh from fdp configs — using n_ruhs = {n_ruhs}")

        # ══════════════════════════════════════════════════════════════════════
        # Phase 2: Delete all namespaces
        # ══════════════════════════════════════════════════════════════════════
        log("\nPhase 2: Deleting all namespaces (broadcast NSID 0xFFFFFFFF)...")
        del_r = driver.run_cmd(["delete-ns", ctrl_dev,
                                "--namespace-id=0xFFFFFFFF"], json_out=False)
        if del_r["rc"] == 0:
            log("  ✓ All namespaces deleted")
        else:
            log(f"  ⚠ delete-ns: {del_r['stderr'].strip()} "
                "(may be none to delete — continuing)")

        # ══════════════════════════════════════════════════════════════════════
        # Phase 3: Create one full-capacity namespace with 4 RUHs
        # ══════════════════════════════════════════════════════════════════════
        phndls = ",".join(str(i) for i in range(n_ruhs))
        log(f"\nPhase 3: Creating namespace "
            f"(nsze={nsze_lbas:,} LBAs, nphndls={n_ruhs}, phndls={phndls})...")
        cr_r = driver.run_cmd([
            "create-ns", ctrl_dev,
            f"--nsze={nsze_lbas}",
            f"--ncap={nsze_lbas}",
            f"--block-size={lba_sz}",
            "--nmic=0",
            f"--endg-id={endgrp}",
            f"--nphndls={n_ruhs}",
            f"--phndls={phndls}",
        ], json_out=False)
        if cr_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              f"create-ns failed: {cr_r['stderr'].strip()}")

        m    = _re.search(r"nsid[:\s]+(\d+)", cr_r["stdout"] + cr_r["stderr"],
                          _re.IGNORECASE)
        nsid = int(m.group(1)) if m else 1
        log(f"  ✓ Created NSID {nsid}")

        at_r = attach_ns(driver, ctrl_dev, nsid, log)
        if at_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              f"attach-ns failed: {at_r['stderr'].strip()}")
        log(f"  ✓ Attached NSID {nsid}")

        ns_dev = ctrl_dev + f"n{nsid}"
        _m     = _re.search(r"nvme(\d+)n(\d+)", ns_dev)
        ng_dev = f"/dev/ng{_m.group(1)}n{_m.group(2)}" if _m else ns_dev
        log(f"  Namespace device: {ns_dev}  →  generic: {ng_dev}")

        # ══════════════════════════════════════════════════════════════════════
        # Phase 4: Pre-conditioning — 3 sequential full-device write passes
        # ══════════════════════════════════════════════════════════════════════
        log(f"\nPhase 4: Pre-conditioning — {p['passes']} sequential fill "
            f"pass(es) on {ng_dev}...")
        ok, msg = run_precondition(
            ng_dev   = ng_dev,
            passes   = int(p["passes"]),
            bs       = p["fio_block_size"],
            iodepth  = int(p["fio_queue_depth"]),
            numjobs  = int(p["fio_num_jobs"]),
            n_ruhs   = n_ruhs,
            log      = log,
        )
        if ok:
            return TestResult(TestStatus.PASS, msg)
        return TestResult(TestStatus.FAIL, msg)