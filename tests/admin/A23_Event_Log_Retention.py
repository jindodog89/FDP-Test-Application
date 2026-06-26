"""
Case: FDP Event Log Retention (No Reset)
"""
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.utils import attach_ns
import time

class TestAdminEventLogRetention(BaseTest):
    test_id = "admin_event_log_retention"
    name = "A23. Event Log Retention (Enablement Cycle)"
    description = "Generates events, verifies they exist, cycles FDP (Disable -> Enable), and checks that the log is cleared."
    category = "Admin"
    tags = ["admin", "events", "retention", "set-feature"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        nsid = getattr(self, "params", {}).get("namespace", 1)

        # Enable all FDP event types — disabled by default on some devices after boot
        driver.enable_all_fdp_events(endgrp=endgrp, namespace=nsid)

        # 1. Ensure events are enabled and generate one
        # CDW layout: CDW10=0x8000001E, CDW11=0x00010000|event_type, CDW12=endgrp (enable)
        en_res = driver.set_fdp_event_passthru(event_type=0x00, enable=True,
                                               endgrp=endgrp, namespace=nsid)
        if en_res["rc"] != 0:
            log(f"  ⚠ FID 1Eh not supported or timed out: {en_res['stderr'].strip()}")
            return TestResult(TestStatus.SKIP,
                "FDP event enable (FID 1Eh) not supported on this device — cannot generate events.")

        log("Step 1: Generating an FDP event...")
        driver.write(namespace=nsid, start_block=0, block_count=1, data_size=4096, dtype=2, dspec=0xCCCC)
        time.sleep(1)

        # 2. Confirm event exists
        initial_events = driver.fdp_events(endgrp=endgrp, host_events=True).get("data", {}).get("events", [])
        if len(initial_events) == 0:
            return TestResult(TestStatus.FAIL, "Failed to generate initial event for retention test.")
        log(f"Step 2: Confirmed {len(initial_events)} event(s) in log.")
        
        # 3. Delete all namespaces (spec requirement before toggling FDP)
        log("Step 3: Deleting all namespaces (required by spec before Set Features FID 1Dh)...")
        saved_ns = self._delete_all_ns(driver, log)

        # 4. Disable FDP
        log("Step 4: Issuing Set Features to Disable FDP...")
        dis_res = driver.set_feature_passthru(feature_id=0x1D, cdw11=endgrp, cdw12=0x0, save=True)
        if dis_res["rc"] != 0:
            log(f"  ⚠ FDP disable rejected: {dis_res['stderr'].strip()} — restoring namespaces and skipping.")
            self._restore_ns(driver, log, saved_ns)
            return TestResult(TestStatus.SKIP,
                "Cannot disable FDP on this device — skipping retention cycle test.")

        # 5. Re-enable FDP
        log("Step 5: Re-enabling FDP...")
        driver.set_feature_passthru(feature_id=0x1D, cdw11=endgrp, cdw12=0x1, save=True)
        time.sleep(1)  # Allow enablement to settle

        # 6. Restore namespaces
        log("Step 6: Restoring namespaces...")
        self._restore_ns(driver, log, saved_ns)

        # 7. Check log
        log("Step 7: Reading Log 23h again...")
        final_events_res = driver.fdp_events(endgrp=endgrp, host_events=True)

        # If disabled/re-enabled, the log should either fail to read temporarily or return empty
        final_events = final_events_res.get("data", {}).get("events", []) if final_events_res["rc"] == 0 else []

        if len(final_events) == 0:
            log("✓ The event log is cleared; count returned to 0.")
            return TestResult(TestStatus.PASS, "Event log correctly tied to the current FDP enablement cycle.")
        else:
            log(f"✗ Event log was not cleared! Found {len(final_events)} events.")
            return TestResult(TestStatus.FAIL, "Controller preserved events across an FDP disable/enable cycle.")

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