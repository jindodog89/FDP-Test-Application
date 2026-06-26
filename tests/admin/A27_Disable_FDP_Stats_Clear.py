"""
Case: Disable FDP (Stats Clearing)
"""
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.utils import attach_ns

class TestAdminDisableFDPStatsClear(BaseTest):
    test_id = "admin_disable_fdp_stats_clear"
    name = "A27. Disable FDP Stats Clearing"
    description = "Disables FDP via Set Features and verifies that all FDP-related events and statistics are cleared."
    category = "Admin"
    tags = ["admin", "set-feature", "fdp-disable", "stats"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log("Step 1: Deleting all namespaces (required by spec before Set Features FID 1Dh)...")
        saved_ns = self._delete_all_ns(driver, log)

        log("Step 2: Issuing Set Features (FID 1Dh) to disable FDP...")
        disable_result = driver.set_feature_passthru(
            feature_id=0x1D,
            cdw11=endgrp,
            cdw12=0x0,
            save=True,
        )

        if disable_result["rc"] != 0:
            stderr = disable_result["stderr"].strip()
            log(f"⚠ Set Features to disable FDP was rejected: {stderr}")
            log("  Restoring namespaces and skipping test.")
            self._restore_ns(driver, log, saved_ns)
            return TestResult(TestStatus.SKIP,
                f"Cannot disable FDP on this device (Set Features rejected: {stderr}). "
                "Skipping stats-clear verification.")

        log("✓ FDP successfully disabled.")

        log("Step 3: Verifying FDP Events log is cleared...")
        events_res = driver.fdp_events(endgrp=endgrp)
        
        if events_res["rc"] == 0:
            events_data = events_res.get("data", {})
            events = events_data.get("events", events_data.get("FdpEvents", []))
            if len(events) > 0:
                log(f"✗ Events log not cleared! Found {len(events)} events.")
                return TestResult(TestStatus.FAIL, "FDP Events log was not cleared after disabling FDP.")
            else:
                log("✓ FDP Events log is empty.")
        else:
             log("✓ FDP Events log correctly unreadable/empty while disabled.")

        log("Step 4: Verifying FDP Statistics are cleared...")
        stats_res = driver.fdp_stats(endgrp=endgrp)
        
        if stats_res["rc"] == 0:
             stats_data = stats_res.get("data", {})
             hbmw = int(stats_data.get("hbmw", stats_data.get("HostBytesMediaWritten", 1)))
             mbmw = int(stats_data.get("mbmw", stats_data.get("MediaBytesMediaWritten", 1)))
             if hbmw > 0 or mbmw > 0:
                 log(f"✗ Stats not cleared! HBMW: {hbmw}, MBMW: {mbmw}")
                 return TestResult(TestStatus.FAIL, "FDP Statistics were not cleared after disabling FDP.")
             else:
                 log("✓ FDP Statistics are effectively cleared.")
        else:
             log("✓ FDP Statistics correctly unreadable/empty while disabled.")

        log("Step 5: Restoring namespaces...")
        self._restore_ns(driver, log, saved_ns)

        return TestResult(TestStatus.PASS, "FDP successfully disabled and all statistics/events were cleared.")

    # ── Namespace lifecycle helpers ───────────────────────────────────────────

    def _delete_all_ns(self, driver, log) -> list:
        """
        Save geometry of all namespaces then delete them all in one shot using
        the broadcast NSID 0xFFFFFFFF. This avoids partial deletion if an error
        interrupts a per-namespace loop.
        Returns a list of dicts with enough info to recreate each namespace:
          {"nsid": N, "nsze": N, "ncap": N, "flbas": N, "nphndls": N, "endg_id": N}
        Required by NVMe spec before enabling or disabling FDP via Set Features.
        """
        import re as _re
        ctrl_dev = _re.sub(r'n\d+$', '', driver.device)

        list_res = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        raw_list = []
        if list_res["rc"] == 0:
            data = list_res.get("data", {})
            if isinstance(data, dict):
                raw_list = data.get("nsid_list", data.get("NamespaceList", []))
            elif isinstance(data, list):
                raw_list = data

        # Save geometry for each namespace so we can restore afterwards
        saved = []
        for raw in raw_list:
            nsid = int(raw["nsid"]) if isinstance(raw, dict) else int(raw)
            id_res = driver.run_cmd(["id-ns", ctrl_dev, f"--namespace-id={nsid}"],
                                    json_out=True)
            ns_info = {"nsid": nsid, "nsze": 0, "ncap": 0, "flbas": 0,
                       "nphndls": 0, "endg_id": 1}
            if id_res["rc"] == 0:
                d = id_res.get("data", {})
                if isinstance(d, dict):
                    ns_info["nsze"]  = int(d.get("nsze", 0))
                    ns_info["ncap"]  = int(d.get("ncap", ns_info["nsze"]))
                    ns_info["flbas"] = int(d.get("flbas", 0)) & 0xF
            saved.append(ns_info)

        if not saved:
            log("  No namespaces found to delete.")
            return saved

        # Delete all namespaces in one command using broadcast NSID 0xFFFFFFFF
        del_res = driver.run_cmd(["delete-ns", ctrl_dev,
                                  "--namespace-id=0xFFFFFFFF"], json_out=False)
        if del_res["rc"] == 0:
            log(f"  ✓ All {len(saved)} namespace(s) deleted (broadcast NSID)")
        else:
            log(f"  ⚠ Broadcast delete failed: {del_res['stderr'].strip()}")

        return saved

    def _restore_ns(self, driver, log, saved: list):
        """
        Re-create and re-attach each namespace from the list returned by
        _delete_all_ns(). Both commands require the controller device
        (/dev/nvme0), not a namespace device path.
        Best-effort — logs warnings on any failure.
        """
        import re as _re
        ctrl_dev = _re.sub(r'n\d+$', '', driver.device)
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
                log(f"  ⚠ Restore create-ns failed: {cr['stderr'].strip()}")
                continue
            # Parse new NSID
            out = cr["stdout"] + cr["stderr"]
            m = _re.search(r'nsid[:\s]+(\d+)', out, _re.IGNORECASE)
            new_nsid = int(m.group(1)) if m else ns["nsid"]
            at = attach_ns(driver, ctrl_dev, new_nsid, log)
            if at["rc"] == 0:
                log(f"  ✓ Restored NSID {new_nsid}")
            else:
                log(f"  ⚠ Attach NSID {new_nsid} failed: {at['stderr'].strip()}")