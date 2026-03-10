"""
NVMe CLI Driver — nvme-cli backed implementation of BaseNVMeDriver.
Includes verbose debug logging of every command issued for easier debugging.
"""

import subprocess
import json
import logging
from backend.drivers.base_driver import BaseNVMeDriver

# Module-level debug logger — writes to logs/debug/ via the log manager
debug_log = logging.getLogger("nvme_cli.debug")


class NVMeCliDriver(BaseNVMeDriver):

    @property
    def driver_name(self) -> str:
        return "nvme-cli"

    # ── Low-level execution ───────────────────────────────────────────────────

    def run_command(self, args: list) -> dict:
        """Required by BaseNVMeDriver. Returns raw stdout/stderr/returncode."""
        cmd = ["nvme"] + args
        cmd_str = " ".join(cmd)
        debug_log.debug("CMD: %s", cmd_str)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            debug_log.debug("RC : %d", result.returncode)
            if result.stdout.strip():
                debug_log.debug("OUT: %s", result.stdout.strip()[:2000])
            if result.stderr.strip():
                debug_log.debug("ERR: %s", result.stderr.strip()[:1000])
            return {
                "stdout":     result.stdout,
                "stderr":     result.stderr,
                "returncode": result.returncode,
                "command":    cmd_str,
            }
        except FileNotFoundError:
            msg = "nvme-cli not found. Install with: sudo apt install nvme-cli"
            debug_log.error("CMD FAILED (not found): %s", cmd_str)
            return {"stdout": "", "stderr": msg, "returncode": 127, "command": cmd_str}
        except subprocess.TimeoutExpired:
            debug_log.error("CMD TIMEOUT: %s", cmd_str)
            return {"stdout": "", "stderr": "Command timed out after 30s",
                    "returncode": -1, "command": cmd_str}

    def run_cmd(self, args: list, json_out: bool = True) -> dict:
        """
        Convenience wrapper used by all tests.
        Keys: stdout, stderr, rc, cmd, data (if json_out and rc==0).
        """
        full_args = args + (["-o", "json"] if json_out else [])
        raw = self.run_command(full_args)
        result = {
            "stdout": raw["stdout"],
            "stderr": raw["stderr"],
            "rc":     raw["returncode"],
            "cmd":    raw["command"],
        }
        if json_out and raw["returncode"] == 0:
            try:
                result["data"] = json.loads(raw["stdout"])
            except json.JSONDecodeError:
                result["data"] = raw["stdout"]
        return result

    # ── Identify ──────────────────────────────────────────────────────────────

    def get_controller_identity(self) -> dict:
        return self.run_cmd(["id-ctrl", self.device])

    def id_ctrl(self) -> dict:
        return self.get_controller_identity()

    def get_namespace_identity(self, namespace: int = 1) -> dict:
        return self.run_cmd(["id-ns", self.device, "-n", str(namespace)])

    def id_ns(self, namespace: int = 1) -> dict:
        return self.get_namespace_identity(namespace)

    def list_namespaces(self) -> dict:
        return self.run_cmd(["list-ns", self.device, "--all"])

    # ── FDP status / enable state ─────────────────────────────────────────────

    def get_fdp_status(self) -> dict:
        """
        FDP enable/disable state for an endurance group.
        Command: nvme fdp status <dev>
        Note: this is NOT the same as Reclaim Unit Handle Status (RUHS).
        """
        return self.run_cmd(["fdp", "status", self.device])

    def fdp_status(self) -> dict:
        return self.get_fdp_status()

    # ── FDP configuration log (endurance group scoped) ────────────────────────

    def get_fdp_configs(self, endgrp: int = 1) -> dict:
        """
        FDP Configurations log page (Log ID 0x20).
        Command: nvme fdp configs <dev> --endgrp-id=<N>
        """
        return self.run_cmd(["fdp", "configs", self.device, f"--endgrp-id={endgrp}"])

    def fdp_configs(self, endgrp: int = 1) -> dict:
        return self.get_fdp_configs(endgrp)

    # ── Reclaim Unit Handle Status (RUHS) — THE KEY FIX ──────────────────────

    def get_reclaim_unit_handle_status(self, namespace: int = 1) -> dict:
        """
        Reclaim Unit Handle Status — per namespace.
        Command: nvme fdp status <dev> -n <nsid>
        """
        return self.run_cmd(["fdp", "status", self.device, "-n", str(namespace)])

    def fdp_ruhs(self, ns: int = 1) -> dict:
        """Alias: returns Reclaim Unit Handle Status for the given namespace."""
        return self.get_reclaim_unit_handle_status(ns)

    # ── FDP Reclaim Unit Handle Usage (RUHU) log ──────────────────────────────

    def get_fdp_placement_ids(self, endgrp: int = 1) -> dict:
        """
        Reclaim Unit Handle Usage log (Log ID 0x21) — endurance group scoped.
        Command: nvme fdp usage <dev> -e <endgrp>
        """
        return self.run_cmd(["fdp", "usage", self.device, "-e", str(endgrp)])

    def fdp_usage(self, endgrp: int = 1) -> dict:
        return self.get_fdp_placement_ids(endgrp)

    # ── FDP Events log ────────────────────────────────────────────────────────

    def get_fdp_events(self, endgrp: int = 1) -> dict:
        """
        FDP Events log page (Log ID 0x23) — endurance group scoped.
        Command: nvme fdp events <dev> -e <endgrp>
        """
        return self.run_cmd(["fdp", "events", self.device, "-e", str(endgrp)])

    def fdp_events(self, endgrp: int = 1) -> dict:
        return self.get_fdp_events(endgrp)

    # ── IO Management ─────────────────────────────────────────────────────────

    def io_mgmt_send(self, namespace: int = 1, cdw12: int = 0,
                     data_path: str = None, data_len: int = 4096) -> dict:
        args = [
            "io-mgmt-send", self.device,
            f"--namespace-id={namespace}",
            f"--cdw12={cdw12}",
            f"--data-len={data_len}",
        ]
        if data_path:
            args.append(f"--data={data_path}")
        return self.run_cmd(args, json_out=False)

    def io_mgmt_recv(self, namespace: int = 1, cdw12: int = 0,
                     data_len: int = 4096) -> dict:
        args = [
            "io-mgmt-recv", self.device,
            f"--namespace-id={namespace}",
            f"--cdw12={cdw12}",
            f"--data-len={data_len}",
        ]
        return self.run_cmd(args, json_out=False)

    # ── NVMe Write ────────────────────────────────────────────────────────────

    def write(self, namespace: int = 1, start_block: int = 0,
              block_count: int = 0, data_size: int = 4096,
              data_source: str = "/dev/zero", dtype: int = 0,
              dspec: int = 0) -> dict:
        """
        dtype=0: legacy (no directive)
        dtype=2: FDP directive; dspec = placement handle index
        """
        return self.run_cmd([
            "write", self.device,
            f"--namespace-id={namespace}",
            f"--start-block={start_block}",
            f"--block-count={block_count}",
            f"--data-size={data_size}",
            f"--data={data_source}",
            f"--dtype={dtype}",
            f"--dspec={dspec}",
        ], json_out=False)

    # ── SMART log ─────────────────────────────────────────────────────────────

    def smart_log(self) -> dict:
        return self.run_cmd(["smart-log", self.device])

    # ── Passthrough ───────────────────────────────────────────────────────────

    def admin_passthru(self, opcode: int, cdw10: int = 0, cdw12: int = 0,
                       data_len: int = 4096, read: bool = True) -> dict:
        args = [
            "admin-passthru", self.device,
            f"--opcode={opcode}",
            f"--cdw10={cdw10}",
            f"--cdw12={cdw12}",
            f"--data-len={data_len}",
        ]
        if read:
            args.append("--read")
        return self.run_cmd(args)

    def io_passthru(self, opcode: int, namespace: int = 1, cdw12: int = 0,
                    data_len: int = 4096, read: bool = True) -> dict:
        args = [
            "io-passthru", self.device,
            f"--namespace-id={namespace}",
            f"--opcode={opcode}",
            f"--cdw12={cdw12}",
            f"--data-len={data_len}",
        ]
        if read:
            args.append("--read")
        return self.run_cmd(args)
    
    def extract_ruhs(self, result: dict) -> list:
        """
        Parse a RUHS command result dict into a flat list of handle entries.
        Override in subclasses if the backend returns a different structure.
        """
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("ruhid", "ruhs", "ReclaimUnitHandles", "ruhsd",
                        "reclaim_unit_handle_descriptors"):
                if key in data:
                    val = data[key]
                    return val if isinstance(val, list) else [val]
        return []
    
    # ── FDP Statistics log ────────────────────────────────────────────────────

    def get_fdp_stats(self, endgrp: int = 1) -> dict:
        """
        FDP Statistics log page (Log ID 0x22) — endurance group scoped.
        Command: nvme fdp stats <dev> -e <endgrp>
        Fields include: hbmw (host bytes media written), mbmw (media bytes
        media written), mbe (media bytes erased).
        """
        return self.run_cmd(["fdp", "stats", self.device, "-e", str(endgrp)])

    def fdp_stats(self, endgrp: int = 1) -> dict:
        return self.get_fdp_stats(endgrp)

    # ── Controller / subsystem reset ─────────────────────────────────────────

    def controller_reset(self) -> dict:
        """nvme reset <dev> — triggers CC.EN=0 then CC.EN=1 via kernel driver."""
        return self.run_cmd(["reset", self.device], json_out=False)

    def subsystem_reset(self) -> dict:
        """nvme subsystem-reset <dev> — NVM Subsystem Reset (NSSR)."""
        return self.run_cmd(["subsystem-reset", self.device], json_out=False)

    def ns_rescan(self) -> dict:
        """nvme ns-rescan <dev> — rescan namespaces after reset."""
        return self.run_cmd(["ns-rescan", self.device], json_out=False)

    # ── Directive commands ────────────────────────────────────────────────────

    def dir_receive(self, dir_type: int, dir_oper: int,
                    namespace: int = 1, data_len: int = 4096,
                    dir_spec: int = 0) -> dict:
        """
        Directive Receive admin command.
          dir_type 0x00, dir_oper 0x01 = Identify (returns supported directives)
          dir_type 0x02, dir_oper 0x01 = Data Placement Return Parameters
        Command: nvme dir-receive <dev> -D <type> -O <oper> -n <ns>
        """
        return self.run_cmd([
            "dir-receive", self.device,
            f"--namespace-id={namespace}",
            f"--dir-type={dir_type}",
            f"--dir-oper={dir_oper}",
            f"--dir-spec={dir_spec}",
            f"--data-len={data_len}",
        ])

    def dir_send(self, dir_type: int, dir_oper: int,
                 namespace: int = 1, dir_spec: int = 0,
                 data_len: int = 0) -> dict:
        """
        Directive Send admin command.
          dir_type 0x00, dir_oper 0x01 = Enable Directive
          dir_type 0x00, dir_oper 0x02 = Disable Directive
        Command: nvme dir-send <dev> -D <type> -O <oper> -n <ns>
        """
        args = [
            "dir-send", self.device,
            f"--namespace-id={namespace}",
            f"--dir-type={dir_type}",
            f"--dir-oper={dir_oper}",
            f"--dir-spec={dir_spec}",
        ]
        if data_len:
            args.append(f"--data-len={data_len}")
        return self.run_cmd(args, json_out=False)
    
