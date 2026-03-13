"""
NVMe CLI Driver — wraps nvme-cli for all NVMe and FDP operations.
"""

import subprocess
import json
import logging

from .base_driver import BaseNVMeDriver

debug_log = logging.getLogger("nvme_cli.debug")


def _block_device(device: str) -> str:
    """
    Strip the namespace suffix from a device path so that commands which
    only accept a block device (e.g. 'nvme reset', 'nvme subsystem-reset')
    receive '/dev/nvme0' rather than '/dev/nvme0n1'.

    Examples:
        /dev/nvme0n1  -> /dev/nvme0
        /dev/nvme1n2  -> /dev/nvme1
        /dev/nvme0    -> /dev/nvme0   (already a block device, unchanged)
    """
    import re
    return re.sub(r'n\d+$', '', device)


class NVMeCliDriver(BaseNVMeDriver):
    """NVMe driver backed by nvme-cli."""

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

    def identify(self, cns: int = 0x01, csi: int = 0x00, nsid: int = 0) -> dict:
        """
        Generic Identify command via admin-passthru.
          cns  : Controller or Namespace Structure (CDW10 bits [7:0])
          csi  : Command Set Identifier (CDW11 bits [7:0])
          nsid : Namespace ID (0 = controller-level)
        Command: nvme admin-passthru <dev> --opcode=0x06 --cdw10=<cns> --cdw11=<csi<<24> --read
        """
        cdw10 = cns & 0xFF
        cdw11 = (csi & 0xFF) << 24
        args = [
            "admin-passthru", self.device,
            "--opcode=0x06",
            f"--cdw10={cdw10}",
            f"--cdw11={cdw11}",
            "--data-len=4096",
            "--read",
        ]
        if nsid:
            args.append(f"--namespace-id={nsid}")
        return self.run_cmd(args)

    def get_identify_parsed_fdp(self) -> dict:
        """
        Convenience wrapper: returns a normalised dict of FDP-relevant fields
        from Identify Controller (CNS=0x01), handling nvme-cli JSON variations.

        Returned keys (always present, with safe defaults):
          fdps              : bool  — CTRATT bit 19 (FDP Supported)
          fcm               : bool  — CTRATT bit 18 (Fixed Capacity Management)
          vwc_present       : bool  — VWC byte bit 0 (Volatile Write Cache present)
          vwc_flush_behavior: int   — VWC byte bits [2:1] (Flush Behaviour)
          error             : str   — set only when the Identify command itself fails
        """
        res = self.get_controller_identity()
        if res["rc"] != 0:
            return {"error": res["stderr"].strip() or "Identify Controller failed"}

        data = res.get("data", {})

        # ── CTRATT ────────────────────────────────────────────────────────────
        # nvme-cli may expose ctratt as a raw int, a hex string, or a nested dict
        # of named bits.  Handle all three.
        ctratt_raw = data.get("ctratt", 0)
        if isinstance(ctratt_raw, dict):
            # e.g. {"fdps": 1, "fcm": 1, "mds": 0, ...}
            fdps = bool(ctratt_raw.get("fdps", ctratt_raw.get("FDPS", 0)))
            fcm  = bool(ctratt_raw.get("fcm",  ctratt_raw.get("FCM",  0)))
        else:
            ctratt_int = int(ctratt_raw, 16) if isinstance(ctratt_raw, str) and ctratt_raw.startswith("0x") \
                         else int(ctratt_raw)
            fdps = bool(ctratt_int & (1 << 19))
            fcm  = bool(ctratt_int & (1 << 18))

        # ── VWC ───────────────────────────────────────────────────────────────
        vwc_raw = data.get("vwc", 0)
        if isinstance(vwc_raw, dict):
            # e.g. {"vwcp": 1, "vwcflb": 2}
            vwc_int = vwc_raw.get("vwcp", vwc_raw.get("vwc", 0)) | \
                      (vwc_raw.get("vwcflb", vwc_raw.get("fb", 0)) << 1)
        else:
            vwc_int = int(vwc_raw, 16) if isinstance(vwc_raw, str) and vwc_raw.startswith("0x") \
                      else int(vwc_raw)

        vwc_present        = bool(vwc_int & 0x1)
        vwc_flush_behavior = (vwc_int >> 1) & 0x3

        return {
            "fdps":               fdps,
            "fcm":                fcm,
            "vwc_present":        vwc_present,
            "vwc_flush_behavior": vwc_flush_behavior,
        }

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

    # ── Reclaim Unit Handle Status (RUHS) ─────────────────────────────────────

    def get_reclaim_unit_handle_status(self, namespace: int = 1) -> dict:
        """
        Reclaim Unit Handle Status — per namespace.
        Correct nvme-cli command: nvme fdp status <dev> -n <nsid>
        NOTE: 'nvme fdp ruhs' does NOT exist in nvme-cli. The subcommand
        that returns RUHS data is 'nvme fdp status' with a namespace ID.
        'nvme fdp status' without -n returns FDP feature enable state (different).
        """
        return self.run_cmd(["fdp", "status", self.device, "-n", str(namespace)])

    def fdp_ruhs(self, ns: int = 1) -> dict:
        """Alias: returns Reclaim Unit Handle Status for the given namespace."""
        return self.get_reclaim_unit_handle_status(ns)

    def extract_ruhs(self, result: dict) -> list:
        """
        Parse a RUHS command result dict into a flat list of handle entries.
        """

        _ARRAY_KEYS = (
            "ruhStatusDescriptors",   # nvme-cli ≥ 2.x
            "ruhss",                  # nvme-cli compact key seen on real devices
            "ruhid",
            "ruhs",
            "ReclaimUnitHandles",
            "reclaim_unit_handle_descriptors",
            "ruhsd",
        )

        def _find_in(d: dict) -> list | None:
            """Search one dict level; return the list if found, else None."""
            for key in _ARRAY_KEYS:
                if key in d:
                    val = d[key]
                    # Must be a list — skip scalars (e.g. per-entry "ruhid": 0)
                    if isinstance(val, list):
                        return val
            return None

        data = result.get("data", {})

        if isinstance(data, list):          # already unwrapped
            return data

        if isinstance(data, dict):
            # 1. Search top-level keys first
            found = _find_in(data)
            if found is not None:
                return found

            # 2. Recurse one level into nested values — handles both:
            #    • nested dicts  e.g. {"fdp_ruh_status": {"ruhss": [...]}}
            #    • direct lists  e.g. {"nruhsd": 4, "ruhss": [...]}  (caught above,
            #      but any top-level list value not matching a key is caught here)
            for val in data.values():
                if isinstance(val, dict):
                    found = _find_in(val)
                    if found is not None:
                        return found
                elif isinstance(val, list) and val and isinstance(val[0], dict):
                    # A top-level list of dicts that wasn't caught by _find_in
                    # (i.e. the key wasn't in _ARRAY_KEYS) — return it directly
                    return val

        return []

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

    # ── FDP Statistics log ────────────────────────────────────────────────────

    def get_fdp_stats(self, endgrp: int = 1) -> dict:
        """FDP Statistics log page (Log ID 0x22)."""
        return self.run_cmd(["fdp", "stats", self.device, "-e", str(endgrp)])

    def fdp_stats(self, endgrp: int = 1) -> dict:
        return self.get_fdp_stats(endgrp)

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
            f"--dir-type={dtype}",
            f"--dir-spec={dspec}",
        ], json_out=False)

    # ── SMART log ─────────────────────────────────────────────────────────────

    def smart_log(self) -> dict:
        return self.run_cmd(["smart-log", self.device])

    # ── Get / Set Feature ─────────────────────────────────────────────────────

    def get_feature(self, fid: int, cdw11: int = 0) -> dict:
        return self.run_cmd([
            "get-feature", self.device,
            f"--feature-id={fid}",
            f"--cdw11={cdw11}",
            "--namespace-id=0"
        ])

    def set_feature(self, feature_id: int, value: int = 0, cdw12: int = 0) -> dict:
        """
        Set Features command.
          feature_id : FID (e.g. 0x1D = FDP, 0x1E = FDP Events)
          value      : CDW11 — feature-specific value / enable bit
          cdw12      : CDW12 — typically the Endurance Group ID for FDP features
        Command: nvme set-feature <dev> --feature-id=<fid> --value=<val> --cdw12=<cdw12>
        """
        return self.run_cmd([
            "set-feature", self.device,
            f"--feature-id={feature_id}",
            f"--value={value}",
            f"--cdw12={cdw12}",
        ], json_out=False)

    # ── Namespace Management ──────────────────────────────────────────────────

    def create_ns(self, nsze: int, ncap: int, flbas: int = 0,
                  dps: int = 0, nmic: int = 0,
                  endg_id: int = 1, nphndls: int = 0) -> dict:
        """
        Create a namespace.
          nsze     : Namespace Size (in LBAs)
          ncap     : Namespace Capacity (in LBAs)
          flbas    : Formatted LBA Size index
          dps      : Data Protection Settings
          nmic     : Namespace Multi-path I/O and NS Sharing Capabilities
          endg_id  : Endurance Group ID
          nphndls  : Number of Placement Handles to assign
        Command: nvme create-ns <dev> --nsze=... --ncap=... ...
        """
        args = [
            "create-ns", self.device,
            f"--nsze={nsze}",
            f"--ncap={ncap}",
            f"--flbas={flbas}",
            f"--dps={dps}",
            f"--nmic={nmic}",
            f"--endg-id={endg_id}",
        ]
        if nphndls > 0:
            args.append(f"--nphndls={nphndls}")
        return self.run_cmd(args, json_out=False)

    def delete_ns(self, nsid: int) -> dict:
        """
        Delete a namespace.
        Command: nvme delete-ns <dev> --namespace-id=<nsid>
        """
        return self.run_cmd([
            "delete-ns", self.device,
            f"--namespace-id={nsid}",
        ], json_out=False)

    # ── Generic Get Log Page ──────────────────────────────────────────────────

    def get_log(self, log_id: int, log_len: int = 4096,
                offset: int = 0, bin_out: bool = False,
                lsp: int = 0, lsi: int = 0) -> dict:
        """
        Generic Get Log Page (admin command).
          log_id  : Log Page Identifier (e.g. 0x20 = FDP configs, 0x23 = FDP events)
          log_len : Number of bytes to retrieve
          offset  : Byte offset into the log page
          bin_out : If True, return raw binary output; skip JSON parsing
          lsp     : Log Specific Parameter (CDW10 bits [15:8])
          lsi     : Log Specific Identifier (CDW11 bits [31:16], e.g. endurance group)
        Command: nvme get-log <dev> --log-id=<id> --log-len=<n> [--lpo=<offset>]
        """
        args = [
            "get-log", self.device,
            f"--log-id={log_id}",
            f"--log-len={log_len}",
        ]
        if offset:
            args.append(f"--lpo={offset}")
        if lsp:
            args.append(f"--lsp={lsp}")
        if lsi:
            args.append(f"--lsi={lsi}")
        return self.run_cmd(args, json_out=(not bin_out))

    # ── Directives ────────────────────────────────────────────────────────────

    def dir_receive(self, dir_type: int, dir_oper: int,
                    namespace: int = 1, data_len: int = 4096,
                    dir_spec: int = 0) -> dict:
        return self.run_cmd([
            "dir-receive", self.device,
            f"--dir-type={dir_type}",
            f"--dir-oper={dir_oper}",
            f"--namespace-id={namespace}",
            f"--data-len={data_len}",
        ])

    def dir_send(self, dir_type: int, dir_oper: int,
                 namespace: int = 1, dir_spec: int = 0,
                 data_len: int = 0) -> dict:
        return self.run_cmd([
            "dir-send", self.device,
            f"--dir-type={dir_type}",
            f"--dir-oper={dir_oper}",
            f"--namespace-id={namespace}",
            f"--dspec={dir_spec}",
        ], json_out=False)

    # ── Controller / Subsystem Reset ──────────────────────────────────────────

    def controller_reset(self) -> dict:
        """
        nvme reset <dev> — triggers CC.EN=0 then CC.EN=1 via kernel driver.
        Requires a block device path (e.g. /dev/nvme0), not a namespace path.
        """
        return self.run_cmd(["reset", _block_device(self.device)], json_out=False)

    def subsystem_reset(self) -> dict:
        """
        nvme subsystem-reset <dev> — NVM Subsystem Reset (NSSR).
        Requires a block device path (e.g. /dev/nvme0), not a namespace path.
        """
        return self.run_cmd(["subsystem-reset", _block_device(self.device)], json_out=False)

    def ns_rescan(self) -> dict:
        """nvme ns-rescan <dev> — ask the kernel to rescan namespaces."""
        return self.run_cmd(["ns-rescan", self.device], json_out=False)

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