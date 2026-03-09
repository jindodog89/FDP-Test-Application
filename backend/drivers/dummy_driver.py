"""
DummyNVMeDriver  —  software-simulated NVMe device for GUI / test debugging.

Two pre-canned device paths are registered:
  /dev/nvme-dummy-fdp-on   — FDP enabled,  8 RU handles, realistic log data
  /dev/nvme-dummy-fdp-off  — FDP disabled, 1 namespace,  no FDP log pages

All run_cmd() / run_command() calls are intercepted; nothing is sent to the
kernel.  Return values match the shape that NVMeCliDriver produces so every
test helper (extract_ruhs, etc.) works identically against real hardware.
"""

import json
import time
import random

# ── sentinel paths ────────────────────────────────────────────────────────────
DUMMY_FDP_ON  = "/dev/nvme-dummy-fdp-on"
DUMMY_FDP_OFF = "/dev/nvme-dummy-fdp-off"
DUMMY_DEVICES = {DUMMY_FDP_ON, DUMMY_FDP_OFF}

# ── canned data helpers ───────────────────────────────────────────────────────

def _ok(data, cmd="[dummy]"):
    """Wrap a data dict in the same envelope run_cmd() produces."""
    return {
        "stdout": json.dumps(data),
        "stderr": "",
        "rc":     0,
        "cmd":    cmd,
        "data":   data,
    }

def _err(msg, cmd="[dummy]"):
    return {
        "stdout": "",
        "stderr": msg,
        "rc":     1,
        "cmd":    cmd,
    }

def _ok_text(text, cmd="[dummy]"):
    return {"stdout": text, "stderr": "", "rc": 0, "cmd": cmd}


# ── per-device canned data ────────────────────────────────────────────────────

def _make_id_ctrl(fdp_enabled: bool) -> dict:
    ctratt = (1 << 19) if fdp_enabled else 0          # bit 19 = FDP capability
    return {
        "vid": "0x1234",
        "mn":  "Dummy NVMe SSD FDP-ON" if fdp_enabled else "Dummy NVMe SSD FDP-OFF",
        "sn":  "DUMMY0000001" if fdp_enabled else "DUMMY0000002",
        "fr":  "1.0.0",
        "ctratt": ctratt,
        "oacs":   0x06,
        "oncs":   0x46,
        "nn":     1,
    }


def _make_id_ns(fdp_enabled: bool) -> dict:
    nsfeat = (1 << 4) if fdp_enabled else 0            # bit 4 = FDP namespace
    return {
        "nsze":   2097152,
        "ncap":   2097152,
        "nuse":   1048576,
        "nsfeat": nsfeat,
        "nlbaf":  0,
        "flbas":  4,
        "phndls": 8 if fdp_enabled else 0,
        "lbaf": [{"ms": 0, "ds": 12, "rp": 0}],       # 4 KiB sectors
    }


def _make_fdp_status() -> dict:
    """nvme fdp status <dev>  — feature enable state (no -n flag)."""
    return {"fdpEnabled": True, "fdpSupported": True}


def _make_ruhs(n_handles: int = 8) -> dict:
    """
    nvme fdp status <dev> -n <nsid>  — Reclaim Unit Handle Status.
    nvme-cli JSON: {"nruhsd": N, "ruhid": [{ruhid, ruamw}, ...]}
    """
    handles = []
    for i in range(n_handles):
        handles.append({
            "ruhid": i,
            "ruamw": random.randint(500_000, 2_000_000),   # sectors available
        })
    return {"nruhsd": n_handles, "ruhid": handles}


def _make_fdp_configs() -> dict:
    return {
        "fdp_configurations": [
            {
                "fdpcid": 0,
                "nrg":    1,
                "nruh":   8,
                "maxpids": 8,
                "nnss":   1,
                "fdpa":   0,
            }
        ]
    }


def _make_fdp_usage() -> dict:
    """nvme fdp usage <dev> -e <endgrp>"""
    handles = []
    for i in range(8):
        handles.append({
            "phndl":  i,
            "ruamw":  random.randint(500_000, 2_000_000),
            "nruhsd": 8,
        })
    return {"fdp_usage": handles}


