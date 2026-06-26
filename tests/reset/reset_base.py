"""
reset_base.py — Shared helpers for FDP persistence-across-reset test cases.

Import ResetTestBase and mix it into any reset test class alongside BaseTest:

    class TestMyResetCase(ResetTestBase, BaseTest):
        ...

The mixin provides:
  - FDP enable assertion with clear user guidance
  - Controller / re-enumeration polling helpers
  - FDP Stats log read + field extraction (mbmw, hbmw, mbe)
  - PH→RUH mapping snapshot
  - Directive Receive wrapper for directive capability inspection
  - Short FIO workload runner (FDP-aware writes)
"""

import json
import os
import subprocess
import tempfile
import time

from tests.base_test import TestResult, TestStatus


class ResetTestBase:
    """
    Mixin — must be combined with BaseTest, not used standalone.
    Provides common primitives shared by every reset persistence test.
    """

    # Polling tuning
    RESET_POLL_S     = 1.0   # seconds between id-ctrl probe attempts
    RESET_TIMEOUT_S  = 30    # seconds before we declare controller lost
    RENUM_TIMEOUT_S  = 45    # seconds for full PCIe re-enumeration


    # ── Namespace save / delete / restore ─────────────────────────────────────

    def _save_ns_list(self, driver, log, ctrl_dev: str) -> list:
        import re as _re
        saved = []
        list_r = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        if list_r["rc"] != 0:
            return saved
        data     = list_r.get("data", {})
        raw_list = (data.get("nsid_list") or data.get("NamespaceList")
                    or (data if isinstance(data, list) else []))
        for raw in raw_list:
            nsid = int(raw["nsid"] if isinstance(raw, dict) else raw)
            ns_info = {"nsid": nsid, "nsze": 0, "ncap": 0, "flbas": 0,
                       "nphndls": 0, "endg_id": 1}
            idr = driver.run_cmd(
                ["id-ns", ctrl_dev, f"--namespace-id={nsid}"], json_out=True)
            if idr["rc"] == 0:
                d = idr.get("data", {})
                if isinstance(d, dict):
                    ns_info["nsze"]  = int(d.get("nsze", 0))
                    ns_info["ncap"]  = int(d.get("ncap", ns_info["nsze"]))
                    ns_info["flbas"] = int(d.get("flbas", 0)) & 0xF
            saved.append(ns_info)
        log(f"  Saved {len(saved)} namespace(s)")
        return saved

    def _delete_all_ns(self, driver, log, ctrl_dev: str) -> bool:
        r = driver.run_cmd(
            ["delete-ns", ctrl_dev, "--namespace-id=0xFFFFFFFF"], json_out=False)
        if r["rc"] == 0:
            log("  ✓ All namespaces deleted")
        else:
            log(f"  ⚠ delete-ns: {r['stderr'].strip()}")
        return r["rc"] == 0

    def _restore_ns_list(self, driver, log, ctrl_dev: str, saved: list):
        import re as _re2
        from tests.utils import attach_ns
        for ns in saved:
            args = [
                "create-ns", ctrl_dev,
                f"--nsze={ns['nsze']}",
                f"--ncap={ns['ncap']}",
                f"--flbas={ns['flbas']}",
                "--nmic=0",
                f"--endg-id={ns['endg_id']}",
            ]
            if ns["nphndls"] > 0:
                args.append(f"--nphndls={ns['nphndls']}")
            cr = driver.run_cmd(args, json_out=False)
            if cr["rc"] != 0:
                log(f"  ⚠ create-ns failed: {cr['stderr'].strip()}")
                continue
            out      = cr["stdout"] + cr["stderr"]
            m        = _re2.search(r"nsid[:\s]+(\d+)", out, _re2.IGNORECASE)
            new_nsid = int(m.group(1)) if m else ns["nsid"]
            at       = attach_ns(driver, ctrl_dev, new_nsid, log)
            if at["rc"] == 0:
                log(f"  ✓ Restored NSID {new_nsid}")
            else:
                log(f"  ⚠ attach-ns failed: {at['stderr'].strip()}")

    def _set_fdp_enabled(self, driver, log, ctrl_dev: str,
                          enable: bool, endgrp: int = 1) -> bool:
        cdw10 = 0x1D | 0x80000000
        cdw12 = 0x1 if enable else 0x0
        r = driver.run_cmd([
            "admin-passthru", ctrl_dev, "--opcode=0x09",
            f"--cdw10={cdw10}", f"--cdw11={endgrp}", f"--cdw12={cdw12}",
        ], json_out=False)
        action = "enabled" if enable else "disabled"
        if r["rc"] == 0:
            log(f"  ✓ FDP {action} (Set Features FID 0x1D)")
        else:
            log(f"  ✗ FDP {action} failed: {r['stderr'].strip()}")
        return r["rc"] == 0

    def _reenable_fdp(self, driver, log, p: dict):
        import re as _re
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)
        endgrp   = int(p.get("endgrp", 1))
        log("  Saving namespace geometry...")
        saved = self._save_ns_list(driver, log, ctrl_dev)
        log("  Deleting namespaces before re-enabling FDP...")
        self._delete_all_ns(driver, log, ctrl_dev)
        self._set_fdp_enabled(driver, log, ctrl_dev, enable=True, endgrp=endgrp)
        state = self._get_fdp_enable_state(driver, log, endgrp=endgrp)
        log(f"  FDP state after re-enable: {state}")
        if saved:
            log("  Restoring namespaces...")
            self._restore_ns_list(driver, log, ctrl_dev, saved)

    # ── FDP enable check ──────────────────────────────────────────────────────

    def _get_fdp_enable_state(self, driver, log, endgrp: int = 1) -> bool | None:
        """
        Query FDP enable state via get-feature FID 0x1D.
        Delegates to DUTConfig._parse_fdp_enabled() which handles all the
        device-specific response formats including the nested dict structure
        returned by some nvme-cli builds.
        Returns True (enabled), False (disabled), or None (undetermined).
        """
        import re as _re
        from tests.dut_config import DUTConfig
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)
        feat_r = driver.run_cmd(
            ["get-feature", ctrl_dev,
             "--feature-id=0x1d", f"--cdw11={endgrp}",
             "--namespace-id=0"],
            json_out=True,
        )
        result = DUTConfig._parse_fdp_enabled(feat_r)
        log(f"  FDP enable state: {result}")
        return result
    def _assert_fdp_enabled(self, driver, log, endgrp: int = 1) -> TestResult | None:
        """
        Guard: verify FDP is enabled before proceeding with a test.
        Returns None if enabled, or a TestResult(SKIP) to return immediately.
        Usage:
            skip = self._assert_fdp_enabled(driver, log)
            if skip: return skip
        """
        log("Prerequisite: checking FDP enable state...")
        state = self._get_fdp_enable_state(driver, log, endgrp)
        if state is None:
            return TestResult(
                TestStatus.SKIP,
                "Cannot determine FDP enable state — device may not support FDP. "
                "To enable FDP: nvme fdp <dev> --endgrp-id=1 --enable-conf-idx=0"
            )
        if not state:
            return TestResult(
                TestStatus.SKIP,
                "FDP is not enabled on this device. "
                "Enable it with: nvme fdp <dev> --endgrp-id=1 --enable-conf-idx=0  "
                "Note: device must have no active namespaces before enabling FDP."
            )
        log("  ✓ FDP is enabled")
        return None

    # ── Reset and recovery helpers ────────────────────────────────────────────

    def _do_controller_reset(self, driver, log) -> TestResult | None:
        """
        Issue nvme reset and verify the command is accepted.
        Returns None on success, TestResult(FAIL) on error.
        """
        log("Issuing NVMe Controller Reset (CC.EN = 0 → 1)...")
        r = driver.controller_reset()
        log(f"  Command: {r.get('cmd', 'nvme reset')}")
        log(f"  RC: {r['rc']}")
        if r.get("stderr", "").strip():
            log(f"  stderr: {r['stderr'].strip()}")
        if r["rc"] != 0:
            return TestResult(
                TestStatus.FAIL,
                f"Controller reset command failed (rc={r['rc']}): {r.get('stderr','').strip()}"
            )
        return None

    def _do_subsystem_reset(self, driver, log) -> TestResult | None:
        """
        Issue nvme subsystem-reset (NSSR) and verify the command is accepted.
        Returns None on success, TestResult(FAIL) on error.
        """
        log("Issuing NVM Subsystem Reset (NSSR)...")
        r = driver.subsystem_reset()
        log(f"  Command: {r.get('cmd', 'nvme subsystem-reset')}")
        log(f"  RC: {r['rc']}")
        if r.get("stderr", "").strip():
            log(f"  stderr: {r['stderr'].strip()}")
        if r["rc"] != 0:
            return TestResult(
                TestStatus.FAIL,
                f"Subsystem reset command failed (rc={r['rc']}): {r.get('stderr','').strip()}"
            )
        return None

    def _do_link_reset(self, driver, log) -> TestResult | None:
        """
        PCIe link-level reset via the upstream root port's Link Control register.
        Sets Link Disable (bit 4) then clears it, triggering link retraining.
        Returns None on success, TestResult(FAIL) on error.
        """
        from backend.drivers.pcie_driver import PCIeDriver

        log("Resolving PCIe topology...")
        try:
            pcie = PCIeDriver.from_nvme_device(driver.device)
        except Exception as e:
            return TestResult(TestStatus.FAIL, f"PCIe driver init failed: {e}")

        info = pcie.get_device_info()
        log(f"  Endpoint: {info.get('bdf')}  Upstream: {info.get('upstream_bdf')}")
        log(f"  Link:     {info.get('link_speed', '?')} {info.get('link_width', '?')}")

        if not pcie.upstream_bdf:
            return TestResult(
                TestStatus.FAIL,
                "No upstream PCIe port found — cannot perform link-level reset. "
                "This test requires the device to be behind a root port or switch."
            )

        # Set Link Disable bit
        log("Setting Link Disable bit in upstream port LnkCtl...")
        dis = pcie.disable_link()
        if dis.get("rc", 1) != 0:
            return TestResult(
                TestStatus.FAIL,
                f"Failed to set Link Disable: {dis.get('error', dis.get('stderr', ''))}"
            )
        log(f"  LnkCtl: {dis.get('lnkctl_before')} → {dis.get('lnkctl_after')}  ✓ link disabled")
        time.sleep(0.1)

        # Clear Link Disable bit — triggers link retraining automatically
        log("Clearing Link Disable bit (link retraining)...")
        en = pcie.enable_link(retrain=True)
        if en.get("rc", 1) != 0:
            return TestResult(
                TestStatus.FAIL,
                f"Failed to clear Link Disable: {en.get('error', en.get('stderr', ''))}"
            )
        log(f"  LnkCtl: {en.get('lnkctl_before')} → {en.get('lnkctl_after')}  ✓ link re-enabled")

        # Stash the pcie driver for the caller to use for rescan if needed
        self._last_pcie_driver = pcie
        return None

    def _wait_for_controller(self, driver, log,
                              initial_sleep: float = 1.0,
                              timeout: int = None) -> bool:
        """
        Poll id-ctrl until the controller responds or timeout expires.
        Returns True if the controller came back, False otherwise.
        """
        timeout = timeout or self.RESET_TIMEOUT_S
        if initial_sleep:
            log(f"  Sleeping {initial_sleep}s before polling...")
            time.sleep(initial_sleep)

        log(f"  Polling for controller response (timeout={timeout}s)...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = driver.run_cmd(["id-ctrl", driver.device], json_out=False)
            if r["rc"] == 0:
                elapsed = timeout - max(0.0, deadline - time.time())
                log(f"  ✓ Controller responding after ~{elapsed:.1f}s")
                return True
            time.sleep(self.RESET_POLL_S)

        log(f"  ✗ Controller did not respond within {timeout}s")
        return False

    def _wait_for_reenumeration(self, driver, log,
                                 timeout: int = None) -> bool:
        """
        After a link-level reset the device sysfs path may briefly disappear.
        Poll for the device path to reappear AND id-ctrl to succeed.
        Falls back to a rescan on the PCIe bus if stashed pcie driver is available.
        Returns True if device came back, False otherwise.
        """
        timeout  = timeout or self.RENUM_TIMEOUT_S
        dev_path = driver.device
        deadline = time.time() + timeout

        log(f"  Waiting for re-enumeration (timeout={timeout}s)...")
        while time.time() < deadline:
            if os.path.exists(dev_path):
                r = driver.run_cmd(["id-ctrl", dev_path], json_out=False)
                if r["rc"] == 0:
                    elapsed = timeout - max(0.0, deadline - time.time())
                    log(f"  ✓ Device re-enumerated after ~{elapsed:.1f}s")
                    return True
            time.sleep(self.RESET_POLL_S)

        # Attempt manual rescan before giving up
        pcie = getattr(self, "_last_pcie_driver", None)
        if pcie:
            log("  Attempting manual PCIe bus rescan...")
            pcie.rescan_bus()
            time.sleep(2.0)
            r = driver.run_cmd(["id-ctrl", dev_path], json_out=False)
            if r["rc"] == 0:
                log("  ✓ Device responded after manual rescan")
                return True

        log(f"  ✗ Device did not re-enumerate within {timeout}s")
        return False

    def _post_reset_recovery(self, driver, log, is_link_reset: bool = False) -> bool:
        """
        Unified post-reset stabilisation:
          1. Wait for controller / re-enumeration
          2. ns-rescan
          3. 1s settle
        Returns True if device is healthy.
        """
        if is_link_reset:
            ok = self._wait_for_reenumeration(driver, log)
        else:
            ok = self._wait_for_controller(driver, log, initial_sleep=2.0)

        if not ok:
            return False

        log("  Rescanning namespaces...")
        driver.ns_rescan()
        time.sleep(1.0)
        return True

    # ── FDP Statistics ────────────────────────────────────────────────────────

    def _read_fdp_stats(self, driver, log, endgrp: int = 1) -> dict | None:
        """
        Read and return the FDP Statistics log page as a dict, or None on error.
        Command: nvme fdp stats <dev> -e <endgrp>
        """
        r = driver.fdp_stats(endgrp=endgrp)
        if r["rc"] != 0:
            log(f"  FDP stats error (rc={r['rc']}): {r.get('stderr','').strip()}")
            return None
        data = r.get("data", {})
        if not data:
            log("  FDP stats returned empty data")
            return None
        return data

    def _extract_stat_field(self, stats: dict, *keys) -> int | None:
        """
        Extract a 128-bit counter from FDP stats JSON.
        nvme-cli may split 128-bit values as {"lo": X, "hi": Y}.
        Tries each key in order until one matches.
        """
        for key in keys:
            if key in stats:
                val = stats[key]
                if isinstance(val, dict):
                    lo = int(val.get("lo", val.get("lower", 0)))
                    hi = int(val.get("hi", val.get("upper", 0)))
                    return lo + (hi << 64)
                if isinstance(val, (int, float)):
                    return int(val)
                if isinstance(val, str):
                    try:
                        return int(val, 0)
                    except ValueError:
                        pass
        return None

    def _get_mbmw(self, stats: dict) -> int | None:
        """Media Bytes Media Written — total bytes the NAND media has written."""
        return self._extract_stat_field(
            stats,
            "mbmw", "MBMW", "media_bytes_media_written", "MediaBytesMediaWritten"
        )

    def _get_hbmw(self, stats: dict) -> int | None:
        """Host Bytes Media Written — host-issued write data in bytes."""
        return self._extract_stat_field(
            stats,
            "hbmw", "HBMW", "host_bytes_media_written", "HostBytesMediaWritten"
        )

    def _get_mbe(self, stats: dict) -> int | None:
        """Media Bytes Erased — total bytes of NAND erased."""
        return self._extract_stat_field(
            stats,
            "mbe", "MBE", "media_bytes_erased", "MediaBytesErased"
        )

    def _log_stats_snapshot(self, log, stats: dict, label: str = ""):
        """Log all three FDP Stats counters at once."""
        tag = f"[{label}] " if label else ""
        mbmw = self._get_mbmw(stats)
        hbmw = self._get_hbmw(stats)
        mbe  = self._get_mbe(stats)
        log(f"  {tag}mbmw={mbmw if mbmw is not None else 'N/A'}  "
            f"hbmw={hbmw if hbmw is not None else 'N/A'}  "
            f"mbe={mbe if mbe is not None else 'N/A'}")

    def _compare_stats(self, before: dict, after: dict, log) -> dict:
        """
        Compare FDP stats before/after a reset. Returns a summary dict with:
          - per-field deltas (should be 0 for persistence tests)
          - "all_match" bool
          - "fields_changed" list of field names with unexpected changes
        """
        results = {"all_match": True, "fields_changed": [], "details": {}}
        fields = {
            "mbmw": (self._get_mbmw, "Media Bytes Media Written"),
            "hbmw": (self._get_hbmw, "Host Bytes Media Written"),
            "mbe":  (self._get_mbe,  "Media Bytes Erased"),
        }
        for fid, (getter, fname) in fields.items():
            pre  = getter(before)
            post = getter(after)
            if pre is None and post is None:
                log(f"  {fname}: not reported by firmware (skip)")
                continue
            delta = (post or 0) - (pre or 0)
            match = (delta == 0)
            status_sym = "✓" if match else "✗"
            log(f"  {status_sym} {fname}: before={pre}  after={post}  delta={delta:+d}")
            results["details"][fid] = {"before": pre, "after": post, "delta": delta}
            if not match:
                results["all_match"] = False
                results["fields_changed"].append(fname)
        return results

    # ── IO workload ───────────────────────────────────────────────────────────

    def _run_fio_workload(self, driver, log,
                          duration_sec: int = 10,
                          block_size: str = "4k",
                          queue_depth: int = 8,
                          placement_handle: int = 0,
                          namespace: int = 1) -> bool:
        """
        Run a short FDP-aware FIO write workload.
        Returns True on success, False if fio is unavailable or fails.
        """
        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            log("  fio not installed — run: sudo apt install fio")
            return False
        # Ensure io_uring is enabled (disabled by default on some kernels after boot)
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        import re as _re
        dev  = driver.device
        base = dev.split("/")[-1]
        # Derive the block device (/dev/nvme0n1) and char device (/dev/ng0n1)
        # io_uring_cmd (required for FDP) needs the generic char device
        if "n" in base and base.index("n") > 4:
            ns_dev = dev   # already a namespace device e.g. /dev/nvme0n1
        else:
            ns_dev = f"{dev}n{namespace}"
        m = _re.search(r"nvme(\d+)n(\d+)", ns_dev)
        ng_dev = f"/dev/ng{m.group(1)}n{m.group(2)}" if m else ns_dev
        log(f"  FIO target: {ng_dev}  duration={duration_sec}s  bs={block_size}  "
            f"qd={queue_depth}  placement_handle={placement_handle}")

        # Verify the namespace has FDP placement handles before using fdp=1.
        # fio issues an internal RUH status query at startup; if the namespace
        # has no handles configured it fails with "ruh info failed" immediately.
        use_fdp = False
        try:
            ruhs_r = driver.fdp_ruhs(ns=namespace)
            ruhs   = driver.extract_ruhs(ruhs_r) if ruhs_r["rc"] == 0 else []
            if ruhs:
                use_fdp = True
                log(f"  FDP placement handles found ({len(ruhs)}) — using fdp=1")
            else:
                log("  ⚠ No FDP placement handles found — running fio without fdp=1")
        except Exception as _e:
            log(f"  ⚠ Could not query RUH status ({_e}) — running fio without fdp=1")

        fdp_lines = (
            f"fdp=1\nfdp_pli={placement_handle}\nfdp_pli_select=roundrobin\n"
            if use_fdp else ""
        )
        job = (
            "[global]\n"
            "ioengine=io_uring_cmd\ndirect=0\nrw=write\n"
            f"bs={block_size}\niodepth={queue_depth}\n"
            f"runtime={duration_sec}\ntime_based=1\n"
            "size=100%\n"
            f"{fdp_lines}"
            f"[fdp_workload]\nfilename={ng_dev}\n"
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".fio", delete=False) as f:
            f.write(job)
            job_path = f.name

        try:
            r = subprocess.run(
                ["fio", "--output-format=json", job_path],
                capture_output=True, text=True,
                timeout=duration_sec + 30
            )
            if r.returncode != 0:
                log(f"  fio failed (rc={r.returncode}): {r.stderr.strip()[:200]}")
                return False
            try:
                jobs = json.loads(r.stdout).get("jobs", [])
                if jobs:
                    wr = jobs[0].get("write", {})
                    bw  = round(wr.get("bw_bytes", 0) / 1e6, 1)
                    ios = round(wr.get("io_bytes", 0) / 1e6, 1)
                    log(f"  ✓ FIO complete — {bw} MB/s, {ios} MB written")
            except Exception:
                log("  ✓ FIO complete")
            return True
        except subprocess.TimeoutExpired:
            log("  fio timed out")
            return False
        finally:
            os.unlink(job_path)

    # ── RUHS parsing ──────────────────────────────────────────────────────────

    def _read_ph_ruh_mapping(self, driver, log, namespace: int = 1) -> list[dict]:
        """
        Read the Placement Handle → Reclaim Unit Handle mapping via RUHS.
        Returns a list of dicts, each with 'phndl' and 'ruhid' keys,
        normalised from whatever field names the firmware returns.
        """
        r = driver.fdp_ruhs(ns=namespace)
        if r["rc"] != 0:
            log(f"  Cannot read RUHS (rc={r['rc']}): {r.get('stderr','').strip()}")
            return []

        raw_ruhs = driver.extract_ruhs(r)
        mapping = []
        for entry in raw_ruhs:
            # Normalise field names across firmware variations
            phndl = None
            ruhid = None
            for pk in ("phndl", "PlacementHandle", "placement_handle", "pid"):
                if pk in entry:
                    phndl = int(entry[pk])
                    break
            for rk in ("ruhid", "RUHIdentifier", "reclaim_unit_handle_id", "ruh"):
                if rk in entry:
                    ruhid = int(entry[rk])
                    break
            # Fallback: use list index as phndl if not present
            if phndl is None:
                phndl = len(mapping)
            mapping.append({"phndl": phndl, "ruhid": ruhid, "raw": entry})
        return mapping

    def _log_mapping(self, log, mapping: list[dict], label: str = ""):
        tag = f"[{label}] " if label else ""
        if not mapping:
            log(f"  {tag}(no mapping entries)")
            return
        for m in mapping:
            log(f"  {tag}PH {m['phndl']} → RUH {m['ruhid']}")

    # ── Directive helpers ─────────────────────────────────────────────────────

    def _read_identify_directive(self, driver, log, namespace: int = 1) -> dict | None:
        """
        Directive Receive: Type 00h (Identify), Operation 01h (Return Parameters).

        Uses admin-passthru with --raw-binary so the actual byte values are
        preserved. nvme-cli's JSON/text output represents non-printable bytes
        as '.' making bit extraction impossible (e.g. 0x05 = Supported+Persistent
        is non-printable ASCII and would show as '.').

        The 4096-byte response has one capability byte per directive type:
          Byte 0 = Identify Directive (0x00):  bits [Supported, Enabled, Persistent]
          Byte 1 = Streams Directive  (0x01):  same
          Byte 2 = Data Placement Dir (0x02):  same
        """
        import re as _re, subprocess as _sp
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)
        # CDW10: 0x3FF (keep as hex — decimal conversion mangles the value)
        # CDW11: 0x1 (DTYPE = Identify Directive)
        cdw10 = "0x3FF"
        cdw11 = "0x1"

        try:
            result = _sp.run([
                "nvme", "admin-passthru", ctrl_dev,
                "--opcode=0x1A",       # Directive Receive opcode
                f"--namespace-id={namespace}",
                "--data-len=4096",
                "--read",
                f"--cdw10={cdw10}",
                f"--cdw11={cdw11}",
                "--raw-binary",
            ], capture_output=True, text=False, timeout=15)

            if result.returncode == 0 and result.stdout:
                raw = result.stdout
                log(f"  Directive Receive: {len(raw)} bytes received via raw-binary")
                if len(raw) >= 3:
                    log(f"  Byte[0]=0x{raw[0]:02x}  Byte[1]=0x{raw[1]:02x}  "
                        f"Byte[2]=0x{raw[2]:02x}")
                return {"raw_bytes": raw}

            log(f"  admin-passthru Directive Receive failed "
                f"(rc={result.returncode}), falling back to dir-receive JSON...")
        except Exception as e:
            log(f"  admin-passthru exception: {e}, falling back to dir-receive...")

        # Fallback: dir-receive JSON (may return unparseable dot strings)
        r = driver.dir_receive(
            dir_type=0x00, dir_oper=0x01,
            namespace=namespace, data_len=4096,
        )
        if r["rc"] != 0:
            log(f"  Directive Receive failed: {r.get('stderr','').strip()}")
            return None
        return r.get("data", {})