# ── Admin Commands (Features & Logs) ──────────────────────────────────────

    def set_feature(self, feature_id: int, value: int = 0, cdw12: int = 0,
                    cdw13: int = 0, cdw14: int = 0, cdw15: int = 0,
                    data_len: int = 0, data_path: str = None, save: bool = False) -> dict:
        """
        nvme set-feature mapping. 'value' targets CDW11.
        """
        args = [
            "set-feature", self.device,
            f"--feature-id={feature_id}",
            f"--value={value}",
            f"--cdw12={cdw12}",
            f"--cdw13={cdw13}",
            f"--cdw14={cdw14}",
            f"--cdw15={cdw15}"
        ]
        if save:
            args.append("--save")
        if data_len > 0:
            args.append(f"--data-len={data_len}")
        if data_path:
            args.append(f"--data={data_path}")
        return self.run_cmd(args, json_out=False)

    def get_feature(self, feature_id: int, cdw11: int = 0, sel: int = 0,
                    data_len: int = 0, namespace_id: int = 0xFFFFFFFF) -> dict:
        """
        nvme get-feature mapping.
        """
        args = [
            "get-feature", self.device,
            f"--feature-id={feature_id}",
            f"--cdw11={cdw11}",
            f"--sel={sel}",
            f"--namespace-id={namespace_id}"
        ]
        if data_len > 0:
            args.append(f"--data-len={data_len}")
        return self.run_cmd(args, json_out=True)

    def get_log(self, log_id: int, log_len: int = 4096, offset: int = 0,
                lsp: int = 0, lsi: int = 0, rae: bool = False,
                namespace_id: int = 0xFFFFFFFF, bin_out: bool = False) -> dict:
        """
        nvme get-log mapping. Supports custom offsets for boundary testing.
        """
        args = [
            "get-log", self.device,
            f"--log-id={log_id}",
            f"--log-len={log_len}",
            f"--lpo={offset}",
            f"--lsp={lsp}",
            f"--lsi={lsi}",
            f"--namespace-id={namespace_id}"
        ]
        if rae:
            args.append("--rae")
        
        # If binary dump is needed (e.g., partial read boundaries), return raw string output
        return self.run_cmd(args, json_out=not bin_out)

    # ── Namespace Management ──────────────────────────────────────────────────

    def create_ns(self, nsze: int, ncap: int, flbas: int, dps: int = 0,
                  nmic: int = 0, endg_id: int = 0, nphndls: int = 0,
                  anagrp_id: int = 0) -> dict:
        """
        nvme create-ns mapping. Supports FDP parameters like endg-id and nphndls.
        """
        args = [
            "create-ns", self.device,
            f"--nsze={nsze}", f"--ncap={ncap}", f"--flbas={flbas}",
            f"--dps={dps}", f"--nmic={nmic}"
        ]
        if endg_id > 0:
            args.append(f"--endg-id={endg_id}")
        if nphndls > 0:
            args.append(f"--nphndls={nphndls}")
        if anagrp_id > 0:
            args.append(f"--anagrp-id={anagrp_id}")
            
        return self.run_cmd(args, json_out=False)

    def delete_ns(self, namespace_id: int) -> dict:
        return self.run_cmd([
            "delete-ns", self.device, f"--namespace-id={namespace_id}"
        ], json_out=False)

    def attach_ns(self, namespace_id: int, controllers: str = "0x1") -> dict:
        return self.run_cmd([
            "attach-ns", self.device,
            f"--namespace-id={namespace_id}",
            f"--controllers={controllers}"
        ], json_out=False)

    def detach_ns(self, namespace_id: int, controllers: str = "0x1") -> dict:
        return self.run_cmd([
            "detach-ns", self.device,
            f"--namespace-id={namespace_id}",
            f"--controllers={controllers}"
        ], json_out=False)
    