def _make_fdp_events() -> dict:
    """nvme fdp events <dev> -e <endgrp>"""
    return {
        "nevents": 3,
        "events": [
            {"type": 0x00, "fdpef": 0, "pid": 0, "nsid": 1, "lbaf": 4},
            {"type": 0x01, "fdpef": 0, "pid": 1, "nsid": 1, "lbaf": 4},
            {"type": 0x02, "fdpef": 0, "pid": 2, "nsid": 1, "lbaf": 4},
        ],
    }


def _make_fdp_stats() -> dict:
    """nvme fdp stats <dev> -e <endgrp>  — Log ID 0x22."""
    return {
        "hbmw":    0,
        "hbmw_hi": 0,
        "mbmw":    random.randint(10_000_000, 500_000_000),
        "mbmw_hi": 0,
        "mbe":     random.randint(0, 1000),
        "mbe_hi":  0,
    }


def _make_dir_receive_identify() -> dict:
    """Directive Receive, Type=0 Op=1 (Identify)."""
    return {
        "supported": 1,
        "enabled":   1,
        "persistent": 1,
    }


def _make_list_ns() -> dict:
    return {"nsid_list": [1]}


def _make_smart_log() -> dict:
    return {
        "critical_warning":          0,
        "temperature":               310,
        "avail_spare":               100,
        "avail_spare_threshold":     10,
        "percent_used":              0,
        "data_units_read":           1024,
        "data_units_written":        2048,
        "host_read_commands":        5000,
        "host_write_commands":       3000,
        "controller_busy_time":      10,
        "power_cycles":              5,
        "power_on_hours":            100,
        "unsafe_shutdowns":          2,
        "media_errors":              0,
        "num_err_log_entries":       0,
    }


# ── the driver class ──────────────────────────────────────────────────────────

