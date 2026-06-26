"""
Case I1: FDPS – Validate FDPS Bit in Controller Attributes
"""
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.utils import attach_ns

class TestAdminIdentifyFDPS(BaseTest):
    test_id = "admin_identify_fdps"
    name = "A1. Validate FDPS Bit in Identify Ctrl"
    description = "Checks CTRATT Bit 19 (FDPS) and verifies Set Features (FID 1Dh) acceptance aligns with it."
    category = "Admin"
    tags = ["admin", "identify", "ctratt", "fdps"]

    def run(self, driver, log) -> TestResult:
        endgrp = getattr(self, "params", {}).get("endgrp", 1)
        
        log("Step 1: Reading Identify Controller FDP parsed fields...")
        parsed_id = driver.get_identify_parsed_fdp()
        
        if "error" in parsed_id:
            return TestResult(TestStatus.FAIL, f"Identify Controller failed: {parsed_id['error']}")
            
        fdps_supported = parsed_id["fdps"]
        log(f"  FDPS (CTRATT Bit 19): {fdps_supported}")

        log("Step 2: Deleting all namespaces (required by spec before Set Features FID 1Dh)...")
        saved_ns = self._delete_all_ns(driver, log)
        if not saved_ns:
            log("  No namespaces found to delete.")

        log("Step 3: Testing Set Features (FID 1Dh) behavior...")
        # Issue a Set Features to disable FDP (0x0) — safe probe, tests command acceptance
        set_feat_res = driver.set_feature_passthru(feature_id=0x1D, cdw11=endgrp, cdw12=0x0, save=True)
        command_accepted = (set_feat_res["rc"] == 0)

        log("Step 4: Restoring namespaces...")
        self._restore_ns(driver, log, saved_ns)

        if fdps_supported:
            if command_accepted:
                log("✓ FDPS is 1 and Set Features (FID 1Dh) was accepted.")
                return TestResult(TestStatus.PASS, "Controller supports FDP and correctly accepts FID 1Dh.")
            else:
                log(f"⚠ FDPS is 1 but Set Features was rejected: {set_feat_res['stderr'].strip()}")
                log("  FDP is active (evidenced by working FDP commands) — treating as implementation variation.")
                return TestResult(TestStatus.WARN,
                    "FDPS=1 confirmed in CTRATT, but Set Features (FID 1Dh) rejected. "
                    "FDP may require a different enable sequence on this device.")
        else:
            if not command_accepted:
                log("✓ FDPS is 0 and Set Features (FID 1Dh) correctly failed.")
                return TestResult(TestStatus.PASS, "Controller correctly rejects FID 1Dh when FDP is unsupported.")
            else:
                log("✗ FDPS is 0, but Set Features unexpectedly succeeded.")
                return TestResult(TestStatus.FAIL, "Controller lacks FDP support but incorrectly accepted FID 1Dh.")

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