# ── Identify (Generic & FDP Parsing) ──────────────────────────────────────

    def identify(self, cns: int, csi: int = 0, nsid: int = 0, data_len: int = 4096) -> dict:
        """
        Generic nvme identify wrapper.
        Supports specific CNS (Controller/Namespace Structure) and CSI (Command Set Identifier).
        """
        args = [
            "identify", self.device,
            f"--cns={cns}",
            f"--csi={csi}",
            f"--namespace-id={nsid}",
            f"--data-len={data_len}"
        ]
        return self.run_cmd(args, json_out=True)

    def get_identify_parsed_fdp(self) -> dict:
        """
        Issues Identify Controller (CNS 01h) and parses FDP-specific attributes.
        Returns a dictionary with extracted bits for CTRATT and VWC.
        """
        res = self.id_ctrl()
        if res["rc"] != 0:
            return {"error": res.get("stderr", "Identify Controller failed")}
            
        data = res.get("data", {})
        
        # Helper to safely convert nvme-cli's hex strings or ints
        def _to_int(val):
            if isinstance(val, int): return val
            if isinstance(val, str): return int(val, 16) if val.startswith("0x") else int(val)
            return 0

        ctratt = _to_int(data.get("ctratt", 0))
        vwc = _to_int(data.get("vwc", 0))
        
        return {
            "ctratt_raw": ctratt,
            "fdps": bool(ctratt & (1 << 19)),           # CTRATT Bit 19: FDP Supported
            "fcm": bool(ctratt & (1 << 18)),            # CTRATT Bit 18: Fixed Capacity Management
            "vwc_raw": vwc,
            "vwc_present": bool(vwc & 0x1),             # VWC Bit 0: Volatile Write Cache Present
            "vwc_flush_behavior": (vwc >> 1) & 0x3      # VWC Bits 2:1: Flush Behavior
        }