class DummyNVMeDriver:
    """
    Drop-in replacement for NVMeCliDriver that serves canned responses.
    Instantiate with either DUMMY_FDP_ON or DUMMY_FDP_OFF.
    """

    def __init__(self, device: str):
        self.device      = device
        self.fdp_enabled = (device == DUMMY_FDP_ON)
        self._fdp_feature_enabled = self.fdp_enabled   # toggleable by tests
        self._stats_snapshot = _make_fdp_stats()        # stable across calls until reset

    @property
    def driver_name(self) -> str:
        return "dummy"

    # ── low-level stubs (tests call these directly sometimes) ─────────────────

    def run_command(self, args: list) -> dict:
        """Intercept any nvme command and route to the appropriate stub."""
        result = self.run_cmd(args, json_out=False)
        return {
            "stdout":     result["stdout"],
            "stderr":     result["stderr"],
            "returncode": result["rc"],
            "command":    result["cmd"],
        }

    def run_cmd(self, args: list, json_out: bool = True) -> dict:
        """
        Route by command verb.  args[0] is always the nvme subcommand when
        called from driver methods; when called raw it may include 'nvme'.
        """
        # Strip leading 'nvme' if present
        if args and args[0] == "nvme":
            args = args[1:]

        cmd_str = "nvme " + " ".join(str(a) for a in args)
        verb    = args[0] if args else ""
        sub     = args[1] if len(args) > 1 else ""

        # ── dispatch ──────────────────────────────────────────────────────────

        # id-ctrl
        if verb == "id-ctrl":
            return _ok(_make_id_ctrl(self.fdp_enabled), cmd_str)

        # id-ns
        if verb == "id-ns":
            return _ok(_make_id_ns(self.fdp_enabled), cmd_str)

        # list-ns
        if verb == "list-ns":
            return _ok(_make_list_ns(), cmd_str)

        # smart-log
        if verb == "smart-log":
            return _ok(_make_smart_log(), cmd_str)

        # reset / subsystem-reset / ns-rescan
        if verb in ("reset", "subsystem-reset", "ns-rescan"):
            time.sleep(0.05)   # tiny artificial delay
            return _ok_text(f"[dummy] {cmd_str}: Success", cmd_str)

        # fdp …
        if verb == "fdp":
            return self._dispatch_fdp(sub, args, cmd_str)

        # get-feature (FID 0x1D — FDP enable)
        if verb == "get-feature":
            fdp_val = 1 if self._fdp_feature_enabled else 0
            return _ok({"fid": 0x1d, "cdw11": 1, "result": fdp_val}, cmd_str)

        # set-feature (FID 0x1D — FDP enable/disable)
        if verb == "set-feature":
            # parse --cdw11 to detect enable(1)/disable(0)
            for a in args:
                if "cdw12" in str(a) or "cdw11" in str(a):
                    try:
                        val = int(str(a).split("=")[-1], 0)
                        self._fdp_feature_enabled = bool(val & 1)
                    except ValueError:
                        pass
            return _ok_text(f"[dummy] set-feature FDP: Success", cmd_str)

        # dir-receive
        if verb == "dir-receive":
            return _ok(_make_dir_receive_identify(), cmd_str)

        # dir-send
        if verb == "dir-send":
            return _ok_text("[dummy] dir-send: Success", cmd_str)

        # write
        if verb == "write":
            time.sleep(0.01)
            return _ok_text("[dummy] write: Success, completed 1/1 commands", cmd_str)

        # io-mgmt-send
        if verb == "io-mgmt-send":
            return _ok_text("[dummy] io-mgmt-send: Success", cmd_str)

        # io-mgmt-recv
        if verb == "io-mgmt-recv":
            return _ok_text("[dummy] io-mgmt-recv: Success", cmd_str)

        # admin-passthru / io-passthru
        if verb in ("admin-passthru", "io-passthru"):
            return _ok({}, cmd_str)

        # create-ns / attach-ns / detach-ns / delete-ns
        if verb == "create-ns":
            return _ok_text("[dummy] create-ns: Success, created nsid:1", cmd_str)
        if verb == "attach-ns":
            return _ok_text("[dummy] attach-ns: Success", cmd_str)
        if verb in ("detach-ns", "delete-ns"):
            return _ok_text(f"[dummy] {verb}: Success", cmd_str)

        # fallback: unknown command
        return _err(f"[dummy] unrecognised command: {cmd_str}", cmd_str)

    # ── FDP sub-dispatch ──────────────────────────────────────────────────────

    def _dispatch_fdp(self, sub: str, args: list, cmd_str: str) -> dict:
        has_n = any(str(a).startswith("-n") or str(a) == "--namespace-id" for a in args)

        if sub == "status":
            if has_n:
                # RUHS  (nvme fdp status <dev> -n <nsid>)
                if self.fdp_enabled:
                    return _ok(_make_ruhs(8), cmd_str)
                else:
                    return _err("[dummy] FDP not enabled — no RUHS data", cmd_str)
            else:
                # FDP feature enable state
                data = {"fdpEnabled": self._fdp_feature_enabled,
                        "fdpSupported": self.fdp_enabled}
                return _ok(data, cmd_str)

        if sub == "configs":
            if self.fdp_enabled:
                return _ok(_make_fdp_configs(), cmd_str)
            return _err("[dummy] FDP not enabled — no configs", cmd_str)

        if sub == "usage":
            if self.fdp_enabled:
                return _ok(_make_fdp_usage(), cmd_str)
            return _err("[dummy] FDP not enabled — no usage data", cmd_str)

        if sub == "events":
            if self.fdp_enabled:
                return _ok(_make_fdp_events(), cmd_str)
            return _err("[dummy] FDP not enabled — no events", cmd_str)

        if sub == "stats":
            if self.fdp_enabled:
                return _ok(self._stats_snapshot, cmd_str)
            return _err("[dummy] FDP not enabled — no stats", cmd_str)

        return _err(f"[dummy] unknown fdp sub-command: {sub}", cmd_str)

    # ── Named wrappers (mirror NVMeCliDriver's public API) ────────────────────

    def get_controller_identity(self) -> dict:
        return self.run_cmd(["id-ctrl", self.device])

    def id_ctrl(self) -> dict:
        return self.get_controller_identity()

    def get_namespace_identity(self, namespace: int = 1) -> dict:
        return self.run_cmd(["id-ns", self.device, f"-n={namespace}"])

    def id_ns(self, namespace: int = 1) -> dict:
        return self.get_namespace_identity(namespace)

    def list_namespaces(self) -> dict:
        return self.run_cmd(["list-ns", self.device, "--all"])

    def get_fdp_status(self) -> dict:
        return self.run_cmd(["fdp", "status", self.device])

    def fdp_status(self) -> dict:
        return self.get_fdp_status()

    def get_fdp_configs(self, endgrp: int = 1) -> dict:
        return self.run_cmd(["fdp", "configs", self.device, f"--endgrp-id={endgrp}"])

    def fdp_configs(self, endgrp: int = 1) -> dict:
        return self.get_fdp_configs(endgrp)

    def get_reclaim_unit_handle_status(self, namespace: int = 1) -> dict:
        return self.run_cmd(["fdp", "status", self.device, "-n", str(namespace)])

    def fdp_ruhs(self, ns: int = 1) -> dict:
        return self.get_reclaim_unit_handle_status(ns)

    def get_fdp_placement_ids(self, endgrp: int = 1) -> dict:
        return self.run_cmd(["fdp", "usage", self.device, "-e", str(endgrp)])

    def fdp_usage(self, endgrp: int = 1) -> dict:
        return self.get_fdp_placement_ids(endgrp)

    def get_fdp_events(self, endgrp: int = 1) -> dict:
        return self.run_cmd(["fdp", "events", self.device, "-e", str(endgrp)])

    def fdp_events(self, endgrp: int = 1) -> dict:
        return self.get_fdp_events(endgrp)

    def get_fdp_stats(self, endgrp: int = 1) -> dict:
        return self.run_cmd(["fdp", "stats", self.device, "-e", str(endgrp)])

    def fdp_stats(self, endgrp: int = 1) -> dict:
        return self.get_fdp_stats(endgrp)

    def smart_log(self) -> dict:
        return self.run_cmd(["smart-log", self.device])

    def controller_reset(self) -> dict:
        return self.run_cmd(["reset", self.device], json_out=False)

    def subsystem_reset(self) -> dict:
        return self.run_cmd(["subsystem-reset", self.device], json_out=False)

    def ns_rescan(self) -> dict:
        return self.run_cmd(["ns-rescan", self.device], json_out=False)

    def get_feature(self, fid: int, cdw11: int = 0) -> dict:
        return self.run_cmd(["get-feature", self.device,
                             f"--feature-id={fid}", f"--cdw11={cdw11}"])

    def dir_receive(self, dir_type: int, dir_oper: int,
                    namespace: int = 1, data_len: int = 4096,
                    dir_spec: int = 0) -> dict:
        return self.run_cmd([
            "dir-receive", self.device,
            f"-D={dir_type}", f"-O={dir_oper}",
            f"-n={namespace}", f"--data-len={data_len}",
        ])

    def dir_send(self, dir_type: int, dir_oper: int,
                 namespace: int = 1, dir_spec: int = 0,
                 data_len: int = 0) -> dict:
        return self.run_cmd([
            "dir-send", self.device,
            f"-D={dir_type}", f"-O={dir_oper}",
            f"-n={namespace}", f"--dspec={dir_spec}",
        ], json_out=False)

    def write(self, namespace: int = 1, start_block: int = 0,
              block_count: int = 0, data_size: int = 4096,
              data_source: str = "/dev/zero", dtype: int = 0,
              dspec: int = 0) -> dict:
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

    def io_mgmt_send(self, namespace: int = 1, cdw12: int = 0,
                     data_path: str = None, data_len: int = 4096) -> dict:
        args = ["io-mgmt-send", self.device,
                f"--namespace-id={namespace}",
                f"--cdw12={cdw12}",
                f"--data-len={data_len}"]
        if data_path:
            args.append(f"--data={data_path}")
        return self.run_cmd(args, json_out=False)

    def io_mgmt_recv(self, namespace: int = 1, cdw12: int = 0,
                     data_len: int = 4096) -> dict:
        return self.run_cmd([
            "io-mgmt-recv", self.device,
            f"--namespace-id={namespace}",
            f"--cdw12={cdw12}",
            f"--data-len={data_len}",
        ], json_out=False)

    def admin_passthru(self, opcode: int, cdw10: int = 0, cdw12: int = 0,
                       data_len: int = 4096, read: bool = True) -> dict:
        return self.run_cmd(["admin-passthru", self.device,
                             f"--opcode={opcode}",
                             f"--cdw10={cdw10}",
                             f"--cdw12={cdw12}",
                             f"--data-len={data_len}"])

    def io_passthru(self, opcode: int, namespace: int = 1, cdw12: int = 0,
                    data_len: int = 4096, read: bool = True) -> dict:
        return self.run_cmd(["io-passthru", self.device,
                             f"--namespace-id={namespace}",
                             f"--opcode={opcode}",
                             f"--cdw12={cdw12}",
                             f"--data-len={data_len}"])
